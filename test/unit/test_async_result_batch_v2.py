"""V2 async contracts with native local state and real wire serialization.

Query handles assigned here are unissued and test local ownership only.
"""
import asyncio
import inspect
import logging
import socket
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import grpc
import pytest
from sqlalchemy.engine import make_url
from thrift.protocol.TBinaryProtocol import TBinaryProtocol
from thrift.transport.TTransport import TMemoryBuffer

from e6data_python_connector.async_connection import AsyncConnection, QueryRoute
from e6data_python_connector.async_cursor import AsyncCursor
from e6data_python_connector.async_work import reserve_work
from e6data_python_connector.datainputstream import FieldInfo
from e6data_python_connector.e6x_vector import ttypes as wire
from e6data_python_connector.exceptions import IncompleteResultError, ProgrammingError
from e6data_python_connector.server import e6x_engine_pb2 as pb, e6x_engine_pb2_grpc as bindings


def connection(**kwargs):
    settings = dict(host='localhost', port=1, access_token='unit-input', secure=True)
    settings.update(kwargs)
    return AsyncConnection(**settings)


def chunk(values):
    output = TMemoryBuffer()
    vectors = [wire.Vector(len(values), wire.VectorType.LONG, [False] * len(values),
                           wire.Data(int64Data=wire.Int64Data(values)), False)]
    wire.Chunk(size=len(values), vectors=vectors).write(TBinaryProtocol(output))
    return output.getvalue()


def active_cursor(conn):
    cursor = AsyncCursor(conn)
    cursor._state = 'ACTIVE'
    cursor._columns = [FieldInfo('value', 'LONG', '', '')]
    return cursor


async def ingest(cursor, values, terminal=True, session=''):
    response = pb.GetNextResultBatchV2Response(
        resultBatches=[chunk(v) for v in values], endOfStream=terminal, sessionId=session)
    reservation = await reserve_work(deadline=cursor._connection._deadline())
    try:
        await cursor._decode_v2_response(response, reservation, cursor._revision)
    finally:
        reservation.release()


def test_option_defaults_keyword_only_and_read_only():
    assert connection().enable_result_batch_v2 is False
    assert connection(enable_result_batch_v2=True).enable_result_batch_v2 is True
    assert inspect.signature(AsyncConnection).parameters['enable_result_batch_v2'].kind == inspect.Parameter.KEYWORD_ONLY
    with pytest.raises(AttributeError):
        connection().enable_result_batch_v2 = True
    assert connection(enable_result_batch_v2=True).max_receive_message_bytes == 64 * 1024 * 1024
    assert connection(enable_result_batch_v2=True, max_receive_message_bytes=1024).max_receive_message_bytes == 1024


@pytest.mark.parametrize('value', [None, 'true', 1, 0, [], {}])
def test_option_rejects_non_boolean(value):
    with pytest.raises(ValueError, match='enable_result_batch_v2'):
        connection(enable_result_batch_v2=value)


@pytest.mark.parametrize('value, expected', [('true', True), ('false', False)])
def test_sqlalchemy_url_option_does_not_become_grpc_option(value, expected):
    from e6data_python_connector.async_dialect import E6dataAsyncDialect
    _, options = E6dataAsyncDialect().create_connect_args(make_url(
        'e6data+asyncio://localhost:1?enable_result_batch_v2=' + value))
    assert options['enable_result_batch_v2'] is expected
    assert 'grpc_options' not in options


def test_terminal_envelope_mixed_fetches_deliver_each_row_once():
    async def run():
        async with connection(enable_result_batch_v2=True) as conn:
            cursor = active_cursor(conn)
            await ingest(cursor, [[1, 2, 3], [4, 5, 6], [7, 8, 9]])
            assert cursor._state == 'ACTIVE'
            assert await cursor.fetchone() == [[1]]
            assert await cursor.fetchmany(3) == [[2], [3], [4]]
            assert await cursor.fetch_batch() == [[5], [6]]
            assert await cursor.fetchall() == [[7], [8], [9]]
            assert await cursor.fetch_batch() is None
            assert cursor.rownumber == 9
            assert cursor._state == 'EXHAUSTED'
    asyncio.run(run())


