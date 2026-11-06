"""Fork regressions using real locks and explicitly labeled RPC test doubles."""

import multiprocessing
import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from e6data_python_connector import cluster_manager as cm


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux fork regression")


class _EntryObserver:
    """Control ordering before acquisition of the real product thread lock."""

    def __init__(self, lock, barrier=None, entered=None, gate=None):
        self.lock, self.barrier, self.entered, self.gate = lock, barrier, entered, gate

    def acquire(self, *args, **kwargs):
        # resume() has already recorded entry time. Installed inside the child,
        # after any product at-fork callback resets its inherited local lock.
        if self.entered is not None:
            self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(10), "test entry gate timed out"
        if self.barrier is not None:
            self.barrier.wait(timeout=10)
        return self.lock.acquire(*args, **kwargs)

    def release(self):
        self.lock.release()


class _RemoteRPC:
    """Minimal process-shared remote-service test double, with scripted states."""

    def __init__(self, context, responses, block_first=False):
        self.responses = responses
        self.index = context.Value("i", 0)
        self.status_calls = context.Value("i", 0)
        self.resume_calls = context.Value("i", 0)
        self.first_entered = context.Event()
        self.release_first = context.Event()
        if not block_first:
            self.release_first.set()

    def request(self, method):
        counter = self.status_calls if method == "status" else self.resume_calls
        with counter.get_lock():
            counter.value += 1
        with self.index.get_lock():
            index = self.index.value
            self.index.value += 1
        if index == 0:
            self.first_entered.set()
            assert self.release_first.wait(10), "test RPC gate timed out"
        response = self.responses[index] if index < len(self.responses) else "active"
        if response == "raise":
            raise RuntimeError("remote test failure")
        return SimpleNamespace(status=response)

    @property
    def counts(self):
        return self.status_calls.value, self.resume_calls.value


def _child(output, changes, barrier, entered, gate, threads, independent, clock, lock_mode):
    """Construct managers after fork, as process-pool initializers do."""
    try:
        if independent:
            cm.status_lock = cm._StatusLock()
        cm.status_lock._status_thread_lock = _EntryObserver(
            cm.status_lock._status_thread_lock, barrier, entered, gate,
        )
        values = dict(host="fixture.invalid", port=443, user="test-user",
                      password="test-secret", cluster_uuid="test-cluster", secure_channel=True)
        values.update(changes)
        managers = [cm.ClusterManager(**values) for _ in range(threads)]
        if clock is not None:
            ticks = iter(clock) if isinstance(clock, list) else None
            cm.time.monotonic = (lambda: next(ticks)) if ticks is not None else (lambda: clock)
        results = []

        def run(manager):
            try:
                if lock_mode == "process-probe":
                    acquired = cm.status_lock._status_multiprocessing_lock.acquire(block=False)
                    if acquired:
                        cm.status_lock._status_multiprocessing_lock.release()
                    result = not acquired
                elif lock_mode == "legacy":
                    cm.status_lock._LOCK_TIMEOUT = 0
                    with cm.status_lock:
                        result = True
                elif lock_mode == "oauth":
                    with cm.status_lock.hold_until(time.monotonic() + 0.1):
                        result = True
                else:
                    result = manager.resume()
                results.append((result, None))
            except BaseException as error:
                results.append((None, type(error).__name__))

        if threads == 1:
            run(managers[0])
        else:
            workers = [threading.Thread(target=run, args=(manager,)) for manager in managers]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(10)
                assert not worker.is_alive(), "test leaked a child thread"
        output.send((os.getpid(), results))
    except BaseException as error:
        output.send((os.getpid(), [(None, type(error).__name__)]))
    finally:
        output.close()


@pytest.fixture
def processes(monkeypatch):
    context = multiprocessing.get_context("fork")
    lock = cm._StatusLock()
    monkeypatch.setattr(cm, "status_lock", lock)
    children, outputs, remotes, gates = [], [], [], []

    def remote(responses, block_first=False):
        rpc = _RemoteRPC(context, responses, block_first)
        remotes.append(rpc)
        monkeypatch.setattr(cm.ClusterManager, "_try_cluster_request",
                            lambda manager, method: rpc.request(method))
        return rpc

    def start(changes=None, barrier=None, entered=None, gate=None, threads=1,
              independent=False, clock=None, lock_mode=None):
        output, sender = context.Pipe(duplex=False)
        process = context.Process(target=_child, args=(
            sender, changes or {}, barrier, entered, gate, threads, independent, clock, lock_mode,
        ))
        process.start()
        sender.close()
        children.append(process)
        outputs.append(output)
        if gate is not None:
            gates.append(gate)
        return process, output

    def finish(worker):
        process, output = worker
        assert output.poll(15), "child did not finish resume"
        result = output.recv()
        process.join(5)
        assert process.exitcode == 0
        return result

    yield SimpleNamespace(context=context, lock=lock, remote=remote, start=start, finish=finish)
    for rpc in remotes:
        rpc.release_first.set()
    for gate in gates:
        gate.set()
    for process in children:
        if process.is_alive():
            process.terminate()
        process.join(5)
        assert not process.is_alive(), "test leaked a worker process"
        process.close()
    for output in outputs:
        output.close()
    assert lock._status_multiprocessing_lock.acquire(block=False)
    assert not lock._status_multiprocessing_lock.acquire(block=False)
    lock._status_multiprocessing_lock.release()


def _assert_success(results, process_count, threads=1):
    assert len({pid for pid, _ in results}) == process_count
    assert all(values == [(True, None)] * threads for _, values in results), results


