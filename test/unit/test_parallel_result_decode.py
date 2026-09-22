"""Real spawned-process contracts for the bounded V2 decoder."""
import importlib
import importlib.util
import logging
import multiprocessing
import os
import signal
import threading
import time
from pathlib import Path

import pytest
from thrift.protocol.TBinaryProtocol import TBinaryProtocol
from thrift.transport.TTransport import TMemoryBuffer
from e6data_python_connector.e6x_vector import ttypes as wire
from e6data_python_connector.result_batch import decode_result_batches


def runtime_module():
    name = 'e6data_python_connector.result_decode'
    assert importlib.util.find_spec(name) is not None, 'Bounded decoder runtime is missing'
    return importlib.import_module(name)


def deadline(seconds=10):
    return time.monotonic() + seconds


def chunk(values):
    vector = wire.Vector(len(values), wire.VectorType.STRING, [False] * len(values),
                         wire.Data(varcharData=wire.VarcharData(values)))
    transport = TMemoryBuffer()
    wire.Chunk(len(values), [vector]).write(TBinaryProtocol(transport))
    return transport.getvalue()


def empty_chunk():
    transport = TMemoryBuffer()
    wire.Chunk(0, []).write(TBinaryProtocol(transport))
    return transport.getvalue()


def until(predicate, seconds=5):
    end = deadline(seconds)
    while not predicate():
        assert time.monotonic() < end, 'Expected state did not settle'
        time.sleep(.01)


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.fixture
def lease():
    lease = runtime_module().DecoderLease()
    lease.start(deadline())
    try:
        yield lease
    finally:
        lease.close(deadline())
        until(lambda: not any(alive(pid) for pid in lease.worker_pids))


def test_two_workers_are_shared_and_last_close_reaps_them():
    module = runtime_module()
    first, second = module.DecoderLease(), module.DecoderLease()
    try:
        first.start(deadline())
        second.start(deadline())
        pids = first.worker_pids
        assert len(pids) == 2 and len(set(pids)) == 2
        assert pids == second.worker_pids
        first.close(deadline())
        assert all(alive(pid) for pid in pids)
        assert second.decode(['value'], [chunk(['a']), chunk(['b'])], deadline(), object()) == [[['a']], [['b']]]
    finally:
        first.close(deadline())
        second.close(deadline())
    assert not any(alive(pid) for pid in pids)


def test_parallel_decode_preserves_order_and_skips_empty_chunks(lease, caplog):
    payloads = [chunk(['first', 'second']), empty_chunk(), chunk(['third']), chunk(['fourth'])]
    with caplog.at_level(logging.DEBUG):
        result = lease.decode(['value'], payloads, deadline(), object())
    assert result == decode_result_batches(['value'], payloads)
    assert 'mode=parallel' in caplog.text
    assert 'first' not in caplog.text


@pytest.mark.parametrize('position', [0, 1, 2])
def test_malformed_first_middle_or_last_fails_entire_envelope(lease, position):
    payloads = [chunk(['one']), chunk(['two']), chunk(['three'])]
    payloads[position] = b'invalid thrift bytes'
    with pytest.raises(ValueError):
        lease.decode(['value'], payloads, deadline(), object())
    assert lease.decode(['value'], [chunk(['after']), chunk(['failure'])], deadline(), object()) == [[['after']], [['failure']]]


def test_single_and_empty_envelopes_use_sequential_mode(lease, caplog):
    with caplog.at_level(logging.DEBUG):
        assert lease.decode(['value'], [chunk(['one'])], deadline(), object()) == [[['one']]]
        assert lease.decode(['value'], [], deadline(), object()) == []
    assert 'mode=sequential' in caplog.text
    assert 'fallback=single_chunk' in caplog.text


def stalled_decode(lease, seconds=10, payloads=None):
    for pid in lease.worker_pids:
        os.kill(pid, signal.SIGSTOP)
    owner = object()
    errors = []
    def run():
        try:
            lease.decode(['value'], payloads if payloads is not None else [chunk(['one']), chunk(['two'])], deadline(seconds), owner)
        except BaseException as error:
            errors.append(error)
    thread = threading.Thread(target=run)
    thread.start()
    until(lambda: lease._runtime._active is not None)
    return owner, errors, thread


