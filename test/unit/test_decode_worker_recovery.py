"""Recovery uses real worker processes and existing serialized Thrift fixtures."""

import gc
import logging
import os
import signal
import sys
import threading
import time
import weakref

import pytest

from test.unit.test_parallel_result_decode import (
    alive, chunk, deadline, decimal_chunk, lease, runtime_module, until,
)
from e6data_python_connector.result_batch import decode_result_batches


class Envelope(list):
    """A weak-referenceable envelope used only to inspect object ownership."""


@pytest.mark.parametrize('failure', ['exit', 'pipe'])
def test_failed_worker_recovers_complete_envelope_without_replacement(lease, failure, caplog):
    payloads = [chunk(['first', 'second']), chunk(['third']), chunk(['fourth'])]
    pids = lease.worker_pids
    if failure == 'exit':
        os.kill(pids[0], signal.SIGKILL)
        until(lambda: lease._runtime.slots[0].process.exitcode is not None)
    else:
        lease._runtime.slots[0].channel.close()
    with caplog.at_level(logging.DEBUG):
        actual = lease.decode(['value'], payloads, deadline(), lease.new_owner())
    assert actual == [[['first'], ['second']], [['third']], [['fourth']]]
    assert lease.worker_pids == pids
    assert lease._runtime.stopped.is_set()
    assert not any(alive(pid) for pid in pids)
    assert 'recovery=complete' in caplog.text
    assert 'first' not in caplog.text and 'fourth' not in caplog.text
    assert lease.decode(['value'], [chunk(['later']), chunk(['query'])], deadline(),
                        lease.new_owner()) == [[['later']], [['query']]]


def test_failed_runtime_releases_envelope_while_lease_stays_open(lease):
    def fail():
        payloads = Envelope([chunk(['valid']), b'invalid thrift bytes'])
        reference = weakref.ref(payloads)
        try:
            lease.decode(['value'], payloads, deadline(), lease.new_owner())
        except ValueError:
            pass
        else:
            pytest.fail('Malformed data must remain fatal')
        return reference

    reference = fail()
    assert lease._runtime.stopped.wait(3)
    gc.collect()
    assert reference() is None
    assert lease._runtime.error.__traceback__ is None
    assert lease._runtime.error.__cause__ is None
    assert lease._runtime.error.__context__ is None
    for slot in lease._runtime.slots:
        assert slot.jobs.empty()
        assert slot.result is None
        assert slot.error is None or slot.error.__traceback__ is None


def test_cleanup_releases_successful_slot_results(lease):
    # Submit to the real worker outside the coordinator so cleanup must own the
    # completed output and release it without a consuming decode call.
    slot = lease._runtime.slots[0]
    slot.jobs.put_nowait((99, 0, (0,), chunk(['retained-row'])))
    until(lambda: slot.result is not None)
    lease._runtime.quarantine(runtime_module().ResultDecodeError('Stopped.'), deadline())
    assert lease._runtime.stopped.wait(3)
    assert slot.result is None
    assert all(slot.jobs.empty() for slot in lease._runtime.slots)


@pytest.mark.parametrize('stage', ['cleanup', 'recovery'])
@pytest.mark.parametrize('token_owner', [True, False])
def test_cancellation_after_worker_failure_prevents_recovery_publication(lease, stage, token_owner):
    module = runtime_module()
    owner = lease.new_owner() if token_owner else object()
    os.kill(lease.worker_pids[0], signal.SIGKILL)
    until(lambda: lease._runtime.slots[0].process.exitcode is not None)
    reached = threading.Event()
    previous = threading.gettrace() if stage == 'cleanup' else sys.gettrace()
    target = module._Runtime._cleanup if stage == 'cleanup' else decode_result_batches

    def cancel_at_stage(frame, event, arg):
        if event == 'call' and frame.f_code is target.__code__:
            reached.set()
            lease.cancel(owner)
        return cancel_at_stage

    settrace = threading.settrace if stage == 'cleanup' else sys.settrace
    settrace(cancel_at_stage)
    try:
        with pytest.raises(module.ResultDecodeError, match='cancelled'):
            lease.decode(['value'], [chunk(['one']), chunk(['two'])], deadline(), owner)
    finally:
        settrace(previous)
    assert reached.wait(2)
    assert lease._runtime.stopped.wait(3)


def test_recovery_keeps_original_deadline_after_sequential_decode(lease):
    os.kill(lease.worker_pids[0], signal.SIGKILL)
    until(lambda: lease._runtime.slots[0].process.exitcode is not None)
    end = deadline(.5)
    previous = sys.gettrace()
    reached = []

    def exhaust_budget(frame, event, arg):
        if event == 'return' and frame.f_code is decode_result_batches.__code__:
            reached.append(True)
            time.sleep(max(0, end - time.monotonic()) + .01)
        return exhaust_budget

    sys.settrace(exhaust_budget)
    try:
        with pytest.raises(TimeoutError):
            lease.decode(['value'], [chunk(['one']), chunk(['two'])], end, lease.new_owner())
    finally:
        sys.settrace(previous)
    assert reached == [True]


def test_recovery_preserves_original_sequential_error(lease):
    payloads = [chunk(['valid']), b'invalid thrift bytes']
    with pytest.raises(Exception) as expected:
        decode_result_batches(['value'], payloads)
    os.kill(lease.worker_pids[0], signal.SIGKILL)
    until(lambda: lease._runtime.slots[0].process.exitcode is not None)
    with pytest.raises(type(expected.value)) as actual:
        lease.decode(['value'], payloads, deadline(), lease.new_owner())
    assert str(actual.value) == str(expected.value)


def test_recovery_matches_sequential_decimal_values_and_sticky_flags(lease):
    import decimal
    payloads = [decimal_chunk(12345678901234567890123456789012345678, 2),
                decimal_chunk(12345, 2)]
    with decimal.localcontext() as context:
        context.clear_flags()
        context.flags[decimal.Clamped] = True
        expected = decode_result_batches(['value'], payloads)
        expected_flags = dict(context.flags)
        context.clear_flags()
        context.flags[decimal.Clamped] = True
        original_flags = dict(context.flags)
        os.kill(lease.worker_pids[1], signal.SIGSTOP)
        killed = []
        retried = []
        previous = sys.gettrace()

        def kill_after_partial_result(frame, event, arg):
            if (event == 'line' and frame.f_code is runtime_module()._Runtime._parallel.__code__
                    and not killed and any(frame.f_locals.get('output', []))):
                assert context.flags[decimal.Inexact]
                killed.append(True)
                os.kill(lease.worker_pids[1], signal.SIGKILL)
            if event == 'call' and frame.f_code is decode_result_batches.__code__:
                assert dict(context.flags) == original_flags
                retried.append(True)
            return kill_after_partial_result

        sys.settrace(kill_after_partial_result)
        try:
            actual = lease.decode(['value'], payloads, deadline(), lease.new_owner())
        finally:
            sys.settrace(previous)
        assert killed == retried == [True]
        assert actual == expected
        assert dict(context.flags) == expected_flags