@pytest.mark.parametrize("initially_active", [False, True], ids=["suspended", "already-active"])
def test_forked_waiters_share_successful_resume(processes, initially_active):
    rpc = processes.remote(["active"] if initially_active else ["suspended", "resuming", "active"])
    barrier = processes.context.Barrier(5)
    workers = [processes.start(barrier=barrier) for _ in range(5)]
    _assert_success([processes.finish(worker) for worker in workers], 5)
    assert rpc.counts == ((1, 0) if initially_active else (2, 1))


def test_mixed_threads_and_processes_share_completion(processes):
    rpc = processes.remote(["active"])
    barrier = processes.context.Barrier(4)
    workers = [processes.start(barrier=barrier, threads=2) for _ in range(2)]
    _assert_success([processes.finish(worker) for worker in workers], 2, threads=2)
    assert rpc.counts == (1, 0)


@pytest.mark.parametrize("changes", [
    {"host": "other.invalid"}, {"port": 444}, {"cluster_uuid": "other"},
    {"user": "other-user"}, {"password": "rotated-secret"}, {"secure_channel": False},
    {"ssl_cert": b"test-certificate"}, {"grpc_options": [("grpc.test", 1)]},
])
def test_forked_different_identity_does_not_share(processes, changes):
    rpc = processes.remote(["active", "active"])
    barrier = processes.context.Barrier(2)
    workers = [processes.start(barrier=barrier), processes.start(changes, barrier=barrier)]
    _assert_success([processes.finish(worker) for worker in workers], 2)
    assert rpc.counts == (2, 0)


def test_independent_storage_does_not_share_completion(processes):
    rpc = processes.remote(["active", "active"])
    barrier = processes.context.Barrier(2)
    workers = [processes.start(barrier=barrier, independent=True) for _ in range(2)]
    _assert_success([processes.finish(worker) for worker in workers], 2)
    assert rpc.counts == (2, 0)


def test_later_process_checks_new_suspension(processes):
    rpc = processes.remote(["active", "suspended", "resuming", "active"])
    _assert_success([processes.finish(processes.start())], 1)
    _assert_success([processes.finish(processes.start())], 1)
    assert rpc.counts == (3, 1)


def test_equal_timestamps_do_not_share(processes):
    rpc = processes.remote(["active", "active"])
    barrier = processes.context.Barrier(2)
    workers = [processes.start(barrier=barrier, clock=10.0) for _ in range(2)]
    _assert_success([processes.finish(worker) for worker in workers], 2)
    assert rpc.counts == (2, 0)


@pytest.mark.parametrize("failure", ["failed", "raise"])
def test_newer_failure_invalidates_shared_success_before_old_waiter(processes, failure):
    rpc = processes.remote(["active", failure, "active"], block_first=True)
    leader = processes.start()
    assert rpc.first_entered.wait(5)
    entered, gate = processes.context.Event(), processes.context.Event()
    delayed = processes.start(entered=entered, gate=gate)
    assert entered.wait(5)
    rpc.release_first.set()
    _assert_success([processes.finish(leader)], 1)
    _, newer = processes.finish(processes.start())
    assert newer == ([(None, "RuntimeError")] if failure == "raise" else [(False, None)])
    gate.set()
    _assert_success([processes.finish(delayed)], 1)
    assert rpc.counts == (3, 0)


@pytest.mark.parametrize("failure", ["failed", "raise"])
def test_failed_leader_does_not_publish_success(processes, failure):
    rpc = processes.remote([failure, "active"])
    barrier = processes.context.Barrier(2)
    workers = [processes.start(barrier=barrier) for _ in range(2)]
    values = [processes.finish(worker)[1][0] for worker in workers]
    assert (True, None) in values
    assert ((None, "RuntimeError") if failure == "raise" else (False, None)) in values
    assert rpc.counts == (2, 0)


@pytest.mark.parametrize("lock_mode", ["legacy", "oauth"])
def test_child_resets_parent_owned_thread_lock(processes, lock_mode):
    # Hold only the local thread lock, leaving the shared process gate available.
    # No elapsed-time assertion: the inherited locked object must not be used.
    parent_lock = processes.lock._status_thread_lock
    parent_lock.acquire()
    try:
        _assert_success([processes.finish(processes.start(lock_mode=lock_mode))], 1)
        assert parent_lock.locked(), "child released the parent's owned local lock"
    finally:
        parent_lock.release()


def test_child_preserves_parent_owned_process_gate(processes):
    gate = processes.lock._status_multiprocessing_lock
    gate.acquire()
    try:
        _assert_success([processes.finish(processes.start(lock_mode="process-probe"))], 1)
    finally:
        gate.release()


def test_shared_cache_hit_does_not_extend_completion_time(processes):
    rpc = processes.remote(["active", "active"], block_first=True)
    leader = processes.start(clock=[0.0, 1.0])
    assert rpc.first_entered.wait(5)
    old_entered, old_gate = processes.context.Event(), processes.context.Event()
    older = processes.start(entered=old_entered, gate=old_gate, clock=[0.0, 3.0])
    assert old_entered.wait(5)
    rpc.release_first.set()
    _assert_success([processes.finish(leader)], 1)
    new_entered, new_gate = processes.context.Event(), processes.context.Event()
    newer = processes.start(entered=new_entered, gate=new_gate, clock=[2.0, 4.0])
    assert new_entered.wait(5)
    old_gate.set()
    _assert_success([processes.finish(older)], 1)
    new_gate.set()
    _assert_success([processes.finish(newer)], 1)
    assert rpc.counts == (2, 0)
