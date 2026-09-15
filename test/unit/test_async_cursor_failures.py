"""Actual closed-port RPC failures and local cursor state, without server doubles.

Unissued query handles below exercise local ownership only. No test claims that
these handles correspond to a query accepted by a service.
"""
import asyncio
import socket

import grpc
import pytest

from e6data_python_connector.async_connection import AsyncConnection, QueryRoute
from e6data_python_connector.async_cursor import AsyncCursor
from e6data_python_connector.exceptions import (
    AmbiguousSubmissionError, IncompleteResultError, NotSupportedError,
    OperationalError, ProgrammingError,
)


def connection():
    # Reserve a TCP port without listening for the whole test. No service can
    # unexpectedly bind it, and connection attempts fail through native gRPC.
    reservation = socket.socket()
    reservation.bind(('127.0.0.1', 0))
    conn = AsyncConnection(host='127.0.0.1', port=reservation.getsockname()[1],
                           access_token='local-nonusable-input', secure=True,
                           operation_timeout=.2, cleanup_timeout=.05)
    return reservation, conn


def route_cursor(conn):
    cursor = AsyncCursor(conn)
    cursor._route = conn._register_route(QueryRoute(conn.target, 'unissued-local-handle',
                                                   '127.0.0.1', 'blue'))
    cursor._state = 'ACTIVE'
    return cursor


def test_failed_prepare_is_not_replayed_and_blocks_reuse():
    async def run():
        reservation, conn = connection()
        with reservation:
            async with conn:
                cursor = AsyncCursor(conn)
                with pytest.raises(AmbiguousSubmissionError) as caught:
                    await cursor.execute('SELECT 1')
                assert isinstance(caught.value.__cause__, grpc.RpcError)
                assert cursor._state == 'SUBMISSION_UNKNOWN'
                assert cursor in conn._ambiguous_submissions
                with pytest.raises(ProgrammingError):
                    await cursor.execute('SELECT 1')
                with pytest.raises(AmbiguousSubmissionError):
                    await cursor.clear()
                await cursor.close()
                assert cursor.cleanup_error is not None
            with pytest.raises(ProgrammingError):
                await conn.reopen()
    asyncio.run(run())


def test_cursor_rejects_overlapping_ordinary_operations():
    async def run():
        reservation, conn = connection()
        with reservation:
            async with conn:
                cursor = AsyncCursor(conn)
                first = asyncio.create_task(cursor.execute('SELECT 1'))
                await asyncio.sleep(0)
                assert cursor._busy
                with pytest.raises(ProgrammingError, match='one ordinary'):
                    await cursor.get_schema_names()
                with pytest.raises(AmbiguousSubmissionError):
                    await first
    asyncio.run(run())


@pytest.mark.parametrize('name', ['status', 'explain', 'explain_analyse',
                                  'refresh_metadata', 'get_rowcount', 'get_description'])
def test_read_failure_keeps_registered_handle(name):
    async def run():
        reservation, conn = connection()
        with reservation:
            async with conn:
                cursor = route_cursor(conn)
                with pytest.raises(OperationalError) as caught:
                    await getattr(cursor, name)()
                assert isinstance(caught.value.__cause__, grpc.RpcError)
                assert cursor.query_id in conn._routes
                assert cursor._state == 'ACTIVE'
                with pytest.raises(OperationalError):
                    await cursor.clear()
                assert cursor.query_id in conn._routes
                await cursor.close()
                assert cursor.cleanup_error is not None
                assert cursor.query_id in conn._routes
    asyncio.run(run())


@pytest.mark.parametrize('name,args', [('get_tables', ()), ('get_columns', ('unissued-table',)),
                                      ('get_schema_names', ())])
def test_discovery_failure_is_operational(name, args):
    async def run():
        reservation, conn = connection()
        with reservation:
            async with conn:
                cursor = AsyncCursor(conn)
                with pytest.raises(OperationalError) as caught:
                    await getattr(cursor, name)(*args)
                assert isinstance(caught.value.__cause__, grpc.RpcError)
                assert cursor._state == 'EMPTY'
    asyncio.run(run())


@pytest.mark.parametrize('name', ['fetch_batch', 'fetchmany', 'fetchall'])
def test_dispatched_fetch_failure_is_terminal(name):
    async def run():
        reservation, conn = connection()
        with reservation:
            async with conn:
                cursor = route_cursor(conn)
                cursor._columns = []
                with pytest.raises(IncompleteResultError) as caught:
                    await getattr(cursor, name)()
                assert cursor._state == 'RESULT_FAILED'
                assert cursor.query_id == caught.value.query_id
                with pytest.raises(IncompleteResultError) as again:
                    await cursor.fetchone()
                assert again.value is caught.value
    asyncio.run(run())


