"""Real RPC regressions on an explicitly prepared, exclusive-use cluster.

The operator must suspend the cluster and disable auto-resume before opting in.
These tests observe real requests and never alter responses or cluster settings.
"""
import asyncio
import os
from pathlib import Path

import grpc
import pytest

from e6data_python_connector import Connection
from e6data_python_connector.aio import AsyncConnection
from e6data_python_connector.async_cluster_manager import AsyncClusterManager
from e6data_python_connector.cluster_manager import ClusterManager
from e6data_python_connector.exceptions import OperationalError


pytestmark = pytest.mark.integration


@pytest.fixture
def rejected_resume_config(live_config):
    if os.environ.get('E6_RESUME_REJECTION_AUTHORIZED') != '1':
        pytest.skip('Requires an exclusive suspended target with auto-resume disabled')
    if not live_config.connection_kwargs.get('password'):
        pytest.skip('This regression requires the legacy password authentication path')
    return live_config


def _manager_options(config):
    settings = config.connection_kwargs
    return dict(host=settings['host'], port=settings['port'],
                user=settings['username'], password=settings['password'],
                secure_channel=settings.get('secure', False),
                cluster_uuid=settings.get('cluster_name'),
                ssl_cert=settings.get('ssl_cert'),
                grpc_options=settings.get('grpc_options'), timeout=15)


class _ObservedSyncManager(ClusterManager):
    """Observe inherited real RPCs without replacing the transport."""

    def _try_cluster_request(self, operation):
        self.operations.append(operation)
        try:
            return super()._try_cluster_request(operation)
        except grpc.RpcError as error:
            self.errors.append(error)
            raise


class _ObservedAsyncManager(AsyncClusterManager):
    """Observe inherited real RPCs without replacing the transport."""

    async def _request(self, client, operation, deadline):
        self.operations.append(operation)
        try:
            return await super()._request(client, operation, deadline)
        except grpc.RpcError as error:
            self.errors.append(error)
            raise


def _observed_manager(manager_type, config, *, timeout=15, debug=False):
    options = _manager_options(config)
    options.update(timeout=timeout, debug=debug)
    manager = manager_type(**options)
    manager.operations = []
    manager.errors = []
    return manager


def _assert_disabled(error):
    assert error.code() == grpc.StatusCode.FAILED_PRECONDITION
    assert 'disabled' in error.details().lower()


def test_sync_active_cluster_does_not_dispatch_resume(live_config):
    if os.environ.get('E6_RESUME_ACTIVE_AUTHORIZED') != '1':
        pytest.skip('Requires an explicitly prepared active target')
    if not live_config.connection_kwargs.get('password'):
        pytest.skip('This regression requires the legacy password authentication path')
    manager = _observed_manager(_ObservedSyncManager, live_config, debug=True)
    try:
        assert manager.resume() is True
        assert manager.operations == ['status']
        assert manager.errors == []
    finally:
        if hasattr(manager, '_channel'):
            manager._channel.close()


def test_sync_resume_preserves_original_terminal_error(rejected_resume_config):
    manager = _observed_manager(_ObservedSyncManager, rejected_resume_config)
    try:
        with pytest.raises(grpc.RpcError) as raised:
            manager.resume()
        _assert_disabled(raised.value)
        assert raised.value is manager.errors[-1]
        assert manager.operations == ['status', 'resume']
    finally:
        if hasattr(manager, '_channel'):
            manager._channel.close()


def test_sync_query_preserves_disabled_resume_error(rejected_resume_config):
    options = dict(rejected_resume_config.connection_kwargs, auto_resume=True)
    with pytest.raises(grpc.RpcError) as raised:
        with Connection(**options) as connection:
            with connection.cursor() as cursor:
                cursor.execute(rejected_resume_config.read_only_sql)
    _assert_disabled(raised.value)


def test_async_resume_preserves_terminal_reason_and_cause(rejected_resume_config):
    async def run():
        manager = _observed_manager(_ObservedAsyncManager, rejected_resume_config)
        try:
            with pytest.raises(OperationalError) as raised:
                await manager.resume()
            cause = raised.value.__cause__
            _assert_disabled(cause)
            assert cause is manager.errors[-1]
            assert cause.details() in str(raised.value)
            assert manager.operations == ['status', 'resume']
        finally:
            await manager.close()
    asyncio.run(run())


def test_async_rejected_resume_allows_a_later_attempt(rejected_resume_config):
    async def run():
        manager = _observed_manager(_ObservedAsyncManager, rejected_resume_config)
        try:
            for _ in range(2):
                with pytest.raises(OperationalError) as raised:
                    await manager.resume()
                _assert_disabled(raised.value.__cause__)
                assert manager._mutation.pending is None
            assert manager.operations == ['status', 'resume', 'status', 'resume']
        finally:
            await manager.close()
    asyncio.run(run())


def test_async_same_manager_recovers_after_reenable(rejected_resume_config):
    signal_value = os.environ.get('E6_RESUME_REENABLE_SIGNAL')
    if not signal_value:
        pytest.skip('Requires operator re-enable coordination through a fresh signal path')
    signal = Path(signal_value)
    assert signal.is_absolute()
    rejected, enabled = Path(str(signal) + '.rejected'), Path(str(signal) + '.enabled')
    assert not rejected.exists() and not enabled.exists(), 'Use a fresh signal path'

    async def run():
        manager = _observed_manager(_ObservedAsyncManager, rejected_resume_config, timeout=300)
        try:
            with pytest.raises(OperationalError) as raised:
                await manager.resume()
            _assert_disabled(raised.value.__cause__)
            assert manager._mutation.pending is None
            rejected.touch(mode=0o600)
            async with asyncio.timeout(180):
                while not enabled.exists():
                    await asyncio.sleep(.25)
            assert await manager.resume()
            assert manager._mutation.pending is None
            assert manager.operations.count('resume') == 2
            async with AsyncConnection(**rejected_resume_config.connection_kwargs) as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(rejected_resume_config.read_only_sql)
                    assert [list(row) for row in await cursor.fetchall()] == rejected_resume_config.expected_rows
        finally:
            await manager.close()
            rejected.unlink(missing_ok=True)
            enabled.unlink(missing_ok=True)
    asyncio.run(run())
