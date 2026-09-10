"""Local configuration/state and native-channel contract tests, no test service."""
import asyncio
import dataclasses
import inspect
import socket

import grpc
import pytest

from e6data_python_connector.async_connection import AsyncConnection, QueryRoute
from e6data_python_connector.exceptions import ProgrammingError, NotSupportedError, OperationalError


def connection(**kwargs):
    return AsyncConnection('localhost', 1, username='unit-user', password='unit-input', **kwargs)


def test_local_constructor_and_defaults():
    conn = connection()
    assert not conn.check_connection()
    assert conn.operation_timeout == 600
    assert conn.cleanup_timeout == 10
    assert conn.oauth_timeout == 10
    assert conn.auto_resume_timeout == 300
    assert conn.max_receive_message_bytes == 64 * 1024 * 1024
    assert conn._channel is None


def test_new_opener_does_not_inherit_departed_callers_cancellation():
    from e6data_python_connector.async_work import reserve_work
    async def run():
        slots = [await reserve_work() for _ in range(4)]
        conn = connection(ssl_cert='/dev/null')
        try:
            first = asyncio.create_task(conn.open())
            while conn._open_waiters != 1:
                await asyncio.sleep(0)
            first.cancel()
            second = asyncio.create_task(conn.open())
            results = await asyncio.gather(first, second, return_exceptions=True)
            assert isinstance(results[0], asyncio.CancelledError)
            assert isinstance(results[1], ProgrammingError)
            assert second.cancelling() == 0
            assert conn._state == 'closed'
        finally:
            for slot in slots:
                slot.release()
            await conn.close()
    asyncio.run(run())


def test_completed_shared_recovery_strategy_is_adopted_without_moving_pinned_query():
    from e6data_python_connector.async_cluster_manager import AsyncClusterManager
    async def run():
        conn = await connection().open()
        manager = AsyncClusterManager('localhost', 1, user='unit-user', password='unit-input',
                                      initial_strategy='green')
        conn._cluster_manager = manager
        route = conn._register_route(QueryRoute(conn.target, 'unissued-local-handle', 'unit-engine', 'blue'))
        # A completed shared phase still owned by an earlier waiter. This is
        # local coordination state, not proof of a real cluster resume.
        manager._flight.task = asyncio.create_task(asyncio.sleep(0, result=True))
        manager._flight.waiters = 1
        await manager._flight.task
        try:
            assert await conn._resume_cluster(conn._deadline())
            assert conn.strategy == 'green'
            assert conn._route(route.query_id).strategy == 'blue'
        finally:
            manager._flight.waiters = 0
            conn._release_route(route.query_id)
            await conn.close()
    asyncio.run(run())


@pytest.mark.parametrize('kwargs', [dict(access_token='unit-token'), dict(client_id='id', client_secret='input', token_url='https://localhost/token')])
def test_oauth_rejects_insecure(kwargs):
    with pytest.raises(ValueError, match='TLS'):
        AsyncConnection('localhost', 1, **kwargs)


@pytest.mark.parametrize('kwargs', [dict(operation_timeout=0), dict(cleanup_timeout=float('inf')), dict(max_receive_message_bytes=-1), dict(grpc_options={'max_receive_message_length': -1})])
def test_invalid_limits(kwargs):
    with pytest.raises(ValueError):
        connection(**kwargs)


def test_network_methods_explicit():
    for name in ('open', 'close', 'reopen', 'get_session_id', 'get_re_authenticate_session_id', 'clear', 'query_cancel', 'dry_run', 'get_tables', 'get_columns', 'get_schema_names', 'commit', 'rollback'):
        assert inspect.iscoroutinefunction(getattr(AsyncConnection, name)), name
    assert not inspect.iscoroutinefunction(AsyncConnection.cursor)


def test_route_immutable():
    route = QueryRoute('localhost:1', 'unit-query', 'unit-engine', 'blue')
    with pytest.raises(dataclasses.FrozenInstanceError):
        route.strategy = 'green'


