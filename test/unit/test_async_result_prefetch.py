"""Real loopback transport tests for the single-flag async result pipeline."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import os
import signal
import time
import threading

import grpc
import pytest
from thrift.protocol.TBinaryProtocol import TBinaryProtocol
from thrift.transport.TTransport import TMemoryBuffer

from e6data_python_connector.async_connection import AsyncConnection, QueryRoute
from e6data_python_connector.datainputstream import FieldInfo
from e6data_python_connector.e6x_vector import ttypes as wire
from e6data_python_connector.exceptions import IncompleteResultError, OperationalError
from e6data_python_connector.server import e6x_engine_pb2 as pb
from e6data_python_connector.server import e6x_engine_pb2_grpc as bindings


def chunk(values):
    output = TMemoryBuffer()
    vector = wire.Vector(len(values), wire.VectorType.LONG, [False] * len(values),
                         wire.Data(int64Data=wire.Int64Data(values)), False)
    wire.Chunk(size=len(values), vectors=[vector]).write(TBinaryProtocol(output))
    return output.getvalue()


class SyntheticResults(bindings.QueryEngineServiceServicer):
    """Explicit test server; every payload uses the real Thrift format."""

    def __init__(self, fail_second=False):
        self.calls = []
        self.second = threading.Event()
        self.fail_second = fail_second
        self.clear_session = None
        self.query_calls = {}
        self.fail_clear = False
        self.corrupt_first = False
        self.second_release = threading.Event()
        self.second_release.set()

    def getNextResultBatchV2(self, request, context):
        self.calls.append(request)
        index = self.query_calls.get(request.queryId, 0) + 1
        self.query_calls[request.queryId] = index
        if index == 2:
            self.second.set()
            self.second_release.wait(5)
            if self.fail_second:
                context.abort(grpc.StatusCode.UNAVAILABLE, "synthetic second response failure")
        payloads = [chunk([index * 10]), chunk([index * 10 + 1])]
        if self.corrupt_first and index == 1:
            payloads[1] = b"invalid-synthetic-thrift"
        return pb.GetNextResultBatchV2Response(
            resultBatches=payloads,
            sessionId="local-session-" + str(index), endOfStream=index == 3)

    def clearOrCancelQuery(self, request, context):
        self.clear_session = request.sessionId
        if self.fail_clear:
            context.abort(grpc.StatusCode.UNAVAILABLE, "synthetic cleanup failure")
        return pb.ClearOrCancelQueryResponse()

    def authenticate(self, request, context):
        return pb.AuthenticateResponse(sessionId="local-session-0")

    def clear(self, request, context):
        if self.fail_clear:
            context.abort(grpc.StatusCode.UNAVAILABLE, "synthetic cleanup failure")
        return pb.ClearResponse()


@pytest.fixture
def local_server():
    service = SyntheticResults()
    with ThreadPoolExecutor(max_workers=4) as executor:
        server = grpc.server(executor)
        bindings.add_QueryEngineServiceServicer_to_server(service, server)
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        try:
            yield port, service
        finally:
            service.second_release.set()
            server.stop(0).wait(timeout=5)


async def active(port):
    connection = AsyncConnection(host="127.0.0.1", port=port, username="local-user",
                                 password="local-input", auto_resume=False,
                                 enable_result_batch_v2=True, operation_timeout=10,
                                 cleanup_timeout=2)
    await connection.open()
    connection._session_id = "local-session-0"
    cursor = connection.cursor()
    cursor._state = "ACTIVE"
    cursor._columns = [FieldInfo("value", "LONG", "", "")]
    cursor._route = connection._register_route(QueryRoute(
        connection.target, "unissued-local-query", "127.0.0.1", connection.strategy))
    return connection, cursor


def test_one_prefetch_starts_while_current_chunks_are_still_buffered(local_server):
    async def run():
        connection, cursor = await active(local_server[0])
        try:
            assert await cursor.fetch_batch() == [[10]]
            assert len(connection._decoder_lease.worker_pids) == 2
            assert await asyncio.to_thread(local_server[1].second.wait, 1), "second RPC did not start"
            assert len(local_server[1].calls) == 2
            assert await cursor.fetch_batch() == [[11]]
            assert len(local_server[1].calls) == 2
            assert await cursor.fetchall() == [[20], [21], [30], [31]]
            assert len(local_server[1].calls) == 3
        finally:
            await connection.close()
    asyncio.run(run())


def test_completed_prefetch_survives_its_dispatch_deadline(local_server):
    async def run():
        connection, cursor = await active(local_server[0])
        try:
            await connection._ensure_decoder(connection._deadline())
            assert await cursor.fetch_batch(timeout=0.2) == [[10]]
            pending = cursor._pending_result[0]
            await asyncio.gather(asyncio.shield(pending.handle), return_exceptions=True)
            await asyncio.sleep(max(0, pending.deadline - asyncio.get_running_loop().time()) + 0.02)
            assert await cursor.fetch_batch() == [[11]]
            assert await cursor.fetch_batch() == [[20]]
        finally:
            await connection.close()
    asyncio.run(run())


def test_four_cursors_share_decode_admission_without_waiting_on_a_second_slot(local_server):
    async def run():
        connection, first = await active(local_server[0])
        cursors = [first]
        try:
            for index in range(3):
                cursor = connection.cursor()
                cursor._state = "ACTIVE"
                cursor._columns = first._columns
                cursor._route = connection._register_route(QueryRoute(
                    connection.target, "unissued-local-query-" + str(index), "127.0.0.1", connection.strategy))
                cursors.append(cursor)
            async with asyncio.timeout(10):
                results = await asyncio.gather(*(cursor.fetchall() for cursor in cursors))
            assert results == [[[10], [11], [20], [21], [30], [31]]] * 4
            assert len(local_server[1].calls) == 12
        finally:
            await connection.close()
    asyncio.run(run())


def test_pending_rpc_error_waits_for_current_rows_and_preserves_identity(local_server):
    local_server[1].fail_second = True
    async def run():
        connection, cursor = await active(local_server[0])
        try:
            assert await cursor.fetch_batch() == [[10]]
            assert await asyncio.to_thread(local_server[1].second.wait, 1)
            pending = cursor._pending_result[0]
            await asyncio.gather(asyncio.shield(pending.handle), return_exceptions=True)
            original = pending.handle.exception()
            assert await cursor.fetch_batch() == [[11]]
            with pytest.raises(grpc.aio.AioRpcError) as caught:
                await cursor.fetch_batch()
            assert caught.value is original
            assert caught.value.code() == grpc.StatusCode.UNAVAILABLE
            with pytest.raises(IncompleteResultError):
                await cursor.fetch_batch()
            assert len(local_server[1].calls) == 2
        finally:
            await connection.close()
    asyncio.run(run())


def test_clear_uses_session_from_completed_unconsumed_prefetch(local_server):
    async def run():
        connection, cursor = await active(local_server[0])
        try:
            assert await cursor.fetch_batch() == [[10]]
            assert await asyncio.to_thread(local_server[1].second.wait, 1)
            await asyncio.gather(asyncio.shield(cursor._pending_result[0].handle), return_exceptions=True)
            await cursor.clear()
            assert local_server[1].clear_session == "local-session-2"
            assert cursor._pending_result is None
        finally:
            await connection.close()
    asyncio.run(run())


def test_failed_close_retains_old_query_cleanup_record(local_server):
    local_server[1].fail_clear = True
    async def run():
        connection, cursor = await active(local_server[0])
        try:
            assert await cursor.fetch_batch() == [[10]]
            await asyncio.gather(asyncio.shield(cursor._pending_result[0].handle), return_exceptions=True)
            await cursor.close()
            assert cursor.cleanup_error is not None
            assert cursor._result_session_id == "local-session-2"
            assert cursor in connection._cursors
        finally:
            await connection.close()
    asyncio.run(run())


def test_pool_return_retires_prefetch_before_new_lease(local_server):
    from e6data_python_connector.async_connection_pool import AsyncConnectionPool

    async def run():
        async with AsyncConnectionPool(
                min_size=0, max_size=1, max_overflow=0, host="127.0.0.1", port=local_server[0],
                username="local-user", password="local-input", auto_resume=False,
                enable_result_batch_v2=True, cleanup_timeout=2) as pool:
            lease = await pool.get_connection()
            connection = lease._connection
            connection._session_id = "local-session-0"
            cursor = lease.cursor()
            cursor._state = "ACTIVE"
            cursor._columns = [FieldInfo("value", "LONG", "", "")]
            cursor._route = connection._register_route(QueryRoute(
                connection.target, "unissued-local-query", "127.0.0.1", connection.strategy))
            assert await cursor.fetch_batch() == [[10]]
            pending = cursor._pending_result[0]
            await asyncio.gather(asyncio.shield(pending.handle), return_exceptions=True)
            await lease.close()
            assert pending.settled
            assert pending.handle is None
            assert local_server[1].clear_session == "local-session-2"
            current = await pool.get_connection()
            assert current._connection is connection
            assert cursor._pending_result is None
            assert current.cursor()._pending_result is None
            await current.close()
    asyncio.run(run())


def test_exhausted_prefetch_capacity_keeps_foreground_fetch_working(local_server):
    from e6data_python_connector.result_prefetch import reserve_prefetch

    permits = [reserve_prefetch() for _ in range(4)]
    assert all(permit is not None for permit in permits)
    async def run():
        connection, cursor = await active(local_server[0])
        try:
            assert await cursor.fetch_batch() == [[10]]
            assert cursor._pending_result is None
            assert len(local_server[1].calls) == 1
            assert await cursor.fetch_batch() == [[11]]
            assert len(local_server[1].calls) == 1
            assert await cursor.fetchall() == [[20], [21], [30], [31]]
        finally:
            await connection.close()
    try:
        asyncio.run(run())
    finally:
        for permit in permits:
            permit.release()


def test_parallel_decode_failure_publishes_no_partial_rows_or_replay(local_server):
    local_server[1].corrupt_first = True
    async def run():
        connection, cursor = await active(local_server[0])
        try:
            with pytest.raises(IncompleteResultError):
                await cursor.fetch_batch()
            assert not cursor._rows
            assert cursor._result_batches.pop() is None
            assert cursor._pending_result is None
            with pytest.raises(IncompleteResultError):
                await cursor.fetch_batch()
            assert len(local_server[1].calls) <= 2
        finally:
            await connection.close()
    asyncio.run(run())


def test_inflight_prefetch_keeps_original_deadline_error_after_current_rows(local_server):
    local_server[1].second_release.clear()
    async def run():
        connection, cursor = await active(local_server[0])
        try:
            await connection._ensure_decoder(connection._deadline())
            assert await cursor.fetch_batch(timeout=0.2) == [[10]]
            pending = cursor._pending_result[0]
            await asyncio.gather(asyncio.shield(pending.handle), return_exceptions=True)
            original = pending.handle.exception()
            assert isinstance(original, grpc.aio.AioRpcError)
            assert original.code() == grpc.StatusCode.DEADLINE_EXCEEDED
            assert await cursor.fetch_batch() == [[11]]
            with pytest.raises(grpc.aio.AioRpcError) as caught:
                await cursor.fetch_batch()
            assert caught.value is original
            assert len(local_server[1].calls) == 2
        finally:
            local_server[1].second_release.set()
            await connection.close()
    asyncio.run(run())


@pytest.mark.parametrize("failure", [False, True])
def test_prefetch_logs_keep_transport_duration_and_wait_separate(local_server, caplog, failure):
    local_server[1].fail_second = failure
    elapsed = []
    async def run():
        connection, cursor = await active(local_server[0])
        try:
            assert await cursor.fetch_batch() == [[10]]
            pending = cursor._pending_result[0]
            await asyncio.gather(asyncio.shield(pending.handle), return_exceptions=True)
            elapsed.append(pending.elapsed)
            assert await cursor.fetch_batch() == [[11]]
            if failure:
                original = pending.handle.exception()
                with pytest.raises(grpc.aio.AioRpcError) as caught:
                    await cursor.fetch_batch()
                assert caught.value is original
            else:
                assert await cursor.fetch_batch() == [[20]]
        finally:
            await connection.close()
    with caplog.at_level(logging.DEBUG, logger="e6data_python_connector.async_cursor"):
        asyncio.run(run())
    records = [record for record in caplog.records
               if hasattr(record, "result_batch_prefetched_rpc_seconds")]
    assert len(records) == 1
    assert records[0].result_batch_prefetched_rpc_seconds == elapsed[0]
    assert records[0].result_batch_prefetch_wait_seconds >= 0
    assert records[0].result_batch_prefetch_status == ("error" if failure else "ok")
    fetches = [record for record in caplog.records if hasattr(record, "result_batch_rpc_seconds")]
    assert fetches[-1].result_batch_rpc_seconds == elapsed[0]
    assert any(getattr(record, "result_batch_prefetch_admitted", None) == 1 for record in caplog.records)
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "unissued-local-query" not in messages
    assert "local-session-" not in messages
    assert "synthetic second response failure" not in messages


def test_prefetch_capacity_log_does_not_include_query_values(local_server, caplog):
    from e6data_python_connector.result_prefetch import reserve_prefetch

    permits = [reserve_prefetch() for _ in range(4)]
    async def run():
        connection, cursor = await active(local_server[0])
        try:
            assert await cursor.fetch_batch() == [[10]]
        finally:
            await connection.close()
    try:
        with caplog.at_level(logging.DEBUG, logger="e6data_python_connector.async_cursor"):
            asyncio.run(run())
    finally:
        for permit in permits:
            permit.release()
    records = [record for record in caplog.records
               if getattr(record, "result_batch_prefetch_status", None) == "capacity_unavailable"]
    assert len(records) == 1
    assert records[0].result_batch_prefetch_admitted == 0


def test_prefetch_preparation_failure_is_logged_without_changing_the_error(local_server, caplog):
    async def run():
        connection, cursor = await active(local_server[0])
        try:
            response = pb.GetNextResultBatchV2Response(resultBatches=[chunk([10])])
            with pytest.raises(TimeoutError):
                await cursor._start_prefetch(response, asyncio.get_running_loop().time() - 1)
            assert cursor._pending_result is None
            assert not local_server[1].calls
        finally:
            await connection.close()
    with caplog.at_level(logging.DEBUG, logger="e6data_python_connector.async_cursor"):
        asyncio.run(run())
    records = [record for record in caplog.records
               if getattr(record, "result_batch_prefetch_status", None) == "preparation_failed"]
    assert len(records) == 1
    assert records[0].result_batch_prefetch_admitted == 0
    assert records[0].exc_info is None
    assert "unissued-local-query" not in records[0].getMessage()


def test_cancellation_during_prefetch_metadata_preparation_stops_current_operation(local_server):
    from e6data_python_connector.result_prefetch import reserve_prefetch

    async def run():
        connection, cursor = await active(local_server[0])
        preparing, release = asyncio.Event(), asyncio.Event()
        original_metadata = connection._metadata
        preparations = 0

        async def gated_metadata(deadline, route=None, _cleanup=False):
            # Test-only scheduling gate; real metadata and both real transports
            # remain in use. The second preparation belongs to prefetch N+1.
            nonlocal preparations
            preparations += 1
            if preparations == 2:
                preparing.set()
                await release.wait()
            return await original_metadata(deadline, route, _cleanup=_cleanup)

        connection._metadata = gated_metadata
        task = asyncio.create_task(cursor.fetch_batch())
        try:
            async with asyncio.timeout(5):
                await preparing.wait()
            assert len(local_server[1].calls) == 1
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert cursor._state == "RESULT_FAILED"
            assert cursor._pending_result is None
            assert cursor._result_batches.pop() is None
            assert not cursor._rows
            assert len(local_server[1].calls) == 1
            permits = [reserve_prefetch() for _ in range(4)]
            try:
                assert all(permit is not None for permit in permits)
            finally:
                for permit in permits:
                    if permit is not None:
                        permit.release()
        finally:
            release.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            connection._metadata = original_metadata
            await connection.close()
    asyncio.run(run())


def test_cancel_stops_the_same_active_decode_owner(local_server):
    async def run():
        connection, cursor = await active(local_server[0])
        task = None
        pids = ()
        try:
            await connection._ensure_decoder(connection._deadline())
            lease = connection._decoder_lease
            pids = lease.worker_pids
            for pid in pids:
                os.kill(pid, signal.SIGSTOP)
            task = asyncio.create_task(cursor.fetch_batch())
            async with asyncio.timeout(5):
                while lease._runtime._active is None:
                    await asyncio.sleep(0.005)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert cursor._state == "RESULT_FAILED"
            assert lease._runtime.state in ("failed", "closed"), "cancel did not find the active owner"
            assert await asyncio.to_thread(lease._runtime.stopped.wait, 2)
            assert not cursor._rows
        finally:
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGCONT)
                except ProcessLookupError:
                    pass
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await connection.close()
    asyncio.run(run())


@pytest.mark.parametrize("method", ["fetch_batch", "fetchmany"])
@pytest.mark.parametrize("stop", ["timeout", "cancel"])
def test_pending_rpc_is_retired_if_decode_admission_is_interrupted(local_server, method, stop):
    from e6data_python_connector.async_work import reserve_work

    local_server[1].second_release.clear()
    async def run():
        connection, cursor = await active(local_server[0])
        reservations = []
        task = None
        try:
            assert await cursor.fetch_batch() == [[10]]
            assert await cursor.fetch_batch() == [[11]]
            pending = cursor._pending_result[0]
            handle = pending.handle
            assert await asyncio.to_thread(local_server[1].second.wait, 1)
            for _ in range(4):
                reservations.append(await reserve_work(deadline=connection._deadline()))
            if stop == "timeout":
                with pytest.raises(OperationalError):
                    await getattr(cursor, method)(timeout=0.03)
            else:
                task = asyncio.create_task(getattr(cursor, method)())
                while cursor._operation_task is not task:
                    await asyncio.sleep(0)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert cursor._state == "RESULT_FAILED"
            assert cursor._failure is not None
            assert cursor._pending_result is None
            await asyncio.gather(asyncio.shield(handle), return_exceptions=True)
            assert pending.settled
            assert handle.cancelled()
            assert pending.handle is None
            assert len(local_server[1].calls) == 2
            with pytest.raises(IncompleteResultError):
                await cursor.fetch_batch()
        finally:
            for reservation in reservations:
                reservation.release()
            local_server[1].second_release.set()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await connection.close()
    asyncio.run(run())


def test_cancel_before_local_decode_starts_prevents_delayed_admission(local_server):
    async def run():
        connection, cursor = await active(local_server[0])
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        task = None
        errors = []
        try:
            await connection._ensure_decoder(connection._deadline())
            lease = connection._decoder_lease
            original_decode = lease.decode
            sequence = lease._runtime._sequence

            def gated_decode(*args):
                # Test-only scheduling gate before calling the real runtime.
                entered.set()
                release.wait(5)
                try:
                    return original_decode(*args)
                except BaseException as error:
                    errors.append(error)
                    raise
                finally:
                    finished.set()

            lease.decode = gated_decode
            task = asyncio.create_task(cursor.fetch_batch())
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            release.set()
            assert await asyncio.to_thread(finished.wait, 2)
            assert errors, "cancelled local work was admitted after its caller stopped"
            assert "cancelled" in str(errors[0])
            assert lease._runtime._sequence == sequence
            assert lease._runtime.state == "ready"
            assert cursor._state == "RESULT_FAILED"
            assert not cursor._rows
        finally:
            release.set()
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await connection.close()
    asyncio.run(run())


def test_connection_close_retires_workers_when_local_work_slots_and_loop_end(local_server):
    from e6data_python_connector.async_work import reserve_work

    reservations = []
    saved = {}
    async def run():
        connection = AsyncConnection(
            host="127.0.0.1", port=local_server[0], username="local-user", password="local-input",
            auto_resume=False, enable_result_batch_v2=True, cleanup_timeout=0.03)
        await connection.open()
        await connection._ensure_decoder(connection._deadline())
        saved['lease'] = connection._decoder_lease
        for _ in range(4):
            reservations.append(await reserve_work(deadline=connection._deadline()))
        await connection.close()
        assert connection._state == 'closed'
    try:
        asyncio.run(run())
        lease = saved['lease']
        assert lease._closed, "loop shutdown canceled the queued decoder retirement"
        assert lease._runtime.stopped.wait(2)
        assert not any(_process_alive(pid) for pid in lease.worker_pids)
    finally:
        for reservation in reservations:
            reservation.release()
        if 'lease' in saved:
            saved['lease'].close(time.monotonic() + 2)


def _process_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