def test_buffered_iterator_preserves_independent_chunk_shapes():
    async def run():
        async with connection(enable_result_batch_v2=True) as conn:
            cursor = active_cursor(conn)
            await ingest(cursor, [[1], [2, 3], [], [4]])
            assert [rows async for rows in cursor.fetchall_buffer()] == [[[1]], [[2], [3]], [[4]]]
            assert cursor.rownumber == 4
    asyncio.run(run())


def test_empty_nonterminal_and_terminal_envelopes_have_distinct_state():
    async def run():
        async with connection(enable_result_batch_v2=True) as conn:
            cursor = active_cursor(conn)
            await ingest(cursor, [[], []], terminal=False)
            assert cursor._result_batches.needs_fetch
            assert cursor._state == 'ACTIVE'
            await ingest(cursor, [], terminal=True)
            assert await cursor.fetchall() == []
            assert cursor._state == 'EXHAUSTED'
    asyncio.run(run())


def test_corrupt_later_chunk_publishes_nothing_and_retains_failure():
    async def run():
        async with connection(enable_result_batch_v2=True) as conn:
            cursor = active_cursor(conn)
            response = pb.GetNextResultBatchV2Response(resultBatches=[chunk([1]), b''])
            reservation = await reserve_work(deadline=conn._deadline())
            try:
                with pytest.raises(IncompleteResultError, match='decode_failed'):
                    await cursor._decode_v2_response(response, reservation, cursor._revision)
            finally:
                reservation.release()
            assert cursor._result_batches.needs_fetch
            assert cursor._rows == deque()
            with pytest.raises(IncompleteResultError):
                await cursor.fetchone()
    asyncio.run(run())


def test_stale_decode_does_not_publish_rows_or_session():
    async def run():
        async with connection(enable_result_batch_v2=True) as conn:
            cursor = active_cursor(conn)
            cursor._revision += 1
            response = pb.GetNextResultBatchV2Response(resultBatches=[chunk([1])], sessionId='unissued')
            reservation = await reserve_work(deadline=conn._deadline())
            try:
                with pytest.raises(asyncio.CancelledError):
                    await cursor._decode_v2_response(response, reservation, cursor._revision - 1)
            finally:
                reservation.release()
            assert cursor._result_batches.needs_fetch
            assert cursor._result_session_id is None
    asyncio.run(run())


def test_legacy_result_session_is_query_local_and_oauth_ignores_it():
    async def run():
        async with connection(enable_result_batch_v2=True, access_token=None, secure=False,
                              username='unit-user', password='unit-input') as conn:
            conn._session_id = 'original-local-session'
            cursor = active_cursor(conn)
            other = active_cursor(conn)
            await ingest(cursor, [], terminal=False, session='refreshed-local-session')
            await ingest(cursor, [], terminal=False, session='')
            assert cursor._result_session_id == 'refreshed-local-session'
            assert conn._session_id == 'original-local-session'
            assert other._result_session_id is None
        async with connection(enable_result_batch_v2=True) as conn:
            cursor = active_cursor(conn)
            await ingest(cursor, [], terminal=False, session='not-an-oauth-identity')
            assert cursor._result_session_id is None
    asyncio.run(run())


def test_clear_and_failure_discard_undelivered_envelope():
    async def run():
        async with connection(enable_result_batch_v2=True) as conn:
            cursor = active_cursor(conn)
            await ingest(cursor, [[1], [2]])
            cursor._fail_result('cancelled_result')
            assert cursor._result_batches.needs_fetch
            await cursor.clear()
            assert cursor._state == 'EMPTY'
            assert cursor._result_protocol == 'v2'
            assert cursor._result_session_id is None
            cursor._state = 'ACTIVE'
            cursor._columns = [FieldInfo('value', 'LONG', '', '')]
            await ingest(cursor, [[3]])
            await cursor.close()
            assert cursor._result_batches.needs_fetch
    asyncio.run(run())


