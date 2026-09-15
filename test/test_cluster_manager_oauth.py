"""Recovery state machine and per-attempt OAuth credentials, without external services."""
import time
from types import SimpleNamespace
from unittest.mock import patch

import grpc
import pytest

from e6data_python_connector import cluster_manager
from e6data_python_connector.cluster_server import cluster_pb2 as pb
from test.test_oauth_auto_resume import ScriptedRPC, rpc_error


def manager_for(client, **kwargs):
    tokens = iter(['token-{}'.format(i) for i in range(100)])
    def metadata(strategy, deadline, rejected_token=None):
        return [('authorization', 'Bearer ' + next(tokens)), ('strategy', strategy),
                ('cluster-name', 'test-cluster')]
    values = dict(host='fixture.invalid', port=443, user='', password='',
                  metadata_provider=metadata, initial_strategy='blue')
    values.update(kwargs)
    manager = cluster_manager.ClusterManager(**values)
    return manager, patch.object(cluster_manager.ClusterManager, '_get_connection',
                                new=property(lambda _: client))


def test_every_poll_resume_and_fallback_has_current_bearer():
    client = SimpleNamespace(status=ScriptedRPC(rpc_error(grpc.StatusCode.UNKNOWN, 'status: 456'),
        pb.ClusterStatusResponse(status='suspended'), pb.ClusterStatusResponse(status='resuming'),
        pb.ClusterStatusResponse(status='active')), resume=ScriptedRPC(pb.ResumeResponse(status='resuming')))
    manager, stub = manager_for(client)
    with stub, patch.object(cluster_manager.time, 'sleep'):
        assert manager.resume() is True
    all_calls = client.status.calls + client.resume.calls
    bearers = [dict(kw['metadata'])['authorization'] for _, kw in all_calls]
    assert len(set(bearers)) == 5
    assert manager.last_successful_strategy == 'green'
    assert all(0 < kw['timeout'] <= 300 for _, kw in all_calls)
    assert all(request.user == request.password == '' for request, _ in all_calls)


@pytest.mark.parametrize('status', ['failed', '', 'unexpected'])
def test_invalid_status_is_terminal(status):
    client = SimpleNamespace(status=ScriptedRPC(pb.ClusterStatusResponse(status=status)))
    manager, stub = manager_for(client)
    with stub, pytest.raises(Exception, match='status|failed'):
        manager.resume()
    assert len(client.status.calls) == 1


@pytest.mark.parametrize('code', [grpc.StatusCode.PERMISSION_DENIED, grpc.StatusCode.UNIMPLEMENTED])
def test_terminal_rpc_error_is_preserved(code):
    error = rpc_error(code, 'denied')
    client = SimpleNamespace(status=ScriptedRPC(error))
    manager, stub = manager_for(client)
    with stub, pytest.raises(grpc.RpcError) as raised:
        manager.resume()
    assert raised.value is error
    assert len(client.status.calls) == 1


def test_lost_resume_response_reads_status_without_second_mutation():
    client = SimpleNamespace(status=ScriptedRPC(pb.ClusterStatusResponse(status='suspended'),
        pb.ClusterStatusResponse(status='resuming'), pb.ClusterStatusResponse(status='active')),
        resume=ScriptedRPC(rpc_error(grpc.StatusCode.UNAVAILABLE, 'response lost')))
    manager, stub = manager_for(client)
    with stub, patch.object(cluster_manager.time, 'sleep'):
        assert manager.resume()
    assert len(client.resume.calls) == 1


def test_lost_resume_response_and_still_suspended_is_ambiguous():
    client = SimpleNamespace(status=ScriptedRPC(pb.ClusterStatusResponse(status='suspended'),
        pb.ClusterStatusResponse(status='suspended')),
        resume=ScriptedRPC(rpc_error(grpc.StatusCode.UNAVAILABLE, 'response lost')))
    manager, stub = manager_for(client)
    with stub, pytest.raises(Exception, match='ambiguous'):
        manager.resume()
    assert len(client.resume.calls) == 1


def test_suspended_after_successful_resume_response_never_repeats_mutation():
    client = SimpleNamespace(status=ScriptedRPC(pb.ClusterStatusResponse(status='suspended'),
        pb.ClusterStatusResponse(status='suspended')),
        resume=ScriptedRPC(pb.ResumeResponse(status='resuming')))
    manager, stub = manager_for(client)
    with stub, pytest.raises(RuntimeError, match='second mutation'):
        manager.resume()
    assert len(client.resume.calls) == 1


def test_metadata_work_consumes_rpc_budget():
    client = SimpleNamespace(status=ScriptedRPC(pb.ClusterStatusResponse(status='active')))
    def slow_metadata(strategy, deadline, rejected_token=None):
        time.sleep(0.04)
        return [('authorization', 'Bearer fixture')]
    manager, stub = manager_for(client, metadata_provider=slow_metadata,
                                deadline=time.monotonic() + 0.02)
    with stub, pytest.raises(TimeoutError):
        manager.resume()
    assert not client.status.calls


