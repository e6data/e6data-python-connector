"""Mutation safety with labeled, deterministic in-process transport test doubles."""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import patch

import grpc
import pytest

from e6data_python_connector import cluster_manager
from e6data_python_connector.async_cluster_manager import AsyncClusterManager
from e6data_python_connector.async_connection import AsyncConnection
from e6data_python_connector.async_connection_pool import AsyncConnectionPool
from e6data_python_connector.exceptions import OperationalError
from e6data_python_connector.cluster_server import cluster_pb2 as pb
from test.test_oauth_auto_resume import ScriptedRPC, rpc_error
from test.test_cluster_manager_oauth import manager_for
from test.unit.test_oauth_dispatch_safety import AsyncRPC


@pytest.mark.parametrize('failure', [
    (grpc.StatusCode.UNAUTHENTICATED, 'expired'),
    (grpc.StatusCode.UNKNOWN, 'status: 456'),
])
def test_sync_resume_is_single_dispatch_even_after_auth_or_routing_error(failure):
    client = SimpleNamespace(resume=ScriptedRPC(
        rpc_error(*failure), pb.ResumeResponse(status='active')))
    manager, _ = manager_for(client)
    with pytest.raises(grpc.RpcError):
        manager._oauth_cluster_request(client, 'resume')
    assert len(client.resume.calls) == 1


def test_sync_uncertain_resume_survives_later_recovery_attempt():
    client = SimpleNamespace(
        status=ScriptedRPC(*(pb.ClusterStatusResponse(status='suspended') for _ in range(4))),
        resume=ScriptedRPC(rpc_error(grpc.StatusCode.UNAVAILABLE, 'lost'),
                           pb.ResumeResponse(status='resuming')))
    manager, _ = manager_for(client)
    with patch.object(cluster_manager.cluster_pb2_grpc, 'ClusterServiceStub', return_value=client):
        with pytest.raises(RuntimeError):
            manager.resume()
        with pytest.raises(RuntimeError):
            manager.resume()
    assert len(client.resume.calls) == 1


@pytest.mark.parametrize('failure', [
    (grpc.StatusCode.UNAUTHENTICATED, 'expired'),
    (grpc.StatusCode.UNKNOWN, 'status: 456'),
])
def test_async_resume_is_single_dispatch_even_after_auth_or_routing_error(failure):
    async def run():
        async def metadata(strategy, deadline, rejected_token=None):
            return [('authorization', 'Bearer replacement' if rejected_token else 'Bearer initial')]
        manager = AsyncClusterManager('fixture.invalid', 443, secure_channel=True,
                                      metadata_provider=metadata)
        rpc = AsyncRPC(rpc_error(*failure), pb.ResumeResponse(status='active'))
        with pytest.raises(grpc.RpcError):
            await manager._request(SimpleNamespace(resume=rpc), 'resume',
                                   asyncio.get_running_loop().time() + 1)
        assert len(rpc.calls) == 1
        assert manager._mutation.pending == 'unknown'
    asyncio.run(run())


def test_async_static_connection_does_not_retry_rejected_status_token():
    async def run():
        connection = AsyncConnection('fixture.invalid', 443, secure=True, access_token='static-token')
        await connection.open()
        rpc = AsyncRPC(rpc_error(grpc.StatusCode.UNAUTHENTICATED, 'expired'),
                       pb.ClusterStatusResponse(status='active'))
        try:
            with patch('e6data_python_connector.async_cluster_manager.bindings.ClusterServiceStub',
                       return_value=SimpleNamespace(status=rpc)):
                with pytest.raises(OperationalError):
                    await connection._resume_cluster(connection._deadline())
            assert len(rpc.calls) == 1
        finally:
            await connection.close()
    asyncio.run(run())


def test_async_static_pool_rejects_refresh_request():
    async def run():
        pool = AsyncConnectionPool(host='fixture.invalid', port=443, secure=True,
                                   access_token='static-token')
        assert await pool._resume_metadata('blue', time.monotonic() + 1) == [
            ('authorization', 'Bearer static-token'), ('strategy', 'blue')]
        assert await pool._resume_metadata('blue', time.monotonic() + 1,
                                           rejected_token='static-token') is None
    asyncio.run(run())


def test_sync_recovery_error_does_not_expose_server_details():
    import traceback
    secret = 'recovery-credential-sentinel'
    client = SimpleNamespace(status=ScriptedRPC(rpc_error(grpc.StatusCode.PERMISSION_DENIED, secret)))
    manager, stub = manager_for(client)
    with stub, pytest.raises(grpc.RpcError) as caught:
        manager.resume()
    assert caught.value.code() == grpc.StatusCode.PERMISSION_DENIED
    assert secret not in ''.join(traceback.format_exception(caught.value))


def test_async_recovery_error_does_not_expose_server_details():
    import traceback
    async def run():
        secret = 'recovery-credential-sentinel'
        async def metadata(strategy, deadline, rejected_token=None):
            return [('authorization', 'Bearer test-token')]
        manager = AsyncClusterManager('fixture.invalid', 443, secure_channel=True,
                                      metadata_provider=metadata)
        rpc = AsyncRPC(rpc_error(grpc.StatusCode.PERMISSION_DENIED, secret))
        try:
            with patch('e6data_python_connector.async_cluster_manager.bindings.ClusterServiceStub',
                       return_value=SimpleNamespace(status=rpc)):
                with pytest.raises(OperationalError) as caught:
                    await manager.resume()
            assert secret not in ''.join(traceback.format_exception(caught.value))
        finally:
            await manager.close()
    asyncio.run(run())


def test_sync_interrupted_resume_is_not_repeated_by_later_attempt():
    client = SimpleNamespace(status=ScriptedRPC(
        pb.ClusterStatusResponse(status='suspended'), pb.ClusterStatusResponse(status='suspended')),
        resume=ScriptedRPC(KeyboardInterrupt(), pb.ResumeResponse(status='resuming')))
    manager, stub = manager_for(client)
    with stub:
        with pytest.raises(KeyboardInterrupt):
            manager.resume()
        with pytest.raises(RuntimeError, match='refusing a second mutation'):
            manager.resume()
    assert len(client.resume.calls) == 1