def test_v2_unimplemented_falls_back_once_then_v1_failure_is_terminal(caplog):
    async def run(port):
        async with connection(host='127.0.0.1', port=port, access_token=None, secure=False,
                              username='unit-user', password='unit-input',
                              enable_result_batch_v2=True, operation_timeout=2, cleanup_timeout=.05) as conn:
            conn._session_id = 'local-unissued-session'
            cursor = active_cursor(conn)
            cursor._route = conn._register_route(QueryRoute(conn.target, 'unissued-query', '', conn.strategy))
            with pytest.raises(IncompleteResultError):
                await cursor.fetch_batch()
            assert cursor._result_protocol == 'v1'
            assert cursor.query_id in conn._routes
            with pytest.raises(IncompleteResultError):
                await cursor.fetchone()
            assert active_cursor(conn)._result_protocol == 'v2'
    with ThreadPoolExecutor(max_workers=2) as executor:
        server = grpc.server(executor)
        bindings.add_QueryEngineServiceServicer_to_server(bindings.QueryEngineServiceServicer(), server)
        port = server.add_insecure_port('127.0.0.1:0')
        server.start()
        try:
            with caplog.at_level(logging.DEBUG, logger='e6data_python_connector.async_cursor'):
                asyncio.run(run(port))
        finally:
            server.stop(0).wait(timeout=5)
    attempts = [r for r in caplog.records if hasattr(r, 'result_batch_protocol')]
    assert [(r.result_batch_protocol, r.result_batch_status) for r in attempts] == [('v2', 'unimplemented'), ('v1', 'error')]
    assert len([r for r in caplog.records if getattr(r, 'result_batch_fallback', False)]) == 1


def test_invalid_boolean_url_option_is_rejected():
    from e6data_python_connector.async_dialect import E6dataAsyncDialect
    with pytest.raises(ValueError, match='Boolean URL options'):
        E6dataAsyncDialect().create_connect_args(make_url(
            'e6data+asyncio://localhost:1?enable_result_batch_v2=1'))


def test_aio_connect_and_pool_forward_option_and_revoke_buffered_lease():
    from e6data_python_connector.aio import connect
    from e6data_python_connector.async_connection_pool import AsyncConnectionPool

    async def run():
        async with await connect(host='localhost', port=1, access_token='unit-input',
                                 secure=True, enable_result_batch_v2=True) as conn:
            assert conn.enable_result_batch_v2
        pool = AsyncConnectionPool(min_size=0, max_size=1, max_overflow=0, pre_ping=False,
                                   host='localhost', port=1, username='unit-user',
                                   password='unit-input', enable_result_batch_v2=True)
        async with pool:
            old = await pool.get_connection()
            cursor = old.cursor()
            cursor._state = 'ACTIVE'
            cursor._columns = [FieldInfo('value', 'LONG', '', '')]
            await ingest(cursor, [[1], [2]])
            await old.close()
            assert cursor._result_batches.needs_fetch
            with pytest.raises(ProgrammingError):
                await cursor.fetch_batch()
            current = await pool.get_connection()
            assert current._connection.enable_result_batch_v2
            new_cursor = current.cursor()
            assert new_cursor._result_batches.needs_fetch
            assert new_cursor._result_session_id is None
            assert new_cursor._result_protocol == 'v2'
            await current.close()
    asyncio.run(run())


@pytest.mark.parametrize('name', ['fetch_batch', 'fetchmany', 'fetchall'])
def test_actual_dispatched_connection_failure_does_not_switch_to_v1(name, caplog):
    async def run(port):
        async with connection(host='127.0.0.1', port=port, enable_result_batch_v2=True,
                              operation_timeout=.05, cleanup_timeout=.02) as conn:
            cursor = active_cursor(conn)
            cursor._route = conn._register_route(QueryRoute(conn.target, 'unissued', '', conn.strategy))
            with pytest.raises(IncompleteResultError) as caught:
                await getattr(cursor, name)()
            assert cursor._result_protocol == 'v2'
            assert cursor._state == 'RESULT_FAILED'
            assert cursor.query_id == caught.value.query_id
            with pytest.raises(IncompleteResultError) as again:
                await cursor.fetchone()
            assert again.value is caught.value
            assert cursor.query_id in conn._routes
    with socket.socket() as reserved_port:
        reserved_port.bind(('127.0.0.1', 0))
        with caplog.at_level(logging.DEBUG, logger='e6data_python_connector.async_cursor'):
            asyncio.run(run(reserved_port.getsockname()[1]))
    attempts = [r for r in caplog.records if hasattr(r, 'result_batch_protocol')]
    assert len(attempts) == 1
    assert attempts[0].result_batch_protocol == 'v2'
    assert attempts[0].result_batch_status == 'error'
    assert attempts[0].result_batch_chunk_count == 0
    assert attempts[0].result_batch_serialized_bytes == 0
    assert attempts[0].result_batch_decode_seconds == 0
    assert attempts[0].result_batch_rpc_seconds >= 0