def test_slot_saturation_uses_sequential_without_queue(lease, caplog):
    owner, errors, thread = stalled_decode(lease)
    try:
        with caplog.at_level(logging.DEBUG):
            assert lease.decode(['value'], [chunk(['free']), chunk(['slot'])], deadline(1), object()) == [[['free']], [['slot']]]
        assert 'fallback=capacity' in caplog.text
    finally:
        for pid in lease.worker_pids:
            os.kill(pid, signal.SIGCONT)
        thread.join(3)
    assert not thread.is_alive() and not errors


def test_cancel_is_nonblocking_and_quarantines_without_replacement(lease, caplog):
    owner, errors, thread = stalled_decode(lease)
    pids = lease.worker_pids
    start = time.monotonic()
    lease.cancel(owner)
    assert time.monotonic() - start < .1
    thread.join(2)
    assert not thread.is_alive() and len(errors) == 1
    assert isinstance(errors[0], ValueError)
    with caplog.at_level(logging.DEBUG):
        assert lease.decode(['value'], [chunk(['safe']), chunk(['fallback'])], deadline(), object()) == [[['safe']], [['fallback']]]
    assert 'fallback=unavailable' in caplog.text
    assert lease.worker_pids == pids
    until(lambda: not any(alive(pid) for pid in pids))


@pytest.mark.parametrize("count", [1, 2])
def test_cancelled_envelope_token_rejects_work_before_admission(lease, count):
    assert callable(getattr(lease, "new_owner", None)), "per-envelope cancellation owner is missing"
    owner = lease.new_owner()
    before = lease._runtime._sequence
    lease.cancel(owner)
    with pytest.raises(runtime_module().ResultDecodeError, match="cancelled"):
        lease.decode(['value'], [chunk(['value'])] * count, deadline(), owner)
    assert lease._runtime._sequence == before
    assert lease._runtime.state == 'ready'
    assert lease.decode(['value'], [chunk(['next']), chunk(['query'])], deadline(),
                        lease.new_owner()) == [[['next']], [['query']]]


def test_envelope_cancel_token_is_bound_to_its_lease(lease):
    assert callable(getattr(lease, "new_owner", None)), "per-envelope cancellation owner is missing"
    other = runtime_module().DecoderLease()
    other.start(deadline())
    try:
        owner = lease.new_owner()
        other.cancel(owner)
        with pytest.raises(ValueError, match="another lease"):
            other.decode(['value'], [chunk(['wrong'])], deadline(), owner)
        assert lease.decode(['value'], [chunk(['own']), chunk(['lease'])], deadline(),
                            owner) == [[['own']], [['lease']]]
    finally:
        other.close(deadline())


def test_retirement_stays_pending_if_another_lease_registers_during_cleanup(lease):
    other = runtime_module().DecoderLease()
    pids = lease.worker_pids
    for pid in pids:
        os.kill(pid, signal.SIGSTOP)
    try:
        lease.retire(deadline(1))
        other.start(deadline())
        assert lease.cleanup_pending or lease._runtime.stopped.is_set()
    finally:
        for pid in pids:
            try:
                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
        other.close(deadline())


def test_wrong_owner_cannot_cancel_another_query(lease):
    owner, errors, thread = stalled_decode(lease)
    lease.cancel(object())
    assert thread.is_alive()
    for pid in lease.worker_pids:
        os.kill(pid, signal.SIGCONT)
    thread.join(3)
    assert not errors and not thread.is_alive()


def test_lost_result_hits_deadline_and_reaps_workers(lease):
    owner, errors, thread = stalled_decode(lease, .2)
    thread.join(2)
    assert not thread.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], TimeoutError)
    until(lambda: not any(alive(pid) for pid in lease.worker_pids))


def test_crash_is_detected_without_waiting_for_operation_deadline(lease):
    owner, errors, thread = stalled_decode(lease)
    os.kill(lease.worker_pids[0], signal.SIGKILL)
    thread.join(2)
    assert not thread.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], ValueError)
    until(lambda: not any(alive(pid) for pid in lease.worker_pids))