def test_native_channel_state_and_route_ownership():
    async def run():
        conn = connection()
        await conn.open()
        assert isinstance(conn._channel, grpc.aio.Channel)
        assert conn.check_connection()
        with pytest.raises(AttributeError):
            conn.password = 'changed'
        route = QueryRoute(conn.target, 'unit-query', 'unit-engine', 'blue')
        conn._register_route(route)
        with pytest.raises(ProgrammingError):
            await conn.reopen()
        with pytest.raises(ProgrammingError):
            await conn.clear('unknown')
        conn._release_route(route.query_id)
        with pytest.raises(NotSupportedError):
            await conn.rollback()
        await conn.commit()
        await conn.close()
        await conn.close()
        assert not conn.check_connection()
        await conn.reopen()
        await conn.close()
    asyncio.run(run())


def test_static_oauth_metadata_local():
    async def run():
        conn = AsyncConnection('localhost', 1, access_token='unit-token', secure=True, cluster_name='unit-cluster')
        async with conn:
            assert await conn.get_session_id() == ''
            assert ('authorization', 'Bearer unit-token') in await conn._metadata(conn._deadline())
    asyncio.run(run())


def test_cross_loop_rejected():
    conn = connection()
    owner = asyncio.new_event_loop()
    owner.run_until_complete(conn.open())
    try:
        async def wrong():
            with pytest.raises(ProgrammingError):
                await conn.commit()
        asyncio.run(wrong())
    finally:
        owner.run_until_complete(conn.close())
        owner.close()


def test_native_transport_failure_is_bounded():
    # An OS-reserved bound port has no listening service or invented response.
    with socket.socket() as unavailable:
        unavailable.bind(('127.0.0.1', 0))
        port = unavailable.getsockname()[1]
        async def run():
            async with AsyncConnection('127.0.0.1', port, username='unit-user', password='unit-input', operation_timeout=.2) as conn:
                with pytest.raises(OperationalError) as caught:
                    await conn.get_session_id()
                assert isinstance(caught.value.__cause__, (grpc.RpcError, TimeoutError))
                assert conn._session_id is None
        asyncio.run(run())


def test_cleanup_cannot_cross_owner():
    async def run():
        conn = connection()
        await conn.open()
        conn._owner = (-1, -1, None)
        with pytest.raises(ProgrammingError):
            conn._check_owner(_cleanup=True)
        conn._owner = (__import__('os').getpid(), __import__('threading').get_ident(), asyncio.get_running_loop())
        await conn.close()
    asyncio.run(run())


def test_strategy_mismatch_requires_exact_oauth_detail():
    from e6data_python_connector.async_connection import is_strategy_mismatch
    assert is_strategy_mismatch(grpc.StatusCode.UNKNOWN, 'status: 456', oauth=True)
    assert not is_strategy_mismatch(grpc.StatusCode.UNKNOWN, 'unrelated status: 456 text', oauth=True)
    assert is_strategy_mismatch(grpc.StatusCode.UNKNOWN, 'unrelated status: 456 text', oauth=False)
    assert not is_strategy_mismatch(grpc.StatusCode.UNAVAILABLE, 'status: 456', oauth=True)


