"""Shared recovery regressions using explicit local RPC test doubles."""

import asyncio
import time
import threading
import gc
from types import SimpleNamespace
from unittest.mock import patch

import grpc
import pytest

from e6data_python_connector.async_connection import AsyncConnection
from e6data_python_connector.async_connection_pool import AsyncConnectionPool
from e6data_python_connector.async_cluster_manager import _ResumeState
from e6data_python_connector.cluster_manager import ClusterManager
from e6data_python_connector.cluster_server import cluster_pb2 as pb
from e6data_python_connector.exceptions import OperationalError
from test.test_oauth_auto_resume import make_connection, rpc_error


def connection_options(managed=False, identity='shared-owner-fixture', target='cluster-a'):
    source = ({'client_id': identity, 'client_secret': 'test-secret',
               'token_url': 'https://issuer.invalid/token'} if managed
              else {'access_token': identity})
    return dict(host='fixture.invalid', port=443, secure=True, cluster_name=target,
                auto_resume_timeout=.1, cleanup_timeout=.1, **source)


async def open_connection(options):
    connection = AsyncConnection(**options)
    await connection.open()
    if connection._token_provider is not None:
        connection._token_provider._access_token = 'test-access-token'
        connection._token_provider._expires_at = time.monotonic() + 300
    return connection


class RecoveryRPC:
    """A local transport double with an observable uncertain resume mutation."""

    def __init__(self, cancel_first=False):
        self.resume_calls = 0
        self.status_calls = 0
        self.dispatched = asyncio.Event()
        self.cancel_first = cancel_first
        self.ready = False

    async def status(self, request, **kwargs):
        self.status_calls += 1
        return pb.ClusterStatusResponse(status='active' if self.ready else 'suspended')

    async def resume(self, request, **kwargs):
        self.resume_calls += 1
        self.dispatched.set()
        if self.cancel_first and self.resume_calls == 1:
            await asyncio.Event().wait()
        raise rpc_error(grpc.StatusCode.UNAVAILABLE, 'test lost response')


@pytest.mark.parametrize('managed', [False, True])
@pytest.mark.parametrize('cancel_first', [False, True])
def test_sibling_connection_keeps_uncertain_resume(managed, cancel_first):
    async def run():
        options = connection_options(managed, 'uncertain-' + str(managed) + str(cancel_first))
        first, second = await open_connection(options), await open_connection(options)
        rpc = RecoveryRPC(cancel_first)
        try:
            with patch('e6data_python_connector.async_cluster_manager.bindings.ClusterServiceStub', return_value=rpc):
                task = asyncio.create_task(first._resume_cluster(asyncio.get_running_loop().time() + .06))
                await asyncio.wait_for(rpc.dispatched.wait(), 1)
                if cancel_first:
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                else:
                    with pytest.raises(OperationalError):
                        await task
                with pytest.raises(OperationalError):
                    await second._resume_cluster(asyncio.get_running_loop().time() + .06)
                assert rpc.resume_calls == 1, 'a sibling repeated an uncertain mutation'
                rpc.ready = True
                assert await second._resume_cluster(asyncio.get_running_loop().time() + .1)
                assert rpc.resume_calls == 1
        finally:
            await first.close()
            await second.close()
    asyncio.run(run())


@pytest.mark.parametrize('managed', [False, True])
def test_idle_async_sibling_keeps_pending_after_first_owner_is_dropped(managed):
    async def run():
        options = connection_options(managed, 'idle-sibling-' + str(managed))
        first, second = await open_connection(options), await open_connection(options)
        rpc = RecoveryRPC()
        try:
            with patch('e6data_python_connector.async_cluster_manager.bindings.ClusterServiceStub', return_value=rpc):
                with pytest.raises(OperationalError):
                    await first._resume_cluster(asyncio.get_running_loop().time() + .03)
                await first.close()
                del first
                gc.collect()
                with pytest.raises(OperationalError):
                    await second._resume_cluster(asyncio.get_running_loop().time() + .03)
                assert rpc.resume_calls == 1
        finally:
            await second.close()
    asyncio.run(run())


