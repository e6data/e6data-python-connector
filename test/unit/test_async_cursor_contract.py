"""Async cursor local-state contracts using native connections, no server doubles."""
import asyncio
import importlib.util
import inspect

import pytest


def cursor_type():
    assert importlib.util.find_spec('e6data_python_connector.async_cursor') is not None
    from e6data_python_connector.async_cursor import AsyncCursor
    return AsyncCursor


def test_every_implemented_network_cursor_function_is_awaited():
    cls = cursor_type()
    for name in ('execute', 'executemany', 'fetchone', 'fetchmany', 'fetchall', 'fetch_batch',
                 'update_mete_data', 'refresh_metadata', 'get_rowcount', 'get_description',
                 'get_rpc_metadata', 'status', 'cancel', 'clear', 'close', 'get_tables',
                 'get_columns', 'get_schema_names', 'explain', 'explain_analyse'):
        assert inspect.iscoroutinefunction(getattr(cls, name)), name
    assert inspect.isasyncgenfunction(cls.fetchall_buffer)
    for name in ('setinputsizes', 'setoutputsize'):
        assert not inspect.iscoroutinefunction(getattr(cls, name))


def test_cached_properties_are_local_and_initialized():
    cls = cursor_type()
    from e6data_python_connector.async_connection import AsyncConnection
    conn = AsyncConnection(host='localhost', port=1, access_token='unit-input', secure=True)
    cursor = cls(conn)
    assert cursor.arraysize == 1000
    assert cursor.rownumber == 0
    assert cursor.lastrowid is None
    assert cursor.rowcount == -1
    assert cursor.description is None
    assert cursor.query_id is None
    with pytest.raises(ValueError):
        cursor.arraysize = -1


def test_mixed_fetches_preserve_buffered_rows_and_eof():
    cls = cursor_type()
    from e6data_python_connector.async_connection import AsyncConnection
    async def run():
        async with AsyncConnection(host='localhost', port=1, access_token='unit-input', secure=True) as conn:
            cursor = cls(conn)
            cursor._state = 'EXHAUSTED'
            cursor._accept_rows([[1], [2], [3]])
            assert await cursor.fetchone() == [[1]]
            assert await cursor.fetchall() == [[2], [3]]
            assert await cursor.fetchone() is None
            assert cursor.rownumber == 3
            await cursor.close()
    asyncio.run(run())


def test_terminal_failure_prevents_all_fetches_even_with_buffered_rows():
    cls = cursor_type()
    from e6data_python_connector.async_connection import AsyncConnection
    from e6data_python_connector.exceptions import IncompleteResultError
    async def run():
        async with AsyncConnection(host='localhost', port=1, access_token='unit-input', secure=True) as conn:
            cursor = cls(conn)
            cursor._accept_rows([[1]])
            error = cursor._fail_result('ambiguous_result')
            for operation in (cursor.fetchone, cursor.fetchmany, cursor.fetch_batch,
                              cursor.fetchall, lambda: anext(cursor.fetchall_buffer())):
                with pytest.raises(IncompleteResultError) as caught:
                    await operation()
                assert caught.value is error
            await cursor.close()
    asyncio.run(run())


def test_closing_unknown_submission_does_not_claim_cleanup():
    cls = cursor_type()
    from e6data_python_connector.async_connection import AsyncConnection
    from e6data_python_connector.exceptions import ProgrammingError
    async def run():
        conn = await AsyncConnection(host='localhost', port=1, access_token='unit-input', secure=True).open()
        cursor = cls(conn)
        cursor._state = 'SUBMISSION_UNKNOWN'
        await cursor.close()
        assert cursor.cleanup_error is not None
        await conn.close()
        with pytest.raises(ProgrammingError):
            await conn.reopen()
    asyncio.run(run())


def test_closed_cursor_still_rejects_another_event_loop():
    from e6data_python_connector.async_connection import AsyncConnection
    from e6data_python_connector.exceptions import ProgrammingError
    async def create():
        conn = await AsyncConnection(host='localhost', port=1, access_token='unit-input', secure=True).open()
        cursor = cursor_type()(conn)
        await cursor.close()
        await conn.close()
        return cursor
    cursor = asyncio.run(create())
    with pytest.raises(ProgrammingError):
        asyncio.run(cursor.close())


def test_metadata_decoder_matches_existing_binary_format_off_loop():
    import struct
    from e6data_python_connector.async_cursor import _metadata_columns
    from e6data_python_connector.async_work import run_blocking
    encoded = struct.pack('>qi', 2, 1)
    for field in ('result', 'LONG', '', ''):
        value = field.encode('utf-8')
        encoded += struct.pack('>H', len(value)) + value
    async def run():
        count, columns = await run_blocking(_metadata_columns, encoded)
        assert count == 2
        assert [(col.get_name(), col.get_field_type()) for col in columns] == [('result', 'LONG')]
        with pytest.raises(struct.error):
            await run_blocking(_metadata_columns, encoded[:7])
    asyncio.run(run())