def test_sync_import_does_not_load_optional_httpx():
    import subprocess
    import sys
    result = subprocess.run([sys.executable, '-c', "import sys; import e6data_python_connector; assert 'httpx' not in sys.modules"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_client_credentials_open_remains_local_and_owned():
    async def run():
        conn = AsyncConnection('localhost', 1, secure=True, client_id='unit-id', client_secret='unit-input', token_url='https://localhost/token')
        await conn.open()
        provider = conn._token_provider
        assert provider._client is None
        assert provider._task is None
        await conn.close()
        assert provider._closed
    asyncio.run(run())


def test_lease_guard_distinguishes_public_and_internal_work():
    async def run():
        conn = connection()
        await conn.open()
        owner_task = asyncio.current_task()
        lease_active = True
        def guard(*, internal=False):
            if not lease_active or (not internal and asyncio.current_task() is not owner_task):
                raise ProgrammingError('Lease is inactive or belongs to another task.')
        conn._lease_guard = guard
        await conn.commit()
        async def child():
            with pytest.raises(ProgrammingError):
                await conn.commit()
            assert ('strategy', 'blue') in await conn._metadata(asyncio.get_running_loop().time() + 1)
        await asyncio.create_task(child())
        lease_active = False
        with pytest.raises(ProgrammingError):
            await conn._metadata(asyncio.get_running_loop().time() + 1)
        conn._lease_guard = None
        await conn.close()
    asyncio.run(run())


def test_close_checks_owner_even_when_already_closing():
    async def run():
        conn = connection()
        await conn.open()
        owner = conn._owner
        conn._state = 'closing'
        conn._close_task = asyncio.create_task(asyncio.sleep(0))
        conn._owner = (-1, -1, None)
        with pytest.raises(ProgrammingError):
            await conn.close()
        await conn._close_task
        conn._owner = owner
        conn._state, conn._close_task = 'open', None
        await conn.close()
    asyncio.run(run())


def test_close_bounds_known_handle_cleanup_and_preserves_uncertainty():
    async def run():
        with socket.socket() as unavailable:
            unavailable.bind(('127.0.0.1', 0))
            conn = AsyncConnection('127.0.0.1', unavailable.getsockname()[1], access_token='unit-token', secure=True, cleanup_timeout=.03)
            await conn.open()
            route = QueryRoute(conn.target, 'unit-known-query', 'unit-engine', 'blue')
            conn._register_route(route)
            started = asyncio.get_running_loop().time()
            await conn.close()
            assert asyncio.get_running_loop().time() - started < .5
            assert conn._state == 'closed'
            assert conn._channel is None
            assert conn._routes[route.query_id] == route
            assert conn.cleanup_error is not None
    asyncio.run(run())


@pytest.mark.parametrize('kwargs', [dict(host='', port=1), dict(host='localhost', port=True), dict(host='localhost', port=65536), dict(host='localhost', port=1, username='only'), dict(host='localhost', port=1, client_id='only', secure=True), dict(host='localhost', port=1, access_token='contains space', secure=True), dict(host='localhost', port=1, access_token='token', secure=True, ssl_cert=123)])
def test_rejects_incomplete_or_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        AsyncConnection(**kwargs)


@pytest.mark.parametrize('name', ['ssl_target_name_override', 'grpc.default_authority'])
def test_rejects_tls_authority_override(name):
    with pytest.raises(ValueError, match='authority'):
        connection(grpc_options={name: 'unit-override'})


def test_route_headers_and_pending_strategy_are_connection_local():
    async def run():
        conn = connection(cluster_name='unit-cluster')
        other = connection()
        async with conn, other:
            route = QueryRoute(conn.target, 'unit-query', 'unit-engine', 'blue')
            conn._register_route(route)
            assert await conn._metadata(conn._deadline(), route) == [('strategy', 'blue'), ('plannerip', 'unit-engine'), ('cluster-name', 'unit-cluster')]
            with pytest.raises(ProgrammingError):
                await other._metadata(other._deadline(), route)
            with pytest.raises(ProgrammingError):
                conn._register_route(QueryRoute(conn.target, route.query_id, 'different-engine', 'blue'))
            with pytest.raises(ProgrammingError):
                conn._register_route(QueryRoute('different-target', 'other-query', 'engine', 'blue'))
            conn._pending_strategy = 'green'
            assert conn.check_strategy_change() == 'blue'
            conn._release_route(route.query_id)
            assert conn.strategy == 'green'
            assert other.strategy == 'blue'
            assert conn.client is conn._client
            with pytest.raises(TimeoutError):
                await conn._metadata(asyncio.get_running_loop().time() - 1)
    asyncio.run(run())


@pytest.mark.parametrize('method,args', [('get_tables', ('unit-catalog', 'unit-schema')), ('get_columns', ('unit-catalog', 'unit-schema', 'unit-table')), ('get_schema_names', ('unit-catalog',)), ('dry_run', ('SELECT 1',))])
def test_public_discovery_native_failures_are_operational(method, args):
    async def run():
        with socket.socket() as unavailable:
            unavailable.bind(('127.0.0.1', 0))
            async with AsyncConnection('127.0.0.1', unavailable.getsockname()[1], access_token='unit-token', secure=True, operation_timeout=.02) as conn:
                with pytest.raises(OperationalError) as caught:
                    await getattr(conn, method)(*args)
                assert isinstance(caught.value.__cause__, (grpc.RpcError, TimeoutError))
    asyncio.run(run())


def test_certificate_path_failure_does_not_publish_channel(tmp_path):
    async def run():
        conn = connection(secure=True, ssl_cert=str(tmp_path / 'missing-ca.pem'))
        with pytest.raises(FileNotFoundError):
            await conn.open()
        assert conn._channel is None
        await conn.close()
    asyncio.run(run())


def test_context_does_not_replace_owned_cluster_manager():
    async def run():
        from e6data_python_connector.async_cluster_manager import AsyncClusterManager
        conn = connection()
        manager = AsyncClusterManager('localhost', 1, user='unit-user', password='unit-input')
        conn._cluster_manager = manager
        async with conn:
            assert conn._cluster_manager is manager
        assert manager._closed
    asyncio.run(run())


def test_cancel_transport_failure_keeps_known_route():
    async def run():
        with socket.socket() as unavailable:
            unavailable.bind(('127.0.0.1', 0))
            conn = AsyncConnection('127.0.0.1', unavailable.getsockname()[1], access_token='unit-token', secure=True, operation_timeout=.02, cleanup_timeout=.02)
            await conn.open()
            route = QueryRoute(conn.target, 'unit-query', 'unit-engine', 'blue')
            conn._register_route(route)
            with pytest.raises(OperationalError):
                await conn.query_cancel(route.engine_ip, route.query_id)
            assert conn._routes[route.query_id] == route
            await conn.close()
    asyncio.run(run())


def test_close_cancels_pending_certificate_initialization_without_resurrection():
    from e6data_python_connector.async_work import reserve_work
    async def run():
        reservations = [await reserve_work() for _ in range(4)]
        conn = connection(ssl_cert='/dev/null')
        opening = asyncio.create_task(conn.open())
        try:
            await asyncio.sleep(.01)
            await conn.close()
        finally:
            for reservation in reservations:
                reservation.release()
        result = await asyncio.gather(opening, return_exceptions=True)
        assert isinstance(result[0], asyncio.CancelledError)
        assert conn._state == 'closed'
        assert conn._channel is None
        assert not conn.check_connection()
    asyncio.run(run())


def test_concurrent_open_owns_one_native_channel():
    async def run():
        conn = connection(ssl_cert='/dev/null')
        async def opening():
            await conn.open()
            return conn._channel
        channels = await asyncio.gather(opening(), opening())
        try:
            assert channels[0] is channels[1]
        finally:
            await conn.close()
            for channel in channels:
                await channel.close()
    asyncio.run(run())


def test_unknown_submission_is_visible_on_connection_close():
    async def run():
        conn = await connection().open()
        cursor = conn.cursor()
        conn._ambiguous_submissions.add(cursor)
        await conn.close()
        assert conn.cleanup_error is not None
    asyncio.run(run())


def test_session_waiter_arriving_during_retirement_is_not_cancelled():
    async def run():
        conn = await connection(operation_timeout=.1).open()
        first = asyncio.create_task(conn.get_session_id())
        try:
            while conn._session_waiters != 1:
                await asyncio.sleep(0)
            first.cancel()
            second = asyncio.create_task(conn.get_session_id())
            results = await asyncio.gather(first, second, return_exceptions=True)
            assert isinstance(results[0], asyncio.CancelledError)
            assert not isinstance(results[1], asyncio.CancelledError)
            assert second.cancelling() == 0
        finally:
            await conn.close()
    asyncio.run(run())


def test_concurrent_open_cancellation_keeps_surviving_waiter():
    from e6data_python_connector.async_work import reserve_work
    async def run():
        reservations = [await reserve_work() for _ in range(4)]
        conn = connection(ssl_cert='/dev/null')
        first, second = asyncio.create_task(conn.open()), asyncio.create_task(conn.open())
        try:
            await asyncio.sleep(.01)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
        finally:
            for reservation in reservations:
                reservation.release()
        assert await second is conn
        await conn.close()
    asyncio.run(run())
