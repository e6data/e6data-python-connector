"""Legacy resume regression tests with explicit remote-service test doubles."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from e6data_python_connector import cluster_manager as cm


class ObservedLock:
    """Test observer around the real lock; events control acquisition order."""

    def __init__(self, lock):
        self.lock = lock
        self.entered = {}
        self.gates = {}

    def watch(self, name, gate=None):
        self.entered[name] = threading.Event()
        if gate is not None:
            self.gates[name] = gate

    def acquire(self, *args, **kwargs):
        name = threading.current_thread().name
        if name in self.entered:
            self.entered[name].set()
        if name in self.gates:
            assert self.gates[name].wait(5), "test acquisition gate timed out"
        return self.lock.acquire(*args, **kwargs)

    def release(self):
        self.lock.release()

    def locked(self):
        return self.lock.locked()


class RemoteService:
    """Scripted RPC boundary test double, never a replacement for resume()."""

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.first_rpc = threading.Event()
        self.release_first = threading.Event()

    def request(self, manager, method):
        self.calls.append((threading.current_thread().name, method))
        if len(self.calls) == 1:
            self.first_rpc.set()
            assert self.release_first.wait(5), "test RPC gate timed out"
        response = next(self.responses, "active")
        if isinstance(response, BaseException):
            raise response
        return SimpleNamespace(status=response)


@pytest.fixture
def harness(monkeypatch):
    lock = cm._StatusLock()
    observer = ObservedLock(lock._status_thread_lock)
    lock._status_thread_lock = observer
    monkeypatch.setattr(cm, "status_lock", lock)
    monkeypatch.setattr(cm.time, "sleep", lambda _: None)
    workers = []
    results = {}
    errors = {}
    releases = []

    def remote(responses):
        service = RemoteService(responses)
        releases.append(service.release_first)
        monkeypatch.setattr(cm.ClusterManager, "_try_cluster_request",
                            lambda manager, method: service.request(manager, method))
        return service

    def start(name, manager=None, gate=None):
        observer.watch(name, gate)
        if gate is not None:
            releases.append(gate)

        def run():
            try:
                results[name] = (manager or manager_for()).resume()
            except BaseException as error:
                errors[name] = error

        worker = threading.Thread(name=name, target=run, daemon=True)
        workers.append(worker)
        worker.start()
        assert observer.entered[name].wait(5), "resume did not attempt the real lock"
        return worker

    def join(worker):
        worker.join(5)
        assert not worker.is_alive(), "resume worker did not finish"

    yield SimpleNamespace(lock=lock, observer=observer, remote=remote, start=start,
                          join=join, results=results, errors=errors)
    for release in releases:
        release.set()
    for worker in workers:
        worker.join(5)
        assert not worker.is_alive(), "test leaked a resume worker"
    assert not observer.locked()
    assert lock._status_multiprocessing_lock.acquire(block=False)
    lock._status_multiprocessing_lock.release()


def manager_for(**changes):
    values = dict(host="fixture.invalid", port=443, user="test-user",
                  password="test-secret", cluster_uuid="test-cluster",
                  secure_channel=True, grpc_options=[("grpc.keepalive_time_ms", 1000)])
    values.update(changes)
    return cm.ClusterManager(**values)


def finish_pair(harness, service, first=None, second=None):
    leader = harness.start("leader", first)
    assert service.first_rpc.wait(5)
    waiter = harness.start("waiter", second)
    service.release_first.set()
    harness.join(leader)
    harness.join(waiter)


@pytest.mark.parametrize("statuses", [["active"], ["suspended", "resuming", "resuming", "active"]])
def test_five_overlapping_callers_share_successful_resume(harness, statuses):
    service = harness.remote(statuses)
    workers = [harness.start("leader")]
    assert service.first_rpc.wait(5)
    workers.extend(harness.start("waiter-" + str(i)) for i in range(4))
    service.release_first.set()
    for worker in workers:
        harness.join(worker)
    assert not harness.errors
    assert list(harness.results.values()) == [True] * 5
    assert len(service.calls) == len(statuses)
    assert all(name == "leader" for name, _ in service.calls)


def test_later_independent_call_checks_and_resumes_again(harness):
    service = harness.remote(["active", "suspended", "resuming", "active"])
    service.release_first.set()
    assert manager_for().resume()
    assert manager_for().resume()
    assert [method for _, method in service.calls] == ["status", "status", "resume", "status"]


@pytest.mark.parametrize("failure", ["failed", RuntimeError("remote failure")])
def test_waiter_does_not_share_failure_or_exception(harness, failure):
    service = harness.remote([failure, "active"])
    finish_pair(harness, service)
    assert harness.results["waiter"] is True
    if isinstance(failure, BaseException):
        assert harness.errors == {"leader": failure}
    else:
        assert harness.results["leader"] is False
        assert not harness.errors
    assert len(service.calls) == 2


@pytest.mark.parametrize("failure", ["failed", RuntimeError("newer attempt failed")])
def test_newer_attempt_invalidates_success_before_delayed_waiter(harness, failure):
    service = harness.remote(["active", failure, "active"])
    leader = harness.start("leader")
    assert service.first_rpc.wait(5)
    gate = threading.Event()
    delayed = harness.start("delayed", gate=gate)
    service.release_first.set()
    harness.join(leader)
    newer = harness.start("newer")
    harness.join(newer)
    gate.set()
    harness.join(delayed)
    assert harness.results["delayed"] is True
    assert [name for name, _ in service.calls] == ["leader", "newer", "delayed"]
    if isinstance(failure, BaseException):
        assert harness.errors == {"newer": failure}
    else:
        assert harness.results["newer"] is False
        assert not harness.errors


@pytest.mark.parametrize("changes", [
    {"host": "other.invalid"}, {"port": 444}, {"cluster_uuid": "other-cluster"},
    {"user": "other-user"}, {"password": "rotated-secret"}, {"secure_channel": False},
    {"ssl_cert": b"test-certificate"}, {"ssl_cert": "/test/certificate.pem"},
    {"grpc_options": [("grpc.keepalive_time_ms", 2000)]},
    {"grpc_options": [("grpc.keepalive_time_ms", "1000")]},
])
def test_overlapping_different_identity_checks_status(harness, changes):
    service = harness.remote(["active", "active"])
    finish_pair(harness, service, second=manager_for(**changes))
    assert not harness.errors
    assert harness.results == {"leader": True, "waiter": True}
    assert len(service.calls) == 2


@pytest.mark.parametrize("changes", [
    {"grpc_options": [("grpc.test", [1])]},
    {"grpc_options": [("grpc.test", object())]},
    {"ssl_cert": bytearray(b"mutable-certificate")},
])
def test_unsupported_identity_safely_uses_fresh_status(harness, changes):
    service = harness.remote(["active", "active"])
    finish_pair(harness, service, manager_for(**changes), manager_for(**changes))
    assert not harness.errors
    assert len(service.calls) == 2


def test_same_dict_options_share_success(harness):
    service = harness.remote(["active"])
    options = {"grpc.keepalive_time_ms": 1000}
    finish_pair(harness, service, manager_for(grpc_options=options),
                manager_for(grpc_options=options.copy()))
    assert not harness.errors
    assert len(service.calls) == 1


def test_inherited_other_process_success_is_not_reused(harness, monkeypatch):
    service = harness.remote(["active", "active"])
    monkeypatch.setattr("os.getpid", lambda: 10 if threading.current_thread().name == "leader" else 20)
    finish_pair(harness, service)
    assert not harness.errors
    assert len(service.calls) == 2


def test_equal_completion_timestamp_is_not_reused(harness, monkeypatch):
    service = harness.remote(["active", "active"])
    monkeypatch.setattr(cm.time, "monotonic", lambda: 10.0)
    finish_pair(harness, service)
    assert not harness.errors
    assert len(service.calls) == 2


def test_success_record_does_not_keep_raw_credentials(harness):
    service = harness.remote(["active"])
    service.release_first.set()
    assert manager_for().resume()
    assert "test-secret" not in repr(vars(harness.lock))
    assert "test-user" not in repr(vars(harness.lock))


@pytest.mark.parametrize("which", ["thread", "process"])
@pytest.mark.parametrize("outcome", [False, RuntimeError("acquire failed")])
def test_legacy_lock_acquisition_failure_never_enters_or_releases_unowned_lock(which, outcome):
    lock = cm._StatusLock()
    thread_lock = Mock()
    process_lock = Mock()
    thread_lock.acquire.return_value = True
    process_lock.acquire.return_value = True
    target = thread_lock if which == "thread" else process_lock
    if isinstance(outcome, BaseException):
        target.acquire.side_effect = outcome
        expected = RuntimeError
    else:
        target.acquire.return_value = outcome
        expected = TimeoutError
    lock._status_thread_lock = thread_lock
    lock._status_multiprocessing_lock = process_lock
    entered = False
    with pytest.raises(expected):
        with lock:
            entered = True
    assert not entered
    process_lock.release.assert_not_called()
    if which == "process":
        thread_lock.release.assert_called_once_with()
    else:
        thread_lock.release.assert_not_called()
        process_lock.acquire.assert_not_called()


@pytest.mark.parametrize("statuses, expected, timeout, methods", [
    (["suspended", "resuming", "resuming", "active"], True, 300,
     ["status", "resume", "status", "status"]),
    (["resuming", "failed"], False, 300, ["status", "status"]),
    (["resuming", "resuming"], False, -1, ["status", "status"]),
    (["unexpected"], False, 300, ["status"]),
])
def test_legacy_debug_resume_status_paths(harness, statuses, expected, timeout, methods):
    service = harness.remote(statuses)
    service.release_first.set()
    assert manager_for(debug=True, timeout=timeout).resume() is expected
    assert [method for _, method in service.calls] == methods


@pytest.mark.parametrize("failure_at", ["initial-status", "resume", "poll"])
def test_legacy_rpc_failure_paths_preserve_retry_behavior(harness, failure_at):
    from test.test_oauth_auto_resume import rpc_error

    error = rpc_error()
    cases = {
        "initial-status": ([error], False, ["status"]),
        "resume": (["suspended", error], False, ["status", "resume"]),
        "poll": (["resuming", error, "active"], True, ["status", "status", "status"]),
    }
    statuses, expected, methods = cases[failure_at]
    service = harness.remote(statuses)
    service.release_first.set()
    assert manager_for(debug=True).resume() is expected
    assert [method for _, method in service.calls] == methods


@pytest.fixture
def legacy_strategy(monkeypatch):
    from e6data_python_connector import strategy

    strategy._clear_strategy_cache()
    pending = Mock(wraps=strategy._set_pending_strategy)
    monkeypatch.setattr(cm, "_set_pending_strategy", pending)
    yield strategy, pending
    strategy._clear_strategy_cache()


@pytest.mark.parametrize("initial", [None, "blue"])
@pytest.mark.parametrize("method", ["status", "resume"])
@pytest.mark.parametrize("fallback", [False, True])
def test_legacy_rpc_keeps_strategy_and_pending_transition(monkeypatch, legacy_strategy,
                                                         initial, method, fallback):
    import grpc
    from test.test_oauth_auto_resume import ScriptedRPC, rpc_error

    strategy, pending = legacy_strategy
    if initial is not None:
        strategy._set_active_strategy(initial)
    selected = "green" if fallback else "blue"
    next_strategy = "blue" if fallback else "green"
    response = SimpleNamespace(status="active", new_strategy=next_strategy.upper())
    results = ([rpc_error(grpc.StatusCode.UNKNOWN, "status: 456")] if fallback else []) + [response]
    remote_rpc = ScriptedRPC(*results)
    client = SimpleNamespace(**{method: remote_rpc})
    monkeypatch.setattr(cm.ClusterManager, "_get_connection", property(lambda _: client))

    assert manager_for(debug=True)._try_cluster_request(method) is response
    assert strategy._get_active_strategy() == selected
    pending.assert_called_once_with(next_strategy)
    assert [dict(call[1]["metadata"])["strategy"] for call in remote_rpc.calls] == (
        ["blue", "green"] if fallback else ["blue"])
    for request, _ in remote_rpc.calls:
        assert (request.user, request.password) == ("test-user", "test-secret")


@pytest.mark.parametrize("initial", [None, "blue"])
@pytest.mark.parametrize("failure", ["both-strategies", "non-retryable"])
def test_legacy_rpc_failures_keep_original_retry_contract(monkeypatch, legacy_strategy,
                                                         initial, failure):
    import grpc
    from test.test_oauth_auto_resume import ScriptedRPC, rpc_error

    strategy, pending = legacy_strategy
    if initial is not None:
        strategy._set_active_strategy(initial)
    first = rpc_error(grpc.StatusCode.UNKNOWN, "status: 456")
    second = rpc_error(grpc.StatusCode.UNAVAILABLE, "second strategy unavailable")
    errors = [first, second] if failure == "both-strategies" else [second]
    remote_rpc = ScriptedRPC(*errors)
    client = SimpleNamespace(status=remote_rpc)
    monkeypatch.setattr(cm.ClusterManager, "_get_connection", property(lambda _: client))
    with pytest.raises(grpc.RpcError) as raised:
        manager_for(debug=True)._try_cluster_request("status")
    expected = first if initial and failure == "both-strategies" else second
    assert raised.value is expected
    assert len(remote_rpc.calls) == len(errors)
    assert strategy._get_active_strategy() == initial
    pending.assert_not_called()
