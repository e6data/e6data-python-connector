"""Synthetic local gRPC contracts for continuous sync result download.

The service supplies serialized test rows only. It is not a production query engine.
"""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import grpc
import pytest

from e6data_python_connector import Connection
from e6data_python_connector import e6data_grpc as engine
from e6data_python_connector.datainputstream import FieldInfo
from e6data_python_connector.exceptions import IncompleteResultError, ProgrammingError
from e6data_python_connector.server import e6x_engine_pb2 as pb, e6x_engine_pb2_grpc as bindings
from test.unit.test_async_result_batch_v2 import chunk


class SyntheticResults(bindings.QueryEngineServiceServicer):
    def __init__(self, responses):
        self.responses = responses
        self.requests = []
        self.v1_requests = []
        self.v1_responses = []
        self.cleanups = []
        self.entered = [threading.Event() for _ in responses]
        self.lock = threading.Lock()
        self.response_delay = 0
        self.request_budgets = []
        self.prepare_remaining = None
        self.prepare_requests = []

    def getNextResultBatchV2(self, request, context):
        with self.lock:
            index = len(self.requests)
            self.requests.append(request)
        if index >= len(self.responses):
            context.abort(grpc.StatusCode.OUT_OF_RANGE, 'Unexpected synthetic fetch.')
        self.entered[index].set()
        self.request_budgets.append(context.time_remaining())
        if self.response_delay:
            threading.Event().wait(self.response_delay)
        response = self.responses[index]
        if isinstance(response, grpc.StatusCode):
            context.abort(response, 'Synthetic result transport failure.')
        return response

    def getNextResultBatch(self, request, context):
        with self.lock:
            index = len(self.v1_requests)
            self.v1_requests.append(request)
        if index >= len(self.v1_responses):
            context.abort(grpc.StatusCode.UNIMPLEMENTED, 'No synthetic V1 response configured.')
        return self.v1_responses[index]

    def prepareStatement(self, request, context):
        self.prepare_requests.append(request)
        self.prepare_remaining = context.time_remaining()
        context.abort(grpc.StatusCode.UNIMPLEMENTED, 'Synthetic prepare boundary.')

    def cancelQuery(self, request, context):
        self.cleanups.append(request)
        return pb.CancelQueryResponse()

    def clearOrCancelQuery(self, request, context):
        self.cleanups.append(request)
        return pb.ClearOrCancelQueryResponse()


def envelope(values, *, terminal=False, session='synthetic-session'):
    return pb.GetNextResultBatchV2Response(resultBatches=[chunk(rows) for rows in values],
                                        endOfStream=terminal, sessionId=session)


@pytest.fixture
def local_results():
    resources = []

    def start(responses, **options):
        service = SyntheticResults(responses)
        server = grpc.server(ThreadPoolExecutor(max_workers=2))
        bindings.add_QueryEngineServiceServicer_to_server(service, server)
        port = server.add_insecure_port('127.0.0.1:0')
        server.start()
        conn = Connection(host='127.0.0.1', port=port, username='synthetic-user',
                          password='synthetic-input', require_fastbinary=False, auto_resume=False,
                          enable_result_batch_v2=True, grpc_options={'grpc_prepare_timeout': 2}, **options)
        cursor = conn.cursor()
        cursor._query_id = 'synthetic-query'
        cursor._engine_ip = '127.0.0.1'
        cursor._result_session_id = 'synthetic-session'
        cursor._query_columns_description = [FieldInfo('value', 'LONG', '', '')]
        cursor._is_metadata_updated = True
        resources.append((server, conn, cursor))
        return service, conn, cursor

    yield start
    for server, conn, cursor in resources:
        cursor.close(timeout=1)
        conn.close()
        server.stop(0).wait(timeout=2)


def test_next_rpc_starts_before_current_envelope_is_decoded(local_results, monkeypatch):
    service, _, cursor = local_results([
        envelope([[1], [2]], session='rotated-one'),
        envelope([[3]], terminal=True, session='rotated-two')])
    real_decode = engine.decode_result_batches

    def decode_after_next_request(columns, payloads):
        assert service.entered[1].wait(1), 'N+1 must start before decoding N'
        return real_decode(columns, payloads)

    monkeypatch.setattr(engine, 'decode_result_batches', decode_after_next_request)
    assert cursor.fetch_batch() == [[1]]
    assert cursor.fetch_batch() == [[2]]
    assert cursor.fetch_batch() == [[3]]
    assert cursor.fetch_batch() is None
    assert len(service.requests) == 2
    assert service.requests[1].sessionId == 'rotated-one'


def test_pending_error_waits_until_valid_current_chunks_are_drained(local_results):
    service, _, cursor = local_results([envelope([[1], [2]]), grpc.StatusCode.UNAVAILABLE])
    assert cursor.fetch_batch() == [[1]]
    assert service.entered[1].wait(1)
    pending = cursor._pending_fetch
    pending.handle.result(timeout=1)
    assert cursor.fetch_batch() == [[2]]
    with pytest.raises(grpc.RpcError) as caught:
        cursor.fetch_batch()
    assert caught.value.code() == grpc.StatusCode.UNAVAILABLE
    with pytest.raises(IncompleteResultError):
        cursor.fetch_batch()
    assert len(service.requests) == 2