def test_control_failure_and_handle_mismatch_never_discard_route():
    async def run():
        reservation, conn = connection()
        with reservation:
            async with conn:
                cursor = route_cursor(conn)
                for operation in (cursor.clear, cursor.cancel, cursor.status):
                    with pytest.raises(ProgrammingError):
                        await operation('different-handle')
                with pytest.raises(ProgrammingError):
                    await anext(cursor.fetchall_buffer('different-handle'))
                with pytest.raises(OperationalError):
                    await cursor.cancel()
                assert cursor.query_id in conn._routes
    asyncio.run(run())


def test_local_misuse_and_unsupported_operations_need_no_rpc():
    async def run():
        reservation, conn = connection()
        with reservation:
            async with conn:
                async with AsyncCursor(conn) as cursor:
                    for operation in (cursor.cancel, cursor.status, cursor.refresh_metadata,
                                      cursor.fetchone, cursor.fetchall):
                        with pytest.raises(ProgrammingError):
                            await operation()
                    for sql in ('', ' ', None):
                        with pytest.raises(ProgrammingError):
                            await cursor.execute(sql)
                    with pytest.raises(ProgrammingError):
                        await cursor.execute('SELECT 1', unsupported=True)
                    for operation in (cursor.poll, cursor.fetch_logs):
                        with pytest.raises(NotSupportedError):
                            await operation()
                    assert cursor.setinputsizes([]) is None
                    assert cursor.setoutputsize(1) is None
                    assert await cursor.clear() is None
                    assert dict(await cursor.get_rpc_metadata())['strategy'] == 'blue'
                with pytest.raises(ProgrammingError):
                    await cursor.fetchall()
    asyncio.run(run())


def test_iterators_and_all_fetch_shapes_share_one_buffer():
    async def run():
        reservation, conn = connection()
        with reservation:
            async with conn:
                cursor = AsyncCursor(conn)
                cursor._state = 'EXHAUSTED'
                cursor._accept_rows([[1], [2], [3], [4]])
                assert await cursor.fetchmany(0) == []
                assert await anext(cursor) == [[1]]
                assert await cursor.fetchmany(1) == [[2]]
                assert [batch async for batch in cursor.fetchall_buffer()] == [[[3], [4]]]
                assert await cursor.fetch_batch() is None
                assert [row async for row in cursor] == []
                assert cursor.rownumber == 4
                for size in (-1, True, 1.5):
                    with pytest.raises(ProgrammingError):
                        await cursor.fetchmany(size)
    asyncio.run(run())


def test_executemany_reports_first_ambiguous_parameter_index():
    async def run():
        reservation, conn = connection()
        with reservation:
            async with conn:
                cursor = AsyncCursor(conn)
                assert await cursor.executemany('SELECT %s', []) is None
                with pytest.raises(AmbiguousSubmissionError) as caught:
                    await cursor.executemany('SELECT %s', [(1,), (2,)])
                assert caught.value.parameter_index == 0
    asyncio.run(run())


def test_connection_close_during_dispatched_prepare_retains_uncertainty():
    async def run():
        reservation, conn = connection()
        with reservation:
            await conn.open()
            cursor = AsyncCursor(conn)
            task = asyncio.create_task(cursor.execute('SELECT 1'))
            while not conn._calls and not task.done():
                await asyncio.sleep(0)
            assert conn._calls, 'Must interrupt an actual dispatched native call'
            await conn.close()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert cursor._state == 'CLOSED'
            assert cursor in conn._ambiguous_submissions
            assert cursor.cleanup_error is not None
            with pytest.raises(ProgrammingError):
                await conn.reopen()
    asyncio.run(run())


def test_cancellation_before_token_dispatch_keeps_empty_query_state():
    from e6data_python_connector.async_work import reserve_work
    async def run():
        slots = [await reserve_work() for _ in range(4)]
        conn = await AsyncConnection('localhost', 1, client_id='unit-id',
            client_secret='unit-input', token_url='https://localhost/token', secure=True).open()
        try:
            cursor = AsyncCursor(conn)
            operation = asyncio.create_task(cursor.execute('SELECT 1'))
            while conn._token_provider._task is None:
                await asyncio.sleep(0)
            operation.cancel()
            with pytest.raises(asyncio.CancelledError):
                await operation
            assert cursor._state == 'EMPTY'
            assert not conn._ambiguous_submissions
            assert not conn._calls
            assert await cursor.clear() is None
        finally:
            await conn.close()
            for slot in slots:
                slot.release()
    asyncio.run(run())


def test_fetch_admission_timeout_does_not_claim_batch_consumption():
    from e6data_python_connector.async_work import reserve_work
    async def run():
        reservation, conn = connection()
        slots = [await reserve_work() for _ in range(4)]
        try:
            with reservation:
                async with conn:
                    cursor = route_cursor(conn)
                    cursor._columns = []
                    with pytest.raises(OperationalError) as caught:
                        await cursor.fetch_batch(timeout=.02)
                    assert isinstance(caught.value.__cause__, TimeoutError)
                    assert cursor._state == 'ACTIVE'
                    assert cursor._failure is None
                    assert not conn._calls
        finally:
            for slot in slots:
                slot.release()
    asyncio.run(run())
