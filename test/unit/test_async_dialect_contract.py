"""Real local adapters and configuration only, without simulated services."""
import asyncio
import inspect
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import registry
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool
from sqlalchemy.util.concurrency import greenlet_spawn


def test_async_registration_is_separate():
    assert registry.load('e6data.asyncio').is_async
    assert not registry.load('e6data').is_async


def test_dependency_floor():
    source = Path('setup.py').read_text()
    assert 'SQLAlchemy[asyncio]>=2.0,<2.1' in source


def test_engine_constructs_without_network():
    engine = create_async_engine('e6data+asyncio://localhost:1/?catalog=test')
    assert engine.dialect.is_async
    assert isinstance(engine.pool, AsyncAdaptedQueuePool)
    asyncio.run(engine.dispose())


@pytest.mark.parametrize('url', [
    'e6data+asyncio://user:password@localhost:1',
    'e6data+asyncio://localhost:1?access_token=value',
    'e6data+asyncio://localhost:1?client_secret=value',
    'e6data+asyncio://localhost:1?unexpected=value',
    'e6data+asyncio://localhost:1?secure=maybe',
])
def test_unsafe_or_unknown_url_options_rejected(url):
    from e6data_python_connector.async_dialect import E6dataAsyncDialect
    with pytest.raises(ValueError):
        E6dataAsyncDialect().create_connect_args(make_url(url))


def test_options_are_separated():
    from e6data_python_connector.async_dialect import E6dataAsyncDialect
    args, options = E6dataAsyncDialect().create_connect_args(make_url(
        'e6data+asyncio://localhost:1?catalog=cat&schema=db&cluster-name=cluster&secure=true&debug=false&auto-resume=false&operation_timeout=12&grpc.keepalive_time_ms=1000'))
    assert args == []
    assert options['catalog'] == 'cat'
    assert options['database'] == 'db'
    assert options['cluster_name'] == 'cluster'
    assert options['operation_timeout'] == 12
    assert options['secure'] is True
    assert options['auto_resume'] is False
    assert options['grpc_options'] == {'grpc.keepalive_time_ms': 1000}


def test_native_local_adapter_lifecycle_and_unsupported_rollback():
    from e6data_python_connector.async_connection import AsyncConnection
    from e6data_python_connector.async_dialect import AsyncAdaptE6dataConnection, E6dataAsyncDialect
    from e6data_python_connector.exceptions import NotSupportedError, ProgrammingError

    async def run():
        native = await AsyncConnection('localhost', 1, username='unit-user', password='unit-input').open()
        adapted = AsyncAdaptE6dataConnection(native)
        assert adapted.driver_connection is native
        assert E6dataAsyncDialect().do_rollback(adapted) is None
        with pytest.raises(NotSupportedError):
            await native.rollback()
        cursor = adapted.cursor()
        assert cursor.description is None
        assert cursor.rowcount == -1
        cursor.arraysize = 3
        assert cursor.arraysize == 3
        assert cursor.fetchone() is None
        assert cursor.fetchmany() == []
        assert cursor.fetchall() == []
        assert list(cursor) == []
        assert cursor.setinputsizes([]) is None
        assert cursor.setoutputsize(10) is None
        with pytest.raises(ProgrammingError):
            await greenlet_spawn(cursor.execute, '')
        await greenlet_spawn(cursor.close)
        await greenlet_spawn(adapted.close)
        assert not native.check_connection()
    asyncio.run(run())


def test_hooks_are_sync():
    from e6data_python_connector.async_dialect import E6dataAsyncDialect
    for name in ('get_schema_names', 'get_table_names', 'get_columns', '_get_table_columns', 'do_ping', 'do_rollback'):
        assert not inspect.iscoroutinefunction(getattr(E6dataAsyncDialect, name))


def test_repeated_invalid_execute_keeps_dbapi_cursor_reusable():
    from e6data_python_connector.async_connection import AsyncConnection
    from e6data_python_connector.async_dialect import AsyncAdaptE6dataConnection
    from e6data_python_connector.exceptions import ProgrammingError

    async def run():
        native = await AsyncConnection('localhost', 1, username='unit-user', password='unit-input').open()
        cursor = AsyncAdaptE6dataConnection(native).cursor()
        for _ in range(2):
            with pytest.raises(ProgrammingError, match='nonempty'):
                await greenlet_spawn(cursor.execute, '')
        await greenlet_spawn(cursor.close)
        await native.close()
    asyncio.run(run())


def test_real_async_engine_local_initialization_errors_reset_and_disposal():
    from sqlalchemy.exc import DBAPIError
    from e6data_python_connector.exceptions import ProgrammingError

    async def run():
        engine = create_async_engine('e6data+asyncio://localhost:1', connect_args={
            'username': 'unit-user', 'password': 'unit-input', 'database': 'unit-schema'})
        native = None
        try:
            async with engine.connect() as conn:
                raw = await conn.get_raw_connection()
                native = raw.driver_connection
                assert native.check_connection()
                assert await conn.run_sync(lambda sync: sync.dialect.default_schema_name) == 'unit-schema'
                with pytest.raises(DBAPIError) as failure:
                    await conn.exec_driver_sql('')
                assert isinstance(failure.value.orig, ProgrammingError)
                with pytest.raises(DBAPIError):
                    async with conn.stream(text('')):
                        pass
                await conn.rollback()
            async with engine.connect() as conn:
                assert (await conn.get_raw_connection()).driver_connection is native
        finally:
            await engine.dispose()
        assert not native.check_connection()
    asyncio.run(run())