@pytest.mark.parametrize('cleanup', ['clear', 'cancel'])
def test_prefetch_handoff_preserves_cleanup_session(local_results, monkeypatch, cleanup):
    service, conn, cursor = local_results([
        envelope([[1]], session='rotated-one'),
        envelope([[2]], terminal=True, session='rotated-two')])
    assert cursor.fetch_batch() == [[1]]
    record = cursor._pending_fetch
    record.handle.result(timeout=1)
    entered, resume = threading.Event(), threading.Event()
    original_take = record.take

    def paused_take():
        entered.set()
        assert resume.wait(3)
        return original_take()

    monkeypatch.setattr(record, 'take', paused_take)
    with ThreadPoolExecutor(max_workers=1) as executor:
        fetch = executor.submit(cursor.fetch_batch)
        try:
            assert entered.wait(1)
            if cleanup == 'clear':
                cursor.clear(timeout=1)
            else:
                cursor.cancel(cursor.query_id)
            assert service.cleanups[-1].sessionId == 'rotated-two'
        finally:
            resume.set()
        with pytest.raises(IncompleteResultError):
            fetch.result(timeout=2)


def test_cancel_during_foreground_fetch_fences_rows_and_retains_late_session(local_results, monkeypatch):
    service, conn, cursor = local_results([
        envelope([[1]], terminal=True, session='late-foreground-session')])
    entered, resume, retired = threading.Event(), threading.Event(), threading.Event()
    original_rpc = conn.client.getNextResultBatchV2
    original_retire = cursor._retire_result_work

    def paused_rpc(*args, **kwargs):
        response = original_rpc(*args, **kwargs)
        entered.set()
        assert resume.wait(3)
        return response

    def retire(**kwargs):
        result = original_retire(**kwargs)
        if not kwargs.get('wait'):
            retired.set()
        return result

    monkeypatch.setattr(conn.client, 'getNextResultBatchV2', paused_rpc)
    monkeypatch.setattr(cursor, '_retire_result_work', retire)
    with ThreadPoolExecutor(max_workers=2) as executor:
        fetch = executor.submit(cursor.fetch_batch)
        try:
            assert entered.wait(1)
            cancellation = executor.submit(cursor.cancel, cursor.query_id)
            assert retired.wait(1)
        finally:
            resume.set()
        with pytest.raises(IncompleteResultError):
            fetch.result(timeout=2)
        cancellation.result(timeout=2)
    assert not cursor._result_batches.pop()
    assert cursor.query_id == 'synthetic-query'
    cursor.clear(timeout=1)
    assert service.cleanups[-1].sessionId == 'late-foreground-session'
    assert len(service.requests) == 1


def test_prefetched_unimplemented_falls_back_once_without_reusing_failed_record(local_results, monkeypatch):
    service, conn, cursor = local_results([
        envelope([[1]]), grpc.StatusCode.UNIMPLEMENTED])
    calls = []

    def v1(request, **kwargs):
        calls.append(request)
        return pb.GetNextResultBatchResponse(resultBatch=chunk([2]))

    monkeypatch.setattr(conn.client, 'getNextResultBatch', v1)
    assert cursor.fetch_batch() == [[1]]
    assert cursor.fetch_batch() == [[2]]
    assert cursor._result_protocol == 'v1'
    assert cursor._pending_fetch is None
    assert len(service.requests) == 2
    assert len(calls) == 1


def test_cancellation_between_transport_and_acceptance_cannot_publish(local_results, monkeypatch):
    service, conn, cursor = local_results([
        envelope([[1]], terminal=True, session='accepted-session')])
    entered, resume = threading.Event(), threading.Event()
    original_accept = cursor._accept_result_batch

    def paused_accept(*args, **kwargs):
        entered.set()
        assert resume.wait(3)
        return original_accept(*args, **kwargs)

    monkeypatch.setattr(cursor, '_accept_result_batch', paused_accept)
    with ThreadPoolExecutor(max_workers=1) as executor:
        fetch = executor.submit(cursor.fetch_batch)
        try:
            assert entered.wait(1)
            cursor.cancel(cursor.query_id)
        finally:
            resume.set()
        with pytest.raises(IncompleteResultError):
            fetch.result(timeout=2)
    assert service.cleanups[-1].sessionId == 'accepted-session'
    assert cursor._result_batches.pop() is None


def test_stale_fetch_failure_does_not_clear_reused_cursor_results(local_results, monkeypatch):
    service, conn, cursor = local_results([envelope([[1]], terminal=True)])
    entered, resume = threading.Event(), threading.Event()
    original_accept = cursor._accept_result_batch

    def paused_accept(*args, **kwargs):
        entered.set()
        assert resume.wait(3)
        return original_accept(*args, **kwargs)

    monkeypatch.setattr(cursor, '_accept_result_batch', paused_accept)
    with ThreadPoolExecutor(max_workers=1) as executor:
        fetch = executor.submit(cursor.fetch_batch)
        try:
            assert entered.wait(1)
            cursor.clear(timeout=1)
            # Establish an explicitly synthetic replacement query after clear.
            cursor._query_id = 'replacement-query'
            cursor._reset_result_batch_state()
            cursor._result_batches.accept([[[99]]], True)
        finally:
            resume.set()
        with pytest.raises(IncompleteResultError):
            fetch.result(timeout=2)
    assert cursor._result_failure is None
    assert cursor.query_id == 'replacement-query'
    assert cursor.fetch_batch() == [[99]]


def test_stale_identity_cannot_consume_current_pending_record(local_results):
    service, conn, cursor = local_results([
        envelope([[1]]), envelope([[2]], terminal=True)])
    assert cursor.fetch_batch() == [[1]]
    record = cursor._pending_fetch
    record.handle.result(timeout=1)
    old_identity = list(cursor._result_identity())
    old_identity[1] -= 1
    with pytest.raises(IncompleteResultError):
        cursor._take_prefetch(time.monotonic() + 1, record=record, identity=tuple(old_identity))
    assert cursor._pending_fetch is record
    assert cursor._result_failure is None
    assert cursor.fetch_batch() == [[2]]