def test_admission_timeout_has_no_dispatch_or_terminal_consumption():
    from e6data_python_connector.exceptions import OperationalError

    async def run():
        async with connection(enable_result_batch_v2=True, operation_timeout=.02,
                              cleanup_timeout=.02) as conn:
            cursor = active_cursor(conn)
            cursor._route = conn._register_route(QueryRoute(conn.target, 'unissued', '', conn.strategy))
            reservations = [await reserve_work() for _ in range(4)]
            try:
                with pytest.raises(OperationalError) as caught:
                    await cursor.fetch_batch()
                assert not isinstance(caught.value, IncompleteResultError)
                assert cursor._failure is None
                assert cursor._state == 'ACTIVE'
                assert cursor._result_protocol == 'v2'
            finally:
                for item in reservations:
                    item.release()
    asyncio.run(run())


def test_cancelled_real_envelope_decode_never_publishes_late_rows():
    async def run():
        async with connection(enable_result_batch_v2=True) as conn:
            cursor = active_cursor(conn)
            response = pb.GetNextResultBatchV2Response(
                resultBatches=[chunk(list(range(20000)))], endOfStream=True)
            reservation = await reserve_work(deadline=conn._deadline())
            task = asyncio.create_task(cursor._decode_v2_response(response, reservation, cursor._revision))
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert cursor._result_batches.needs_fetch
            assert cursor.rownumber == 0
            while reservation._state == 'submitted':
                await asyncio.sleep(.001)
            await asyncio.sleep(0)
            assert cursor._result_batches.needs_fetch
            assert reservation._state == 'completed'
    asyncio.run(run())


def test_cancel_attempt_discards_buffer_even_when_cleanup_rpc_fails():
    from e6data_python_connector.exceptions import OperationalError

    async def run(port):
        async with connection(host='127.0.0.1', port=port, enable_result_batch_v2=True,
                              operation_timeout=.05, cleanup_timeout=.02) as conn:
            cursor = active_cursor(conn)
            cursor._route = conn._register_route(QueryRoute(conn.target, 'unissued', '', conn.strategy))
            await ingest(cursor, [[1], [2]])
            with pytest.raises(OperationalError):
                await cursor.cancel()
            assert cursor._result_batches.needs_fetch
            with pytest.raises(IncompleteResultError):
                await cursor.fetch_batch()
            assert cursor.query_id in conn._routes
    with socket.socket() as reserved_port:
        reserved_port.bind(('127.0.0.1', 0))
        asyncio.run(run(reserved_port.getsockname()[1]))


@pytest.mark.parametrize('request_type', [
    pb.GetNextResultBatchRequest, pb.GetResultMetadataRequest, pb.StatusRequest,
    pb.CancelQueryRequest, pb.ClearOrCancelQueryRequest, pb.ExplainRequest,
])
def test_refreshed_legacy_session_is_used_for_every_query_request(request_type):
    async def run():
        async with connection(enable_result_batch_v2=True, access_token=None, secure=False,
                              username='unit-user', password='unit-input') as conn:
            conn._session_id = 'original-local-session'
            cursor = active_cursor(conn)
            await ingest(cursor, [], terminal=False, session='refreshed-local-session')
            cursor._route = QueryRoute(conn.target, 'unissued-query', '127.0.0.1', conn.strategy)
            try:
                request = await cursor._query_request(request_type, conn._deadline())
                assert request.sessionId == 'refreshed-local-session'
                assert request.queryId == cursor.query_id
                assert request.engineIP == cursor._route.engine_ip
                assert conn._session_id == 'original-local-session'
            finally:
                cursor._route = None
    asyncio.run(run())


