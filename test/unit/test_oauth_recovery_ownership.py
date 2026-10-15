"""Independent review probes. Test doubles only; no production source changes."""
import threading
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from e6data_python_connector import cluster_manager
from e6data_python_connector.cluster_server import cluster_pb2 as pb
from e6data_python_connector.oauth_cache import TokenState
from e6data_python_connector.oauth_common import validate_token_response
from e6data_python_connector.exceptions import OAuthError
from e6data_python_connector.async_cluster_manager import _ResumeState


def test_healthy_workspace_is_not_blocked_by_another_workspace_preflight():
    entered = threading.Event()
    release = threading.Event()
    healthy_calls = []
    def slow_status(request, **kwargs):
        entered.set()
        assert release.wait(2)
        return pb.ClusterStatusResponse(status='active')
    def healthy_status(request, **kwargs):
        healthy_calls.append(request)
        return pb.ClusterStatusResponse(status='active')
    def manager(name):
        return cluster_manager.ClusterManager('fixture.invalid', 443, '', '', secure_channel=True,
            cluster_uuid=name, metadata_provider=lambda selected, deadline, rejected_token=None: [
                ('authorization', 'Bearer fixture-test-token')], deadline=time.monotonic() + 2)
    a, b = manager('workspace-a/cluster-a'), manager('workspace-b/cluster-b')
    clients = {a.cluster_uuid: SimpleNamespace(status=slow_status), b.cluster_uuid: SimpleNamespace(status=healthy_status)}
    with ThreadPoolExecutor(max_workers=1) as executor, patch.object(
            cluster_manager.ClusterManager, '_get_connection', new=property(lambda self: clients[self.cluster_uuid])):
        first = executor.submit(a.resume)
        try:
            assert entered.wait(1)
            assert b.resume(deadline=time.monotonic() + 0.05) is True
            assert len(healthy_calls) == 1
        finally:
            release.set()
            first.result(timeout=2)




@pytest.mark.parametrize('validator', [lambda value: cluster_manager.ClusterManager._oauth_status(SimpleNamespace(status=value)),
                                      lambda value: _ResumeState().observe(value)])
def test_unknown_cluster_status_does_not_echo_remote_content(validator):
    secret = 'fixture-remote-credential-sentinel'
    with pytest.raises(RuntimeError) as caught:
        validator(secret)
    assert secret not in str(caught.value)


def test_same_auth_owner_and_target_keep_pending_resume_across_managers():
    from test.test_oauth_auto_resume import ScriptedRPC
    from test.test_cluster_manager_oauth import manager_for
    def metadata(strategy, deadline, rejected_token=None):
        return [('authorization', 'Bearer test-only-credential')]
    client = SimpleNamespace(status=ScriptedRPC(
        *(pb.ClusterStatusResponse(status='suspended') for _ in range(4))),
        resume=ScriptedRPC(KeyboardInterrupt(), pb.ResumeResponse(status='active')))
    first, stub = manager_for(client, metadata_provider=metadata)
    second, _ = manager_for(client, metadata_provider=metadata)
    with stub:
        with pytest.raises(KeyboardInterrupt):
            first.resume()
        with pytest.raises(RuntimeError):
            second.resume()
    assert len(client.resume.calls) == 1


@pytest.mark.parametrize('managed', [False, True])
def test_separate_connections_share_pending_resume_only_for_matching_auth_and_target(managed):
    from test.test_oauth_auto_resume import make_connection, ScriptedRPC
    from test.test_cluster_manager_oauth import manager_for
    auth = ({'access_token': None, 'client_id': 'shared-resume-owner-fixture',
             'client_secret': 'test-secret', 'token_url': 'https://issuer.invalid/token'}
            if managed else {'access_token': 'shared-resume-static-fixture'})
    first_connection, second_connection = make_connection(**auth), make_connection(**auth)
    for connection in (first_connection, second_connection):
        connection._channel = None
        if managed:
            connection._token_provider._access_token = 'test-token'
            connection._token_provider._expires_at = time.monotonic() + 300
    client = SimpleNamespace(status=ScriptedRPC(
        pb.ClusterStatusResponse(status='suspended'), pb.ClusterStatusResponse(status='suspended')),
        resume=ScriptedRPC(KeyboardInterrupt()))
    first, stub = manager_for(client, metadata_provider=first_connection._oauth_metadata)
    second, _ = manager_for(client, metadata_provider=second_connection._oauth_metadata)
    other = cluster_manager.ClusterManager('fixture.invalid', 443, '', '', secure_channel=True,
        cluster_uuid='another-target', metadata_provider=second_connection._oauth_metadata)
    try:
        assert first._oauth_recovery is second._oauth_recovery
        assert other._oauth_recovery is not second._oauth_recovery
        with stub:
            with pytest.raises(KeyboardInterrupt):
                first.resume()
            with pytest.raises(RuntimeError, match='refusing a second mutation'):
                second.resume()
        assert len(client.resume.calls) == 1
        assert len(client.status.calls) == 2
    finally:
        first_connection.close()
        second_connection.close()


def test_recovery_registry_releases_states_after_the_last_manager():
    import gc
    import weakref
    def metadata(strategy, deadline, rejected_token=None):
        return [('authorization', 'Bearer temporary-owner-fixture')]
    manager = cluster_manager.ClusterManager('fixture.invalid', 443, '', '', secure_channel=True,
        cluster_uuid='temporary-target', metadata_provider=metadata)
    state = weakref.ref(manager._oauth_recovery)
    del manager
    gc.collect()
    assert state() is None


@pytest.mark.skipif(not hasattr(os, 'fork'), reason='requires fork')
def test_child_can_create_new_recovery_state_when_parent_registry_was_locked():
    result = subprocess.run([sys.executable, '-c', '''
import os
import signal
from e6data_python_connector import cluster_manager as cm
cm._oauth_recovery_registry_lock.acquire()
pid = os.fork()
if pid == 0:
    signal.signal(signal.SIGALRM, lambda *_: os._exit(17))
    signal.alarm(1)
    cm._oauth_recovery_state('child.test', 443, 'child-cluster', lambda *args: [])
    os._exit(0)
_, status = os.waitpid(pid, 0)
cm._oauth_recovery_registry_lock.release()
assert os.waitstatus_to_exitcode(status) == 0, status
'''], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not hasattr(os, 'fork'), reason='requires fork')
def test_inherited_manager_rejects_before_waiting_on_parent_owned_lock():
    result = subprocess.run([sys.executable, '-c', '''
import os
import time
from e6data_python_connector.cluster_manager import ClusterManager
from e6data_python_connector.exceptions import ProgrammingError
manager = ClusterManager('fixture.invalid', 443, '', '', secure_channel=True,
                         metadata_provider=lambda *args: [])
manager._oauth_recovery.lock.acquire()
pid = os.fork()
if pid == 0:
    try:
        manager.resume(deadline=time.monotonic() + .05)
    except ProgrammingError:
        os._exit(0)
    except BaseException:
        os._exit(17)
    os._exit(18)
_, status = os.waitpid(pid, 0)
manager._oauth_recovery.lock.release()
assert os.waitstatus_to_exitcode(status) == 0, status
'''], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