def test_close_cancels_active_decode_and_is_bounded(lease):
    owner, errors, thread = stalled_decode(lease)
    started = time.monotonic()
    lease.close(deadline(.3))
    assert time.monotonic() - started < .6
    thread.join(2)
    assert not thread.is_alive() and errors
    until(lambda: not any(alive(pid) for pid in lease.worker_pids))
    with pytest.raises(ValueError, match='closed'):
        lease.decode(['value'], [chunk(['closed'])], deadline(), object())


def test_expired_start_does_not_create_workers():
    lease = runtime_module().DecoderLease()
    with pytest.raises(TimeoutError):
        lease.start(time.monotonic() - 1)
    lease.close(deadline())
    assert not lease.worker_pids


@pytest.mark.filterwarnings('ignore:This process.*is multi-threaded.*:DeprecationWarning')
def test_forked_lease_rejects_work_without_touching_parent_workers(lease):
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            lease.start(deadline())
        except ValueError as error:
            os.write(write_fd, str(error).encode())
        finally:
            os._exit(0)
    os.close(write_fd)
    message = os.read(read_fd, 4096)
    os.close(read_fd)
    os.waitpid(pid, 0)
    assert b'process' in message
    assert lease.decode(['value'], [chunk(['parent'])], deadline(), object()) == [[['parent']]]


def test_repeated_clean_and_forced_shutdown_has_no_named_semaphore_growth():
    module = runtime_module()
    before = set(Path('/dev/shm').glob('sem.*'))
    for force in (False, True, False):
        lease = module.DecoderLease()
        lease.start(deadline())
        pids = lease.worker_pids
        if force:
            owner, errors, thread = stalled_decode(lease)
            lease.cancel(owner)
            thread.join(2)
        lease.close(deadline())
        until(lambda: not any(alive(pid) for pid in pids))
    assert set(Path('/dev/shm').glob('sem.*')) == before


def test_all_supported_vector_values_cross_process_boundary(lease):
    from test_binary_decoder_contract import VECTOR_CASES
    vectors = []
    for dtype, field, cls, constant_field, constant_cls, value, expected in VECTOR_CASES:
        for constant in (False, True):
            data = wire.Data(**({constant_field: constant_cls(value)} if constant else {field: cls([value] * 3)}))
            vectors.append(wire.Vector(3, dtype, [False] if constant else [False, True, False], data, constant))
    raw = (-12345).to_bytes(16, 'big', signed=True)
    vectors.extend([
        wire.Vector(3, wire.VectorType.DECIMAL128, [False, True, False], wire.Data(decimal128Data=wire.Decimal128Data([raw] * 3, 2)), False),
        wire.Vector(3, wire.VectorType.TIMESTAMP_TZ, [False, True, False], wire.Data(timeData=wire.TimeData([0] * 3, ['+05:30'] * 3)), False),
        wire.Vector(3, wire.VectorType.NULL),
    ])
    transport = TMemoryBuffer()
    wire.Chunk(3, vectors).write(TBinaryProtocol(transport))
    payloads = [transport.getvalue()] * 3
    columns = [str(index) for index in range(len(vectors))]
    assert lease.decode(columns, payloads, deadline(), object()) == decode_result_batches(columns, payloads)


def test_unstarted_decode_and_closed_start_are_rejected():
    lease = runtime_module().DecoderLease()
    with pytest.raises(ValueError, match='start'):
        lease.decode(['value'], [], deadline(), object())
    lease.cancel(object())
    lease.close(deadline())
    lease.close(deadline())
    with pytest.raises(ValueError, match='closed'):
        lease.start(deadline())


@pytest.mark.parametrize('scenario', ['partial_start', 'startup_timeout', 'close_during_start', 'daemon', 'interactive'])
def test_real_bootstrap_failures_reap_resources(scenario):
    import subprocess
    import sys
    helper = Path(__file__).with_name('parallel_decode_probe.py')
    command = [sys.executable, str(helper), scenario]
    if scenario == 'interactive':
        command = [sys.executable, '-c', 'from e6data_python_connector.result_decode import DecoderLease; import time; DecoderLease().start(time.monotonic()+2)']
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        assert result.returncode != 0
        assert 'import-safe main' in result.stderr
    else:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'PROBE_OK' in result.stdout