def test_streaming_adapter_normalizes_native_in_memory_rows():
    from e6data_python_connector.async_connection import AsyncConnection
    from e6data_python_connector.async_dialect import AsyncAdaptE6dataConnection

    async def run():
        native = await AsyncConnection('localhost', 1, username='unit-user', password='unit-input').open()
        adapted = AsyncAdaptE6dataConnection(native)
        cursor = adapted.cursor(server_side=True)
        # Pure in-memory result state, with no generated response or transport.
        cursor._cursor._state = 'EXHAUSTED'
        cursor._cursor._accept_rows([[1, 'first'], [2, 'second'], [3, 'third']])
        assert await greenlet_spawn(cursor.fetchone) == [1, 'first']
        assert await greenlet_spawn(cursor.fetchmany, 1) == [[2, 'second']]
        assert await greenlet_spawn(cursor.fetchall) == [[3, 'third']]
        assert await greenlet_spawn(cursor.fetchone) is None
        await greenlet_spawn(cursor.close)
        empty = adapted.cursor()
        await greenlet_spawn(empty.executemany, 'SELECT 1', [])
        assert empty.fetchall() == []
        await greenlet_spawn(empty.close)
        await greenlet_spawn(adapted.commit)
        await greenlet_spawn(adapted.close)
    asyncio.run(run())


@pytest.mark.parametrize('streaming', [False, True])
def test_async_engine_discards_native_after_ambiguous_submission(streaming):
    import socket
    from sqlalchemy.exc import DBAPIError
    from e6data_python_connector.exceptions import AmbiguousSubmissionError

    async def run():
        # A bound, non-listening socket is an actual unavailable local receiver.
        with socket.socket() as unavailable:
            unavailable.bind(('127.0.0.1', 0))
            port = unavailable.getsockname()[1]
            engine = create_async_engine('e6data+asyncio://127.0.0.1:{}'.format(port), connect_args={
                'access_token': 'unit-input', 'secure': True, 'auto_resume': False,
                'operation_timeout': .2, 'cleanup_timeout': .1}, pool_size=1, max_overflow=0)
            native = None
            try:
                async with engine.connect() as conn:
                    native = (await conn.get_raw_connection()).driver_connection
                    with pytest.raises(DBAPIError) as failure:
                        if streaming:
                            async with conn.stream(text('SELECT 1')):
                                pass
                        else:
                            await conn.exec_driver_sql('SELECT 1')
                    assert isinstance(failure.value.orig, AmbiguousSubmissionError)
                    assert failure.value.orig.__cause__ is not None
                    assert native._ambiguous_submissions
                async with engine.connect() as conn:
                    replacement = (await conn.get_raw_connection()).driver_connection
                    assert replacement is not native
                    assert not replacement._ambiguous_submissions
                assert not native.check_connection()
            finally:
                await engine.dispose()
    asyncio.run(run())


def test_adapter_reset_retires_unresolved_native_state():
    from e6data_python_connector.async_connection import AsyncConnection
    from e6data_python_connector.async_dialect import AsyncAdaptE6dataConnection, E6dataAsyncDialect
    from e6data_python_connector.exceptions import OperationalError

    async def run():
        native = await AsyncConnection('localhost', 1, username='unit-user', password='unit-input').open()
        cursor = native.cursor()
        native._ambiguous_submissions.add(cursor)
        adapted = AsyncAdaptE6dataConnection(native)
        with pytest.raises(OperationalError):
            await greenlet_spawn(E6dataAsyncDialect().do_rollback, adapted)
        assert not native.check_connection()
        assert native._ambiguous_submissions
    asyncio.run(run())


def test_adapter_reports_known_route_cleanup_failure_and_retires_on_reset():
    from e6data_python_connector.async_connection import AsyncConnection, QueryRoute
    from e6data_python_connector.async_dialect import AsyncAdaptE6dataConnection, E6dataAsyncDialect
    from e6data_python_connector.exceptions import OperationalError

    async def run():
        native = await AsyncConnection('localhost', 1, username='unit-user', password='unit-input').open()
        adapted = AsyncAdaptE6dataConnection(native)
        cursor = adapted.cursor(server_side=True)
        route = QueryRoute(native.target, 'unit-query', 'unit-planner', 'blue')
        native._register_route(route)
        cursor._cursor._route = route
        # There is no legacy session: cleanup rejects locally before dispatch.
        with pytest.raises(OperationalError) as failure:
            await greenlet_spawn(cursor.close)
        assert adapted._cleanup_error is failure.value
        assert E6dataAsyncDialect().is_disconnect(failure.value, adapted, cursor)
        with pytest.raises(OperationalError):
            await greenlet_spawn(adapted.rollback)
        assert not native.check_connection()
        assert route.query_id in native._routes
    asyncio.run(run())


def test_async_soft_close_preserves_buffered_rows_and_metadata():
    """SQLAlchemy 2.0.52 awaits this hook before exposing buffered Results."""
    from e6data_python_connector.async_connection import AsyncConnection
    from e6data_python_connector.async_dialect import AsyncAdaptE6dataConnection

    async def run():
        native = await AsyncConnection('localhost', 1, username='unit-user', password='unit-input').open()
        adapted = AsyncAdaptE6dataConnection(native)
        cursor = adapted.cursor()
        # Exercise the real adapter's buffered state without a network service.
        await cursor._cursor.close()
        cursor._native_closed = True
        cursor._rows.extend([[1], [2]])
        cursor._description = [('number', int, None, None, None, None, None)]
        cursor._rowcount = 2
        await cursor._async_soft_close()
        await cursor._async_soft_close()
        assert cursor.description[0][0] == 'number'
        assert cursor.rowcount == 2
        assert cursor.fetchone() == [1]
        assert cursor.fetchall() == [[2]]
        cursor.close()
        await native.close()
    asyncio.run(run())