def test_interrupt_after_foreground_rpc_cannot_resume_consumed_results(local_results, monkeypatch):
    service, conn, cursor = local_results([
        envelope([[1]]), envelope([[2]], terminal=True)])
    original_rpc = conn.client.getNextResultBatchV2
    interruption = KeyboardInterrupt('synthetic-interruption')

    def interrupted_rpc(*args, **kwargs):
        original_rpc(*args, **kwargs)
        raise interruption

    monkeypatch.setattr(conn.client, 'getNextResultBatchV2', interrupted_rpc)
    with pytest.raises(KeyboardInterrupt) as caught:
        cursor.fetch_batch()
    assert caught.value is interruption
    with pytest.raises(IncompleteResultError):
        cursor.fetch_batch()
    assert len(service.requests) == 1


def test_cancel_before_sync_decode_admission_does_not_start_worker_jobs(local_results, monkeypatch):
    from e6data_python_connector.result_decode import DecoderLease

    service, conn, cursor = local_results([envelope([[1], [2]], terminal=True)])
    lease = DecoderLease()
    conn._decoder_lease = lease
    lease.start(time.monotonic() + 5)
    entered, resume, admitted = threading.Event(), threading.Event(), threading.Event()
    original_decode, original_parallel = lease.decode, lease._runtime._parallel

    def paused_decode(*args, **kwargs):
        entered.set()
        assert resume.wait(3)
        return original_decode(*args, **kwargs)

    def observe_parallel(*args, **kwargs):
        admitted.set()
        return original_parallel(*args, **kwargs)

    monkeypatch.setattr(lease, 'decode', paused_decode)
    monkeypatch.setattr(lease._runtime, '_parallel', observe_parallel)
    with ThreadPoolExecutor(max_workers=1) as executor:
        fetch = executor.submit(cursor.fetch_batch)
        try:
            assert entered.wait(1)
            cursor.cancel(cursor.query_id)
        finally:
            resume.set()
        with pytest.raises(IncompleteResultError):
            fetch.result(timeout=2)
    assert not admitted.is_set()
    assert cursor._result_batches.pop() is None


def test_terminal_envelope_does_not_prefetch(local_results):
    service, _, cursor = local_results([envelope([[1], [2]], terminal=True)])
    assert cursor.fetchall() == [[1], [2]]
    assert cursor._pending_fetch is None
    assert len(service.requests) == 1


def test_downloads_all_serialized_responses_before_first_decode(local_results, monkeypatch):
    responses = [envelope([[i]], terminal=i == 7, session='session-%s' % i)
                 for i in range(8)]
    service, _, cursor = local_results(responses)
    original_decode = engine.decode_result_batches
    observed = []

    def decode_after_all_downloads(columns, payloads):
        if not observed:
            assert service.entered[-1].wait(2), 'All RPCs must run while first decode waits.'
            cursor._pending_fetch.handle.result(timeout=2)
            observed.append(cursor._pending_fetch.queued_count)
            assert cursor._pending_fetch.queued_count == 7
            assert cursor._pending_fetch.queued_bytes > 0
        return original_decode(columns, payloads)

    monkeypatch.setattr(engine, 'decode_result_batches', decode_after_all_downloads)
    assert cursor.fetchall() == [[i] for i in range(8)]
    assert observed == [7]
    assert len(service.requests) == 8
    assert [request.sessionId for request in service.requests[1:]] == [
        'session-%s' % i for i in range(7)]


def test_slow_application_does_not_pause_serialized_download(local_results):
    responses = [envelope([[i]], terminal=i == 6, session='session-%s' % i)
                 for i in range(7)]
    service, _, cursor = local_results(responses)
    assert cursor.fetch_batch() == [[0]]
    assert service.entered[-1].wait(2)
    record = cursor._pending_fetch
    record.handle.result(timeout=2)
    assert record.queued_count == 6
    assert record.session_id == 'session-6'
    assert cursor.fetchall() == [[i] for i in range(1, 7)]
    assert len(service.requests) == 7


def test_queued_transport_error_follows_all_successful_envelopes(local_results, monkeypatch):
    responses = [envelope([[i]], session='session-%s' % i) for i in range(6)]
    service, conn, cursor = local_results(responses + [grpc.StatusCode.UNAVAILABLE])
    original_rpc = conn.client.getNextResultBatchV2
    errors = []

    class ObserveTransport:
        """Minimal test double recording the actual local gRPC exception."""
        def __call__(self, *args, **kwargs):
            return original_rpc(*args, **kwargs)

        def future(self, *args, **kwargs):
            handle = original_rpc.future(*args, **kwargs)
            def record_error(completed):
                try:
                    completed.result()
                except grpc.RpcError as error:
                    errors.append(error)
            handle.add_done_callback(record_error)
            return handle

    monkeypatch.setattr(conn.client, 'getNextResultBatchV2', ObserveTransport())
    assert cursor.fetch_batch() == [[0]]
    assert service.entered[-1].wait(2)
    cursor._pending_fetch.handle.result(timeout=2)
    assert [cursor.fetch_batch() for _ in range(5)] == [[[i]] for i in range(1, 6)]
    with pytest.raises(grpc.RpcError) as caught:
        cursor.fetch_batch()
    assert caught.value is errors[0]
    assert len(service.requests) == 7
    with pytest.raises(IncompleteResultError):
        cursor.fetch_batch()