@pytest.mark.parametrize('managed', [False, True])
def test_idle_sync_and_async_owners_anchor_one_pending_state(managed):
    async def run():
        options = connection_options(managed, 'idle-cross-family-' + str(managed))
        sources = {key: value for key, value in options.items()
                   if key in ('access_token', 'client_id', 'client_secret', 'token_url')}
        if managed:
            sources['access_token'] = None
        first = make_connection(cluster_name=options['cluster_name'], **sources)
        second = make_connection(cluster_name=options['cluster_name'], **sources)
        first._channel = second._channel = None
        connection = await open_connection(options)
        try:
            assert first._oauth_recovery is second._oauth_recovery
            assert first._oauth_recovery is connection._oauth_recovery
            first._oauth_recovery.pending = True
            first.close()
            del first
            gc.collect()
            assert second._oauth_recovery.pending
            assert connection._oauth_recovery.pending
            second.close()
            del second
            gc.collect()
            assert connection._oauth_recovery.pending
        finally:
            await connection.close()
    asyncio.run(run())


def test_static_recovery_identity_is_validated_read_only_and_absent_for_legacy():
    connection = AsyncConnection(**connection_options(identity='immutable-static-fixture'))
    assert connection._static_access_token == 'immutable-static-fixture'
    with pytest.raises(AttributeError):
        connection._static_access_token = 'replacement-fixture'
    legacy = AsyncConnection('fixture.invalid', 443, username='fixture-user', password='fixture-password')
    assert legacy._static_access_token is None
    assert legacy._oauth_recovery is None
    pool = AsyncConnectionPool(host='fixture.invalid', port=443,
                               username='fixture-user', password='fixture-password')
    assert pool._static_access_token is None


@pytest.mark.parametrize('stale_status', ['active', 'suspended'])
def test_full_observation_phase_is_serialized(stale_status):
    async def run():
        first = await open_connection(connection_options(identity='fenced-' + stale_status))
        second = await open_connection(connection_options(identity='fenced-' + stale_status))
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def status(request, **kwargs):
            calls.append(asyncio.current_task())
            if len(calls) == 1:
                entered.set()
                await release.wait()
                return pb.ClusterStatusResponse(status=stale_status)
            return pb.ClusterStatusResponse(status='active')

        async def resume(request, **kwargs):
            return pb.ResumeResponse(status='resuming')

        tasks = []
        try:
            with patch('e6data_python_connector.async_cluster_manager.bindings.ClusterServiceStub',
                       return_value=SimpleNamespace(status=status, resume=resume)):
                tasks.append(asyncio.create_task(first._resume_cluster(asyncio.get_running_loop().time() + 1)))
                await asyncio.wait_for(entered.wait(), 1)
                tasks.append(asyncio.create_task(second._resume_cluster(asyncio.get_running_loop().time() + 1)))
                await asyncio.sleep(.02)
                assert len(calls) == 1, 'another recovery read status during an unresolved observation'
                release.set()
                assert await asyncio.gather(*tasks) == [True, True]
        finally:
            release.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await first.close()
            await second.close()
    asyncio.run(run())


@pytest.mark.parametrize('managed', [False, True])
def test_async_connection_pool_and_sync_share_credential_target_state(managed):
    async def run():
        options = connection_options(managed, 'identity-fixture-' + str(managed))
        connection = await open_connection(options)
        pool = AsyncConnectionPool(**options, min_size=0)
        await pool.open()
        if pool._token_provider is not None:
            pool._token_provider._access_token = 'test-access-token'
            pool._token_provider._expires_at = time.monotonic() + 300

        async def status(request, **kwargs):
            return pb.ClusterStatusResponse(status='active')

        try:
            with patch('e6data_python_connector.async_cluster_manager.bindings.ClusterServiceStub',
                       return_value=SimpleNamespace(status=status)):
                await connection._resume_cluster(asyncio.get_running_loop().time() + .1)
            sync = ClusterManager(options['host'], options['port'], '', '', secure_channel=True,
                                  cluster_uuid=options['cluster_name'], metadata_provider=connection._resume_metadata)
            sync._resume_pending = True
            assert connection._cluster_manager._mutation.pending
            assert pool._cluster_manager._mutation.pending
            connection._cluster_manager._mutation.observe('active')
            assert not sync._resume_pending
            assert pool._cluster_manager._mutation.pending is None
        finally:
            await connection.close()
            await pool.close_all()
    asyncio.run(run())