def test_lock_wait_expires_without_releasing_another_owner():
    lock = cluster_manager.status_lock._status_thread_lock
    client = SimpleNamespace(status=ScriptedRPC(pb.ClusterStatusResponse(status='active')))
    manager, stub = manager_for(client, deadline=time.monotonic() + 0.03)
    assert lock.acquire(timeout=1)
    try:
        with stub, pytest.raises(TimeoutError):
            manager.resume()
        assert lock.locked()
        assert not client.status.calls
    finally:
        lock.release()


def test_process_lock_wait_releases_only_the_acquired_thread_lock():
    lock = cluster_manager.status_lock
    client = SimpleNamespace(status=ScriptedRPC(pb.ClusterStatusResponse(status='active')))
    manager, stub = manager_for(client, deadline=time.monotonic() + 0.03)
    assert lock._status_multiprocessing_lock.acquire(timeout=1)
    try:
        with stub, pytest.raises(TimeoutError):
            manager.resume()
        assert not lock._status_thread_lock.locked()
        assert not lock._status_multiprocessing_lock.acquire(block=False)
        assert not client.status.calls
    finally:
        lock._status_multiprocessing_lock.release()


def test_polling_expires_without_dispatching_another_rpc():
    client = SimpleNamespace(status=ScriptedRPC(pb.ClusterStatusResponse(status='resuming')))
    manager, stub = manager_for(client, deadline=time.monotonic() + 0.03)
    start = time.monotonic()
    with stub, pytest.raises(TimeoutError):
        manager.resume()
    assert time.monotonic() - start < 0.2
    assert len(client.status.calls) == 1


@pytest.mark.parametrize('request_type', ['status', 'resume'])
def test_explicit_unauthenticated_refreshes_once_per_logical_request(request_type):
    calls = []
    def metadata(strategy, deadline, rejected_token=None):
        calls.append(rejected_token)
        return [('authorization', 'Bearer ' + ('renewed' if rejected_token else 'expired'))]
    status = [pb.ClusterStatusResponse(status='suspended')] if request_type == 'resume' else []
    client = SimpleNamespace(status=ScriptedRPC(*status, pb.ClusterStatusResponse(status='active')),
                             resume=ScriptedRPC(pb.ResumeResponse(status='resuming')))
    target = getattr(client, request_type)
    target.results.insert(0 if request_type == 'resume' else 0,
                          rpc_error(grpc.StatusCode.UNAUTHENTICATED, 'expired'))
    manager, stub = manager_for(client, metadata_provider=metadata)
    with stub:
        assert manager.resume()
    assert calls.count('expired') == 1


def test_refresh_budget_is_shared_across_strategy_fallback():
    failure = rpc_error(grpc.StatusCode.UNAUTHENTICATED, 'still rejected')
    client = SimpleNamespace(status=ScriptedRPC(rpc_error(grpc.StatusCode.UNAUTHENTICATED, 'expired'),
        rpc_error(grpc.StatusCode.UNKNOWN, 'status: 456'), failure))
    manager, stub = manager_for(client)
    with stub, pytest.raises(grpc.RpcError) as raised:
        manager.resume()
    assert raised.value is failure
    assert len(client.status.calls) == 3


@pytest.mark.parametrize('status', ['', 'failed', 'unexpected'])
def test_malformed_resume_response_does_not_trigger_poll_or_prepare(status):
    client = SimpleNamespace(status=ScriptedRPC(pb.ClusterStatusResponse(status='suspended')),
                             resume=ScriptedRPC(pb.ResumeResponse(status=status)))
    manager, stub = manager_for(client)
    with stub, pytest.raises(RuntimeError):
        manager.resume()
    assert len(client.status.calls) == len(client.resume.calls) == 1


@pytest.mark.parametrize('code', [grpc.StatusCode.PERMISSION_DENIED, grpc.StatusCode.UNIMPLEMENTED,
                                 grpc.StatusCode.UNAUTHENTICATED])
def test_terminal_resume_failure_never_polls_or_repeats_mutation(code):
    failure = rpc_error(code, 'denied')
    client = SimpleNamespace(status=ScriptedRPC(pb.ClusterStatusResponse(status='suspended')),
                             resume=ScriptedRPC(failure, failure))
    manager, stub = manager_for(client)
    with stub, pytest.raises(grpc.RpcError) as raised:
        manager.resume()
    assert raised.value is failure
    assert len(client.status.calls) == 1
    assert len(client.resume.calls) == (2 if code == grpc.StatusCode.UNAUTHENTICATED else 1)