def test_close_clears_every_queued_payload_and_uses_latest_session(local_results):
    responses = [envelope([[i]], terminal=i == 6, session='session-%s' % i)
                 for i in range(7)]
    service, _, cursor = local_results(responses)
    assert cursor.fetch_batch() == [[0]]
    assert service.entered[-1].wait(2)
    record = cursor._pending_fetch
    record.handle.result(timeout=2)
    assert record.queued_count == 6
    cursor.close(timeout=1)
    assert record.queued_count == 0
    assert record.queued_bytes == 0
    assert service.cleanups[-1].sessionId == 'session-6'


def test_close_uses_rotated_session_from_discarded_pending_response(local_results):
    service, _, cursor = local_results([
        envelope([[1]], session='rotated-one'),
        envelope([[2]], terminal=True, session='rotated-two')])
    assert cursor.fetch_batch() == [[1]]
    assert service.entered[1].wait(1)
    cursor._pending_fetch.handle.result(timeout=1)
    cursor.close(timeout=1)
    assert cursor._cleanup_error is None
    assert service.cleanups[-1].sessionId == 'rotated-two'
    assert cursor._pending_fetch is None
    assert not cursor._retired_fetches


def test_connection_close_retires_pending_and_invalidates_cursor(local_results):
    service, conn, cursor = local_results([envelope([[1], [2]]), envelope([[3]], terminal=True)])
    assert cursor.fetch_batch() == [[1]]
    assert service.entered[1].wait(1)
    conn.close()
    with pytest.raises((ProgrammingError, IncompleteResultError)):
        cursor.fetch_batch()
    assert cursor._pending_fetch is None


@pytest.mark.parametrize('key', ['max_receive_message_length', 'grpc.max_receive_message_length'])
@pytest.mark.parametrize('value', [-1, 0, True, None, float('inf'), '4096'])
def test_v2_requires_finite_positive_receive_limit(key, value):
    with pytest.raises(ValueError, match='receive'):
        Connection(host='127.0.0.1', port=1, username='synthetic-user', password='synthetic-input',
                   require_fastbinary=False, auto_resume=False, enable_result_batch_v2=True,
                   grpc_options={key: value})


def test_v2_receive_limit_defaults_and_normalizes_prefix():
    base = dict(host='127.0.0.1', port=1, username='synthetic-user', password='synthetic-input',
                require_fastbinary=False, auto_resume=False)
    for options, expected in [({}, 64 * 1024 * 1024), ({'grpc.max_receive_message_length': 4096}, 4096)]:
        conn = Connection(**base, enable_result_batch_v2=True, grpc_options=options)
        try:
            configured = dict(conn._get_grpc_options)
            assert configured['grpc.max_receive_message_length'] == expected
            assert 'grpc.grpc.max_receive_message_length' not in configured
        finally:
            conn.close()
    conn = Connection(**base)
    try:
        assert dict(conn._get_grpc_options)['grpc.max_receive_message_length'] == -1
    finally:
        conn.close()


def test_empty_nonterminal_envelope_keeps_one_sequential_prefetch(local_results):
    service, _, cursor = local_results([envelope([]), envelope([[7]], terminal=True)])
    assert cursor.fetch_batch() == [[7]]
    assert cursor.fetch_batch() is None
    assert len(service.requests) == 2


def test_completed_prefetch_is_valid_after_its_transport_deadline(local_results):
    service, conn, cursor = local_results([envelope([[1]]), envelope([[2]], terminal=True)])
    conn.grpc_prepare_timeout = .05
    assert cursor.fetch_batch() == [[1]]
    assert service.entered[1].wait(1)
    pending = cursor._pending_fetch
    pending.handle.result(timeout=1)
    threading.Event().wait(conn.grpc_prepare_timeout + .01)
    assert cursor.fetch_batch() == [[2]]
    assert len(service.requests) == 2


def test_only_unimplemented_pending_error_selects_v1_fallback(local_results):
    service, _, cursor = local_results([envelope([[1], [2]]), grpc.StatusCode.UNIMPLEMENTED])
    assert cursor.fetch_batch() == [[1]]
    assert service.entered[1].wait(1)
    assert cursor.fetch_batch() == [[2]]
    with pytest.raises(grpc.RpcError) as caught:
        cursor.fetch_batch()
    assert caught.value.code() == grpc.StatusCode.UNIMPLEMENTED
    assert cursor._result_protocol == 'v1'
    with pytest.raises(IncompleteResultError):
        cursor.fetch_batch()
    assert len(service.requests) == 2


def test_decode_failure_retires_next_rpc_without_publishing_rows(local_results):
    response = pb.GetNextResultBatchV2Response(resultBatches=[chunk([1]), b'invalid thrift'],
                                             sessionId='rotated-one')
    _, _, cursor = local_results([response, envelope([[2]], terminal=True)])
    with pytest.raises(IncompleteResultError, match='decode_failed'):
        cursor.fetch_batch()
    assert cursor._pending_fetch is None
    assert cursor._result_batches.pop() is None
    with pytest.raises(IncompleteResultError):
        cursor.fetch_batch()


def test_sync_parallel_backend_decodes_real_envelope_in_order(local_results):
    _, conn, cursor = local_results([envelope([[1, 2], [3, 4]], terminal=True)])
    conn._start_result_decoder(time.monotonic() + 5)
    assert len(conn._decoder_lease.worker_pids) == 2
    assert cursor.fetchall() == [[1], [2], [3], [4]]