def test_ordinary_process_keeps_multiprocessing_semaphore():
    from e6data_python_connector.cluster_manager import _StatusLock
    lock = _StatusLock()
    assert type(lock._status_multiprocessing_lock).__module__ == 'multiprocessing.synchronize'


def test_deadline_expired_before_admission_does_not_quarantine(lease):
    with pytest.raises(TimeoutError):
        lease.decode(['value'], [chunk(['one']), chunk(['two'])], time.monotonic() - 1, object())
    assert lease.decode(['value'], [chunk(['next']), chunk(['query'])], deadline(), object()) == [[['next']], [['query']]]


def test_interrupt_fails_current_envelope_and_reaps_processes(lease):
    for pid in lease.worker_pids:
        os.kill(pid, signal.SIGSTOP)
    previous_handler = signal.getsignal(signal.SIGALRM)
    def interrupt(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGALRM, interrupt)
    try:
        signal.setitimer(signal.ITIMER_REAL, .1)
        with pytest.raises(KeyboardInterrupt):
            lease.decode(['value'], [chunk(['one']), chunk(['two'])], deadline(), object())
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
    until(lambda: not any(alive(pid) for pid in lease.worker_pids))


def test_runtime_validation_does_not_start_processes():
    module = runtime_module()
    before = tuple(multiprocessing.active_children())
    assert hasattr(module, 'validate_decode_runtime'), 'Constructor-side runtime validator is missing'
    module.validate_decode_runtime()
    assert tuple(multiprocessing.active_children()) == before


def test_deadline_is_observed_while_parent_send_is_blocked(lease):
    payloads = [chunk(['x' * (1024 * 1024)])] * 2
    owner, errors, thread = stalled_decode(lease, .2, payloads)
    thread.join(2)
    assert not thread.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], TimeoutError)
    until(lambda: not any(alive(pid) for pid in lease.worker_pids))


