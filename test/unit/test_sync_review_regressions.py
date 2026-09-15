"""Real local locks and fork capacity regressions, with no transport doubles."""
import os
import subprocess
import sys
import threading
import time

import pytest

from e6data_python_connector import Connection
from e6data_python_connector import e6data_grpc as engine


@pytest.mark.parametrize('surface', ['cursor', 'connection'])
def test_cleanup_routing_lock_wait_respects_total_budget(surface):
    connection = Connection(host='localhost', port=1, access_token='unit-input', require_fastbinary=False)
    cursor = connection.cursor()
    connection.close()  # Any accidental dispatch fails locally on the real closed channel.
    cursor._query_id, cursor._engine_ip = 'unit-query', 'unit-planner'
    engine._strategy_lock.acquire()
    timer = threading.Timer(.20, engine._strategy_lock.release)
    timer.start()
    started = time.monotonic()
    error = None
    try:
        try:
            if surface == 'cursor':
                cursor.clear(timeout=.02)
            else:
                connection.clear('unit-query', 'unit-planner', timeout=.02)
        except Exception as caught:
            error = caught
        elapsed = time.monotonic() - started
    finally:
        timer.join()
    assert isinstance(error, TimeoutError)
    assert elapsed < .12, 'Cleanup exceeded routing admission budget: {}'.format(elapsed)
    assert cursor._query_id == 'unit-query'
    assert cursor._engine_ip == 'unit-planner'


@pytest.mark.skipif(not hasattr(os, 'fork'), reason='POSIX fork regression')
def test_new_child_provider_has_fresh_capacity_after_fork():
    # A fresh subprocess prevents forking the pytest/gRPC runtime's helper threads.
    result = subprocess.run([sys.executable, '-c', '''
import os
from e6data_python_connector import oauth
slots = oauth._EXCHANGE_SLOTS
for _ in range(4):
    assert slots.acquire(blocking=False)
pid = os.fork()
if pid == 0:
    provider = oauth.ClientCredentialsTokenProvider('https://localhost/token', 'unit-id', 'unit-input')
    acquired = [oauth._EXCHANGE_SLOTS.acquire(blocking=False) for _ in range(4)]
    exhausted = not oauth._EXCHANGE_SLOTS.acquire(blocking=False)
    os._exit(0 if all(acquired) and exhausted else 1)
_, status = os.waitpid(pid, 0)
assert not slots.acquire(blocking=False), 'Child reset modified parent capacity'
for _ in range(4):
    slots.release()
assert os.waitstatus_to_exitcode(status) == 0, 'Child inherited permanently occupied exchange slots'
'''], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_post_rpc_bookkeeping_lock_is_deadline_bound():
    # This is production routing state, not a server response double.
    engine._register_query_strategy('unit-complete', 'blue')
    engine._strategy_lock.acquire()
    timer = threading.Timer(.20, engine._strategy_lock.release)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            engine._cleanup_query_strategy('unit-complete', deadline=started + .02)
        assert time.monotonic() - started < .12
    finally:
        timer.join()
    assert engine._get_query_strategy('unit-complete') == 'blue'
    engine._cleanup_query_strategy('unit-complete')


@pytest.mark.parametrize('operation', [
    lambda deadline: engine._set_pending_strategy('green', deadline=deadline),
    lambda deadline: engine._apply_pending_strategy(deadline=deadline),
])
def test_cleanup_strategy_transition_admission_uses_remaining_budget(operation):
    engine._strategy_lock.acquire()
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            operation(started + .02)
        assert time.monotonic() - started < .12
    finally:
        engine._strategy_lock.release()


def test_atomic_cleanup_timeout_keeps_route():
    engine._register_query_strategy('unit-atomic', 'blue')
    engine._strategy_lock.acquire()
    try:
        with pytest.raises(TimeoutError):
            engine._finish_query_cleanup('unit-atomic', 'green', time.monotonic() + .02)
    finally:
        engine._strategy_lock.release()
    assert engine._get_query_strategy('unit-atomic') == 'blue'
    engine._cleanup_query_strategy('unit-atomic')