def test_inherited_cursor_rejects_fetch_before_using_parent_transport(local_results):
    _, _, cursor = local_results([envelope([[1]], terminal=True)])
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            cursor.fetch_batch()
        except ProgrammingError:
            os.write(write_fd, b'rejected')
        finally:
            os._exit(0)
    os.close(write_fd)
    try:
        assert os.read(read_fd, 32) == b'rejected'
    finally:
        os.close(read_fd)
        os.waitpid(pid, 0)


def test_connection_is_rejected_inside_a_decode_child_before_auth(monkeypatch):
    import multiprocessing
    from e6data_python_connector.result_decode_worker import WORKER_PREFIX
    monkeypatch.setattr(multiprocessing.current_process(), 'name', WORKER_PREFIX + 'contract')
    with pytest.raises(ValueError, match='decode worker'):
        Connection(host='127.0.0.1', port=1, username='synthetic-user', password='synthetic-input',
                   require_fastbinary=False, auto_resume=False)


def test_decoder_startup_happens_before_prepare_and_debits_execute_deadline(local_results):
    service, conn, cursor = local_results([])
    conn._session_id = 'synthetic-session'
    with pytest.raises(grpc.RpcError) as caught:
        cursor.execute('synthetic statement that the local service rejects')
    assert caught.value.code() == grpc.StatusCode.UNIMPLEMENTED
    assert len(conn._decoder_lease.worker_pids) == 2
    assert 0 < service.prepare_remaining < conn.grpc_prepare_timeout


def test_unsafe_cursor_cleanup_prevents_pool_requeue(local_results):
    from e6data_python_connector.connection_pool import ConnectionPool, PooledConnection
    # The generated base service rejects clear when no safe cleanup identity exists.
    service, conn, cursor = local_results([])
    cursor._result_session_id = None
    conn._session_id = None
    pool = ConnectionPool(host='127.0.0.1', port=1, username='synthetic-user',
                          password='synthetic-input', min_size=0, max_size=1,
                          require_fastbinary=False, auto_resume=False,
                          enable_result_batch_v2=True)
    pooled = PooledConnection(conn, pool)
    pooled._cursor = cursor
    pooled.in_use = True
    pool._all_connections.append(pooled)
    pool._created_connections = 1
    pool._active_connections = 1
    pool.return_connection(pooled)
    assert pool._pool.qsize() == 0
    assert pooled not in pool._all_connections
    assert pooled._cursor is cursor
    assert cursor._cleanup_error is not None


def test_cancellation_during_prefetch_preparation_prevents_late_dispatch(local_results, monkeypatch):
    service, conn, cursor = local_results([envelope([[1]]), envelope([[2]], terminal=True)])
    preparing = threading.Event()
    resume = threading.Event()
    original_metadata = conn._call_metadata
    original_decode = engine.decode_result_batches
    calls = 0

    def prepare_metadata(**options):
        nonlocal calls
        calls += 1
        if calls == 2:
            preparing.set()
            assert resume.wait(2)
        return original_metadata(**options)

    def decode_after_transport_has_a_chance(columns, payloads):
        service.entered[1].wait(.1)
        return original_decode(columns, payloads)

    monkeypatch.setattr(conn, '_call_metadata', prepare_metadata)
    monkeypatch.setattr(engine, 'decode_result_batches', decode_after_transport_has_a_chance)
    with ThreadPoolExecutor(max_workers=1) as executor:
        fetch = executor.submit(cursor.fetch_batch)
        assert preparing.wait(1)
        cursor.cancel(cursor.query_id)
        resume.set()
        with pytest.raises(IncompleteResultError):
            fetch.result(timeout=2)
    assert len(service.requests) == 1
    assert cursor._pending_fetch is None


def test_unsettled_retirement_keeps_old_query_and_late_cleanup_session(local_results):
    from concurrent.futures import Future
    from e6data_python_connector.result_prefetch import PendingFetch
    service, conn, cursor = local_results([])
    transport = Future()
    transport.set_running_or_notify_cancel()
    record = PendingFetch(transport, None, session_id='synthetic-session')
    record.identity = cursor._result_identity()
    cursor._pending_fetch = record
    cursor.close(timeout=.01)
    assert cursor._cleanup_error is not None
    assert cursor.query_id == 'synthetic-query'
    assert cursor._retired_fetches == [record]
    replacement = conn.cursor()
    transport.set_result(envelope([], terminal=True, session='late-rotated-session'))
    assert replacement._result_session_id is None
    cursor.clear(timeout=1)
    assert service.cleanups[-1].sessionId == 'late-rotated-session'
    assert not cursor._retired_fetches
    assert cursor.query_id is None
    assert replacement._result_session_id is None
    replacement.close()


def test_keyboard_interrupt_during_decode_retires_pending_rpc(local_results, monkeypatch):
    service, _, cursor = local_results([envelope([[1]]), envelope([[2]], terminal=True)])

    def interrupted_decode(columns, payloads):
        assert service.entered[1].wait(1)
        raise KeyboardInterrupt()

    monkeypatch.setattr(engine, 'decode_result_batches', interrupted_decode)
    with pytest.raises(KeyboardInterrupt):
        cursor.fetch_batch()
    assert cursor._pending_fetch is None
    assert cursor._result_batches.pop() is None
    with pytest.raises(IncompleteResultError):
        cursor.fetch_batch()


def test_connection_close_retires_captured_v2_state_after_option_changes(local_results):
    service, conn, cursor = local_results([envelope([[1], [2]]), envelope([[3]], terminal=True)])
    assert cursor.fetch_batch() == [[1]]
    assert service.entered[1].wait(1)
    conn.enable_result_batch_v2 = False
    conn.close()
    assert cursor._pending_fetch is None
    with pytest.raises((ProgrammingError, IncompleteResultError)):
        cursor.fetch_batch()