@pytest.mark.parametrize('owned', [False, True])
@pytest.mark.parametrize('opted_in, oauth, retained, expected', [
    (True, False, 'refreshed-local-session', 'refreshed-local-session'),
    (True, False, None, 'original-local-session'),
    (False, False, 'ignored-local-session', 'original-local-session'),
    (True, True, 'ignored-oauth-session', ''),
])
def test_query_cleanup_session_selection_preserves_auth_and_opt_in(owned, opted_in, oauth, retained, expected):
    async def run():
        auth = {} if oauth else dict(access_token=None, secure=False, username='unit-user', password='unit-input')
        async with connection(enable_result_batch_v2=opted_in, **auth) as conn:
            conn._session_id = 'original-local-session'
            cursor = active_cursor(conn)
            cursor._result_session_id = retained
            cursor._route = QueryRoute(conn.target, 'unissued-query', '127.0.0.1', conn.strategy)
            try:
                request = await cursor._query_request(pb.ClearOrCancelQueryRequest, conn._deadline(), owned=owned)
                assert request.sessionId == expected
                assert conn._session_id == 'original-local-session'
            finally:
                cursor._route = None
    asyncio.run(run())


def test_owned_cleanup_can_use_retained_session_without_minting_connection_session():
    async def run():
        async with connection(enable_result_batch_v2=True, access_token=None, secure=False,
                              username='unit-user', password='unit-input') as conn:
            assert conn._session_id is None
            cursor = active_cursor(conn)
            await ingest(cursor, [], terminal=False, session='refreshed-local-session')
            cursor._route = QueryRoute(conn.target, 'unissued-query', '127.0.0.1', conn.strategy)
            try:
                request = await cursor._query_request(pb.ClearOrCancelQueryRequest, conn._deadline(), owned=True)
                assert request.sessionId == 'refreshed-local-session'
                assert conn._session_id is None
            finally:
                cursor._route = None
    asyncio.run(run())


@pytest.mark.parametrize('stale', [False, True])
def test_response_session_retained_for_cleanup_when_envelope_decode_fails(stale):
    async def run():
        async with connection(enable_result_batch_v2=True, access_token=None, secure=False,
                              username='unit-user', password='unit-input') as conn:
            conn._session_id = 'original-local-session'
            cursor = active_cursor(conn)
            cursor._route = QueryRoute(conn.target, 'unissued-query', '127.0.0.1', conn.strategy)
            revision = cursor._revision
            if stale:
                cursor._revision += 1
            response = pb.GetNextResultBatchV2Response(
                resultBatches=[chunk([1]), b''], sessionId='refreshed-local-session')
            reservation = await reserve_work(deadline=conn._deadline())
            try:
                expected_error = asyncio.CancelledError if stale else IncompleteResultError
                with pytest.raises(expected_error):
                    await cursor._decode_v2_response(response, reservation, revision)
                request = await cursor._query_request(pb.ClearOrCancelQueryRequest, conn._deadline(), owned=True)
                assert request.sessionId == ('original-local-session' if stale else 'refreshed-local-session')
                assert cursor._result_batches.needs_fetch
                assert conn._session_id == 'original-local-session'
            finally:
                reservation.release()
                cursor._route = None
    asyncio.run(run())


def test_cancelled_decode_retains_current_response_session_for_cleanup():
    async def run():
        async with connection(enable_result_batch_v2=True, access_token=None, secure=False,
                              username='unit-user', password='unit-input') as conn:
            conn._session_id = 'original-local-session'
            cursor = active_cursor(conn)
            cursor._route = QueryRoute(conn.target, 'unissued-query', '127.0.0.1', conn.strategy)
            response = pb.GetNextResultBatchV2Response(
                resultBatches=[chunk(list(range(20000)))], sessionId='refreshed-local-session')
            reservation = await reserve_work(deadline=conn._deadline())
            task = asyncio.create_task(cursor._decode_v2_response(response, reservation, cursor._revision))
            try:
                await asyncio.sleep(0)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                request = await cursor._query_request(pb.ClearOrCancelQueryRequest, conn._deadline(), owned=True)
                assert request.sessionId == 'refreshed-local-session'
                assert cursor._result_batches.needs_fetch
                while reservation._state == 'submitted':
                    await asyncio.sleep(.001)
                assert cursor._result_batches.needs_fetch
            finally:
                reservation.release()
                cursor._route = None
    asyncio.run(run())