def test_concurrent_start_on_same_lease_creates_only_two_workers():
    module = runtime_module()
    lease = module.DecoderLease()
    barrier = threading.Barrier(3)
    errors = []
    def start():
        barrier.wait()
        try:
            lease.start(deadline())
        except BaseException as error:
            errors.append(error)
    threads = [threading.Thread(target=start) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    try:
        for thread in threads:
            thread.join(10)
        assert all(not thread.is_alive() for thread in threads)
        assert not errors
        assert len(lease.worker_pids) == 2
        assert len([child for child in multiprocessing.active_children() if child.name.startswith('e6-result-decode-')]) == 2
    finally:
        lease.close(deadline())


def decimal_chunk(value, scale):
    transport = TMemoryBuffer()
    raw = value.to_bytes(16, 'big', signed=True)
    vector = wire.Vector(1, wire.VectorType.DECIMAL128, [False], wire.Data(decimal128Data=wire.Decimal128Data([raw], scale)), False)
    wire.Chunk(1, [vector]).write(TBinaryProtocol(transport))
    return transport.getvalue()


def test_changed_decimal_context_preserves_caller_values_with_fallback(lease, caplog):
    import decimal
    payloads = [decimal_chunk(12345678901234567890123456789012345678, 2)] * 2
    with decimal.localcontext() as context:
        context.prec = 100
        expected = decode_result_batches(['value'], payloads)
        with caplog.at_level(logging.DEBUG):
            actual = lease.decode(['value'], payloads, deadline(), object())
        assert actual == expected
    assert 'fallback=decimal_context' in caplog.text


def test_parallel_decimal_results_preserve_sticky_caller_flags(lease):
    import decimal
    payloads = [decimal_chunk(12345678901234567890123456789012345678, 2)] * 2
    with decimal.localcontext() as context:
        context.clear_flags()
        expected = decode_result_batches(['value'], payloads)
        expected_flags = dict(context.flags)
        assert expected_flags[decimal.Inexact] and expected_flags[decimal.Rounded]
        context.clear_flags()
        actual = lease.decode(['value'], payloads, deadline(), object())
        assert actual == expected
        assert dict(context.flags) == expected_flags


def test_worker_decimal_flags_do_not_leak_between_jobs(lease):
    import decimal
    with decimal.localcontext() as context:
        lease.decode(['value'], [decimal_chunk(12345678901234567890123456789012345678, 2)] * 2, deadline(), object())
        assert context.flags[decimal.Inexact]
        context.clear_flags()
        context.flags[decimal.Clamped] = True
        lease.decode(['value'], [decimal_chunk(12345, 2)] * 2, deadline(), object())
        assert context.flags[decimal.Clamped]
        assert not context.flags[decimal.Inexact]
        assert not context.flags[decimal.Rounded]


@pytest.mark.parametrize('setting,value', [('rounding', 'ROUND_DOWN'), ('Emin', -999998), ('Emax', 999998), ('capitals', 0), ('clamp', 1)])
def test_all_decimal_arithmetic_settings_gate_parallel_admission(lease, caplog, setting, value):
    import decimal
    with decimal.localcontext() as context:
        setattr(context, setting, value)
        with caplog.at_level(logging.DEBUG):
            assert lease.decode(['value'], [decimal_chunk(12345, 2)] * 2, deadline(), object()) == decode_result_batches(['value'], [decimal_chunk(12345, 2)] * 2)
    assert 'fallback=decimal_context' in caplog.text


def test_decimal_traps_preserve_sequential_error_behavior(lease):
    import decimal
    payloads = [decimal_chunk(12345678901234567890123456789012345678, 2)] * 2
    with decimal.localcontext() as context:
        context.traps[decimal.Inexact] = True
        with pytest.raises(decimal.Inexact) as expected:
            decode_result_batches(['value'], payloads)
        with pytest.raises(type(expected.value)):
            lease.decode(['value'], payloads, deadline(), object())


def test_cleanup_reaps_io_thread_when_stop_token_meets_full_job_queue():
    """Control a real scheduling race without replacing workers or queue behavior."""
    import queue
    module = runtime_module()
    lease = module.DecoderLease()
    get_started = threading.Event()
    release_get = threading.Event()
    stop_queue_full = threading.Event()
    job_finished = threading.Event()
    first_get = [True]
    previous_trace = threading.gettrace()

    def schedule(frame, event, arg):
        # Hold worker zero's I/O thread just before its first queue read. The
        # normal coordinator can enqueue its job while worker one rejects its
        # malformed chunk. Cleanup then finds worker zero's queue full.
        if threading.current_thread().name == 'e6-result-decode-io-0':
            if event == 'call' and frame.f_code is queue.Queue.get.__code__:
                if first_get[0]:
                    first_get[0] = False
                    get_started.set()
                    release_get.wait(5)
                else:
                    job_finished.set()
            elif event == 'return' and frame.f_code is module._Slot.io.__code__:
                job_finished.set()
        if (event == 'exception' and frame.f_code is module._Runtime._cleanup.__code__
                and arg[0] is queue.Full):
            stop_queue_full.set()
            release_get.set()
            # Let the queued job finish before worker termination. Previously
            # the I/O thread then waited forever on an empty queue, because the
            # full slot had rejected its only shutdown token.
            job_finished.wait(5)
        return schedule

    threading.settrace(schedule)
    try:
        lease.start(deadline())
        assert get_started.wait(2)
        with pytest.raises(ValueError):
            lease.decode(['value'], [chunk(['valid']), b'invalid thrift bytes'], deadline(), object())
        assert stop_queue_full.wait(2), 'Controlled full-slot shutdown path was not reached'
        lease.close(deadline(.5))
        assert lease._runtime.stopped.wait(.5), 'Cleanup left an I/O thread waiting on its empty job queue'
        assert not any(alive(pid) for pid in lease.worker_pids)
    finally:
        threading.settrace(previous_trace)
        release_get.set()
        # Keep a deliberately failing RED run from leaking its daemon thread
        # into later tests after the assertion has exposed the missing wakeup.
        if lease._runtime is not None:
            for slot in lease._runtime.slots:
                try:
                    slot.jobs.put_nowait(None)
                except queue.Full:
                    pass
            lease.close(deadline())
            lease._runtime.stopped.wait(3)