@pytest.mark.parametrize('v2,budget,delay,expected_prepares', [
    (True, .05, .15, 1),
    (True, .3, .05, 2),
    (False, None, .15, 2),
])
def test_oauth_resume_keeps_original_prepare_budget_and_rpc_errors(v2, budget, delay, expected_prepares):
    from e6data_python_connector.cluster_server import cluster_pb2, cluster_pb2_grpc
    from test.unit.test_result_batch_diagnostics import ObserveSyncErrors

    class SyntheticSuspendedService(bindings.QueryEngineServiceServicer,
                                    cluster_pb2_grpc.ClusterServiceServicer):
        def __init__(self):
            self.prepare_budgets = []
            self.status_budgets = []

        def prepareStatement(self, request, context):
            self.prepare_budgets.append(context.time_remaining())
            if len(self.prepare_budgets) == 1:
                context.abort(grpc.StatusCode.UNAVAILABLE, 'status: 503, cluster is suspended')
            context.abort(grpc.StatusCode.PERMISSION_DENIED, 'Synthetic resumed prepare rejection.')

        def status(self, request, context):
            self.status_budgets.append(context.time_remaining())
            threading.Event().wait(delay)
            return cluster_pb2.ClusterStatusResponse(status='active')

    service = SyntheticSuspendedService()
    with ThreadPoolExecutor(max_workers=2) as executor:
        server = grpc.server(executor)
        bindings.add_QueryEngineServiceServicer_to_server(service, server)
        cluster_pb2_grpc.add_ClusterServiceServicer_to_server(service, server)
        port = server.add_insecure_port('127.0.0.1:0')
        server.start()
        conn = Connection(host='127.0.0.1', port=port, access_token='synthetic-local-input',
                          auto_resume=True, require_fastbinary=False, enable_result_batch_v2=v2,
                          grpc_options={'grpc_prepare_timeout': 2})
        conn.grpc_auto_resume_timeout_seconds = .5
        observer = ObserveSyncErrors()
        conn._client = bindings.QueryEngineServiceStub(grpc.intercept_channel(conn._channel, observer))
        cursor = conn.cursor()
        deadline = time.monotonic() + budget if budget is not None else None
        try:
            with pytest.raises(grpc.RpcError) as caught:
                cursor._prepare_with_auto_resume('prepareStatement', pb.PrepareStatementRequest(), deadline)
            assert len(service.prepare_budgets) == expected_prepares, caught.value
            if budget is not None:
                assert service.status_budgets and service.status_budgets[0] <= budget + .02, caught.value
            if expected_prepares == 2:
                assert caught.value is observer.errors[-1]
                assert caught.value.code() == grpc.StatusCode.PERMISSION_DENIED
                assert caught.value.details() == 'Synthetic resumed prepare rejection.'
                if budget is not None:
                    assert service.prepare_budgets[1] <= budget + .02
            else:
                assert caught.value.code() == grpc.StatusCode.DEADLINE_EXCEEDED
        finally:
            conn.close()
            server.stop(0).wait(timeout=2)


def test_prefetch_dispatch_rpc_error_is_original_and_never_replayed(local_results, monkeypatch):
    _, _, rejected_cursor = local_results([grpc.StatusCode.UNAVAILABLE])
    with pytest.raises(grpc.RpcError) as rejected:
        rejected_cursor.fetch_batch()
    service, conn, cursor = local_results([envelope([[1], [2]]), envelope([[3]], terminal=True)])
    original_method = conn.client.getNextResultBatchV2
    calls = {'foreground': 0, 'dispatch': 0}

    class RaisingDispatch:
        """Minimal transport test double for the exceptional future() boundary."""
        def __call__(self, *args, **kwargs):
            calls['foreground'] += 1
            return original_method(*args, **kwargs)

        def future(self, *args, **kwargs):
            calls['dispatch'] += 1
            raise rejected.value

    monkeypatch.setattr(conn.client, 'getNextResultBatchV2', RaisingDispatch())
    assert cursor.fetch_batch() == [[1]]
    assert cursor.fetch_batch() == [[2]]
    with pytest.raises(grpc.RpcError) as caught:
        cursor.fetch_batch()
    assert caught.value is rejected.value
    with pytest.raises(IncompleteResultError):
        cursor.fetch_batch()
    assert calls == {'foreground': 1, 'dispatch': 1}
    assert len(service.requests) == 1


@pytest.mark.parametrize('failure_point', ['registration', 'callback'])
def test_stream_registration_failure_retains_actual_transport_until_settled(
        local_results, monkeypatch, failure_point):
    from concurrent.futures import Future
    from e6data_python_connector.result_prefetch import ContinuousResultStream

    service, conn, cursor = local_results([envelope([[1]])])
    original_method = conn.client.getNextResultBatchV2
    creation_error = RuntimeError('Synthetic stream registration failure.')

    class RejectFirstCallback(Future):
        """Test double for failure registering the transport completion callback."""
        def __init__(self):
            super().__init__()
            self.attachments = 0

        def add_done_callback(self, callback):
            self.attachments += 1
            if self.attachments == 1:
                raise creation_error
            return super().add_done_callback(callback)

    transport = RejectFirstCallback() if failure_point == 'callback' else Future()
    transport.set_running_or_notify_cancel()

    class RunningDispatch:
        """Keep an actual Future running after cancellation to test late ownership."""
        def __call__(self, *args, **kwargs):
            return original_method(*args, **kwargs)

        def future(self, *args, **kwargs):
            return transport

    original_set_transport = ContinuousResultStream.set_transport

    def fail_registration(stream, handle):
        original_set_transport(stream, handle)
        if failure_point == 'registration':
            raise creation_error

    monkeypatch.setattr(conn.client, 'getNextResultBatchV2', RunningDispatch())
    monkeypatch.setattr(ContinuousResultStream, 'set_transport', fail_registration)
    try:
        assert cursor.fetch_batch() == [[1]]
        record = cursor._pending_fetch
        record.handle.result(timeout=1)
        with pytest.raises(IncompleteResultError) as caught:
            cursor.fetch_batch()
        assert caught.value.__cause__ is creation_error
        assert not record.settled
        assert cursor._pending_fetch is None
        assert record in cursor._retired_fetches
        transport.set_result(envelope([], terminal=True, session='late-after-registration-failure'))
        assert record.settled
        cursor.clear(timeout=1)
        assert service.cleanups[-1].sessionId == 'late-after-registration-failure'
    finally:
        if not transport.done():
            transport.set_result(envelope([], terminal=True))