@pytest.mark.parametrize('changed', ['credential', 'target', 'host', 'port'])
def test_recovery_identity_does_not_cross_authority_or_target(changed):
    async def run():
        original = connection_options(identity='isolated-fixture-' + changed)
        other = dict(original)
        other[{'credential': 'access_token', 'target': 'cluster_name', 'host': 'host', 'port': 'port'}[changed]] = {
            'credential': 'different-fixture-token', 'target': 'cluster-b', 'host': 'other.invalid', 'port': 444}[changed]
        first, second = await open_connection(original), await open_connection(other)

        async def status(request, **kwargs):
            return pb.ClusterStatusResponse(status='active')

        try:
            with patch('e6data_python_connector.async_cluster_manager.bindings.ClusterServiceStub',
                       return_value=SimpleNamespace(status=status)):
                await first._resume_cluster(asyncio.get_running_loop().time() + .1)
                await second._resume_cluster(asyncio.get_running_loop().time() + .1)
            first._cluster_manager._mutation.dispatched()
            assert second._cluster_manager._mutation.pending is None
        finally:
            await first.close()
            await second.close()
    asyncio.run(run())


@pytest.mark.parametrize('asynchronous_first', [False, True])
@pytest.mark.parametrize('use_pool', [False, True])
@pytest.mark.parametrize('stale_status', ['active', 'suspended'])
def test_sync_async_and_pool_cannot_overlap_status_observations(asynchronous_first, use_pool, stale_status):
    async def run():
        options = connection_options(identity='cross-family-' + str(asynchronous_first) + str(use_pool) + stale_status)
        options['auto_resume_timeout'] = 2
        connection = await open_connection(options)
        pool = AsyncConnectionPool(**options, min_size=0)
        await pool.open()
        sync_connection = make_connection(access_token=options['access_token'], cluster_name=options['cluster_name'])
        sync_connection._channel = None
        sync = ClusterManager(options['host'], options['port'], '', '', secure_channel=True,
                              cluster_uuid=options['cluster_name'], metadata_provider=sync_connection._oauth_metadata)
        first_entered, release, second_started = threading.Event(), threading.Event(), threading.Event()
        observations = []

        async def async_status(request, **kwargs):
            observations.append('async')
            if asynchronous_first and observations == ['async']:
                first_entered.set()
                while not release.is_set():
                    await asyncio.sleep(.001)
                return pb.ClusterStatusResponse(status=stale_status)
            return pb.ClusterStatusResponse(status='active')

        def sync_status(request, **kwargs):
            observations.append('sync')
            if not asynchronous_first and observations == ['sync']:
                first_entered.set()
                assert release.wait(2)
                return pb.ClusterStatusResponse(status=stale_status)
            return pb.ClusterStatusResponse(status='active')

        async def async_resume(request, **kwargs):
            return pb.ResumeResponse(status='resuming')

        async def async_work():
            if not asynchronous_first:
                second_started.set()
            deadline = asyncio.get_running_loop().time() + 2
            return await (pool._cluster_manager.resume(deadline=deadline) if use_pool
                          else connection._resume_cluster(deadline))

        def sync_work():
            if asynchronous_first:
                second_started.set()
            return sync.resume(deadline=time.monotonic() + 2)

        tasks = []
        try:
            with patch('e6data_python_connector.async_cluster_manager.bindings.ClusterServiceStub',
                       return_value=SimpleNamespace(status=async_status, resume=async_resume)), \
                    patch.object(sync, '_get_connection', return_value=SimpleNamespace(
                        status=sync_status, resume=lambda *args, **kwargs: pb.ResumeResponse(status='resuming'))):
                tasks.append(asyncio.create_task(async_work() if asynchronous_first else asyncio.to_thread(sync_work)))
                assert await asyncio.to_thread(first_entered.wait, 1)
                tasks.append(asyncio.create_task(asyncio.to_thread(sync_work) if asynchronous_first else async_work()))
                assert await asyncio.to_thread(second_started.wait, 1)
                await asyncio.sleep(.02)
                assert observations == ['async' if asynchronous_first else 'sync']
                release.set()
                assert await asyncio.gather(*tasks) == [True, True]
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            await connection.close()
            await pool.close_all()
            sync_connection.close()
    asyncio.run(run())


@pytest.mark.parametrize('expired', [False, True])
def test_cancelled_or_expired_lock_waiter_does_not_unlock_another_owner(expired):
    async def run():
        state = _ResumeState()
        lock = state._shared.lock
        assert lock.acquire(blocking=False)

        async def wait():
            async with state.hold(asyncio.get_running_loop().time() + (.01 if expired else 1)):
                pytest.fail('waiter entered another owner\'s phase')

        task = asyncio.create_task(wait())
        try:
            if expired:
                with pytest.raises(TimeoutError):
                    await task
            else:
                await asyncio.sleep(.01)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert lock.locked()
        finally:
            lock.release()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with state.hold(asyncio.get_running_loop().time() + 1):
            assert lock.locked()
        assert not lock.locked()
    asyncio.run(run())