def test_download_metadata_failure_is_delivered_after_current_rows(local_results, monkeypatch):
    service, conn, cursor = local_results([envelope([[1]]), envelope([[2]], terminal=True)])
    original_metadata = conn._call_metadata
    calls = 0

    def preparation_failure(**options):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError('Synthetic metadata preparation failure before dispatch.')
        return original_metadata(**options)

    monkeypatch.setattr(conn, '_call_metadata', preparation_failure)
    assert cursor.fetch_batch() == [[1]]
    with pytest.raises(IncompleteResultError) as caught:
        cursor.fetch_batch()
    assert isinstance(caught.value.__cause__, ValueError)
    assert len(service.requests) == 1


def test_two_cursors_start_exactly_one_connection_decoder_lease(local_results, monkeypatch):
    from e6data_python_connector.result_decode import DecoderLease
    _, conn, _ = local_results([])
    conn._session_id = 'synthetic-session'
    first_cursor, second_cursor = conn.cursor(), conn.cursor()
    original_init = DecoderLease.__init__
    first_creation = threading.Event()
    second_creation = threading.Event()
    release_first = threading.Event()
    leases = []
    created_lock = threading.Lock()

    def observed_init(lease):
        original_init(lease)
        with created_lock:
            leases.append(lease)
            ordinal = len(leases)
        if ordinal == 1:
            first_creation.set()
            assert release_first.wait(2)
        else:
            second_creation.set()

    def execute(cursor):
        with pytest.raises(grpc.RpcError) as caught:
            cursor.execute('synthetic statement rejected by the local service')
        assert caught.value.code() == grpc.StatusCode.UNIMPLEMENTED

    monkeypatch.setattr(DecoderLease, '__init__', observed_init)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(execute, first_cursor)
            assert first_creation.wait(1)
            second = executor.submit(execute, second_cursor)
            second_creation.wait(.1)
            release_first.set()
            first.result(timeout=5)
            second.result(timeout=5)
        assert len(leases) == 1
        worker_pids = conn._decoder_lease.worker_pids
        assert len(worker_pids) == 2
        conn.close()
        for pid in worker_pids:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        release_first.set()
        for lease in leases:
            lease.close(time.monotonic() + 5)


def test_connection_close_during_decoder_startup_prevents_prepare(local_results, monkeypatch):
    from e6data_python_connector.result_decode import DecoderLease
    service, conn, _ = local_results([])
    conn._session_id = 'synthetic-session'
    cursor = conn.cursor()
    original_start, original_close = DecoderLease.start, DecoderLease.close
    started, resume_start = threading.Event(), threading.Event()
    closing, resume_close = threading.Event(), threading.Event()

    def held_start(lease, deadline):
        original_start(lease, deadline)
        started.set()
        assert resume_start.wait(2)

    def held_close(lease, deadline):
        closing.set()
        assert resume_close.wait(2)
        return original_close(lease, deadline)

    monkeypatch.setattr(DecoderLease, 'start', held_start)
    monkeypatch.setattr(DecoderLease, 'close', held_close)
    with ThreadPoolExecutor(max_workers=2) as executor:
        execute = executor.submit(cursor.execute, 'synthetic statement must not be submitted')
        assert started.wait(2)
        worker_pids = conn._decoder_lease.worker_pids
        close = executor.submit(conn.close)
        assert closing.wait(1)
        try:
            resume_start.set()
            with pytest.raises(ProgrammingError, match='closed'):
                execute.result(timeout=2)
            assert service.prepare_requests == []
        finally:
            resume_start.set()
            resume_close.set()
            close.result(timeout=5)
    for pid in worker_pids:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_each_download_uses_fresh_rpc_budget(local_results):
    responses = [envelope([[i]], terminal=i == 6) for i in range(7)]
    service, conn, cursor = local_results(responses)
    service.response_delay = .03
    conn.grpc_prepare_timeout = .12
    assert cursor.fetch_batch() == [[0]]
    record = cursor._pending_fetch
    record.handle.result(timeout=2)
    assert record.queued_count == 6
    assert min(service.request_budgets) > .08
    assert cursor.fetchall() == [[i] for i in range(1, 7)]
    assert len(service.requests) == 7


def test_empty_downloads_stop_after_no_progress_deadline(local_results):
    service, conn, cursor = local_results([envelope([[0]])] + [envelope([])] * 30)
    conn.grpc_prepare_timeout = .08
    assert cursor.fetch_batch() == [[0]]
    record = cursor._pending_fetch
    record.handle.result(timeout=1)
    assert 2 <= len(service.requests) < 10
    with pytest.raises(IncompleteResultError):
        cursor.fetchall()
    assert len(service.requests) < 10


def test_more_than_four_cursors_download_while_decoders_wait(local_results, monkeypatch):
    resources = [local_results([envelope([[i]]), envelope([[i + 10]], terminal=True)])
                 for i in range(6)]
    original_decode = engine.decode_result_batches
    release_decoders = threading.Event()

    def paused_decode(columns, payloads):
        assert release_decoders.wait(3)
        return original_decode(columns, payloads)

    monkeypatch.setattr(engine, 'decode_result_batches', paused_decode)
    with ThreadPoolExecutor(max_workers=6) as executor:
        reads = [executor.submit(cursor.fetch_batch) for _, _, cursor in resources]
        try:
            assert all(service.entered[1].wait(2) for service, _, _ in resources)
        finally:
            release_decoders.set()
        assert [read.result(timeout=2) for read in reads] == [[[i]] for i in range(6)]
    assert [cursor.fetch_batch() for _, _, cursor in resources] == [[[i + 10]] for i in range(6)]


def test_unimplemented_fallback_drains_all_queued_v2_rows_first(local_results, monkeypatch):
    responses = [envelope([[i]], session='session-%s' % i) for i in range(6)]
    service, conn, cursor = local_results(responses + [grpc.StatusCode.UNIMPLEMENTED])
    calls = []

    def v1(request, **options):
        calls.append(request)
        return pb.GetNextResultBatchResponse(resultBatch=chunk([6]))

    monkeypatch.setattr(conn.client, 'getNextResultBatch', v1)
    assert cursor.fetch_batch() == [[0]]
    record = cursor._pending_fetch
    record.handle.result(timeout=2)
    assert [cursor.fetch_batch() for _ in range(5)] == [[[i]] for i in range(1, 6)]
    assert calls == []
    assert cursor.fetch_batch() == [[6]]
    assert len(calls) == 1
    assert calls[0].sessionId == 'session-5'
    assert cursor._result_protocol == 'v1'
    assert len(service.requests) == 7


@pytest.mark.parametrize('cleanup', ['clear', 'pool_return'])
def test_v1_fallback_cleanup_preserves_newer_rotated_session(local_results, cleanup):
    service, conn, cursor = local_results([
        envelope([[1]], session='v2-session'), grpc.StatusCode.UNIMPLEMENTED])
    service.v1_responses = [
        pb.GetNextResultBatchResponse(resultBatch=chunk([2]), sessionId='v1-row-session'),
        pb.GetNextResultBatchResponse(sessionId='v1-eof-session')]
    assert cursor.fetchall() == [[1], [2]]
    assert [request.sessionId for request in service.v1_requests] == [
        'v2-session', 'v1-row-session']
    assert cursor._result_session_id == 'v1-eof-session'
    if cleanup == 'clear':
        cursor.clear(timeout=1)
    else:
        from e6data_python_connector.connection_pool import ConnectionPool, PooledConnection
        pool = ConnectionPool(host='127.0.0.1', port=1, username='synthetic-user',
                              password='synthetic-input', min_size=0, max_size=1, pre_ping=False,
                              require_fastbinary=False, auto_resume=False,
                              enable_result_batch_v2=True)
        pooled = PooledConnection(conn, pool)
        pooled._cursor = cursor
        pooled.in_use = True
        pool._all_connections.append(pooled)
        pool._created_connections = 1
        pool._active_connections = 1
        pool.return_connection(pooled)
    assert service.cleanups[-1].sessionId == 'v1-eof-session'
    assert cursor._retired_fetches == []


def test_cancel_while_fallback_waits_for_producer_preserves_ownership(local_results, monkeypatch):
    from e6data_python_connector.result_prefetch import ContinuousResultStream

    service, _, cursor = local_results([
        envelope([[1]], session='v2-session'), grpc.StatusCode.UNIMPLEMENTED])
    service.v1_responses = [pb.GetNextResultBatchResponse(sessionId='v1-session')]
    producer_finishing = threading.Event()
    release_producer = threading.Event()
    fallback_waiting = threading.Event()
    cancellation_started = threading.Event()
    original_finish = ContinuousResultStream.finish
    original_settle = cursor._settle_download_before_fallback
    original_retire = cursor._retire_result_work

    def paused_finish(stream):
        producer_finishing.set()
        assert release_producer.wait(3)
        return original_finish(stream)

    def observed_settle(*args):
        fallback_waiting.set()
        return original_settle(*args)

    def observed_retire(**options):
        result = original_retire(**options)
        if not options.get('wait'):
            cancellation_started.set()
        return result

    monkeypatch.setattr(ContinuousResultStream, 'finish', paused_finish)
    monkeypatch.setattr(cursor, '_settle_download_before_fallback', observed_settle)
    monkeypatch.setattr(cursor, '_retire_result_work', observed_retire)
    try:
        assert cursor.fetch_batch() == [[1]]
        assert producer_finishing.wait(1)
        with ThreadPoolExecutor(max_workers=2) as executor:
            fetch = executor.submit(cursor.fetch_batch)
            try:
                assert fallback_waiting.wait(1)
                cancel = executor.submit(cursor.cancel, cursor.query_id)
                assert cancellation_started.wait(1)
            finally:
                release_producer.set()
            with pytest.raises(IncompleteResultError):
                fetch.result(timeout=2)
            cancel.result(timeout=2)
        assert service.v1_requests == []
        assert cursor._result_protocol == 'v2'
        assert service.cleanups[-1].sessionId == 'v2-session'
        assert cursor._retired_fetches == []
    finally:
        release_producer.set()
