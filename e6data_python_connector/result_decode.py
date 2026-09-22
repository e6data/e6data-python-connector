"""Bounded, process-wide decoding of independent V2 result chunks.

There are two spawned workers, two blocking I/O threads, and one admitted
parallel envelope. Busy or quarantined runtimes use the sequential oracle.
A failed runtime is retained until its final lease and all resources retire.
"""

import atexit
import decimal
import logging
import multiprocessing
from multiprocessing.connection import wait
import os
import platform
import queue
import sys
import threading
import time

from e6data_python_connector.result_batch import decode_result_batches
from e6data_python_connector.result_decode_worker import (
    WORKER_PREFIX, decode_worker, is_decode_worker, decimal_context_signature,
)

_logger = logging.getLogger(__name__)
_registry_lock = threading.Lock()
_registry_pid = os.getpid()
_runtime = None


class ResultDecodeError(ValueError):
    """A worker failed before a complete envelope could be published."""


class _DecodeOwner:
    """One lease's cancellation latch for one envelope, with identity semantics."""

    def __init__(self, lease):
        self.lease = lease
        self.cancelled = False


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Result decoding deadline exceeded.')
    return remaining


def validate_decode_runtime():
    """Reject unsupported opt-in runtimes before a connection opens a channel."""
    if platform.python_implementation() != 'CPython' or not (3, 11) <= sys.version_info[:2] <= (3, 13):
        raise ValueError('V2 parallel decoding requires CPython 3.11 through 3.13.')
    gil_enabled = getattr(sys, '_is_gil_enabled', None)
    if gil_enabled is not None and not gil_enabled():
        raise ValueError('V2 parallel decoding requires a GIL-enabled CPython runtime.')


def _check_environment():
    validate_decode_runtime()
    main = sys.modules.get('__main__')
    main_file = getattr(main, '__file__', None)
    if (is_decode_worker() or multiprocessing.current_process().daemon or
            getattr(sys, 'frozen', False) or not main_file or
            main_file.startswith('<') or not os.path.isfile(main_file)):
        raise ValueError('V2 parallel decoding requires an import-safe main file guarded by if __name__ == "__main__"; interactive, daemon, frozen, and decode-worker applications are unsupported.')


class _Slot:
    def __init__(self, runtime, index):
        self.runtime = runtime
        self.index = index
        self.process = None
        self.pid = None
        self.channel = None
        self.thread = None
        self.jobs = queue.Queue(maxsize=1)
        self.ready = False
        self.decimal_context = None
        self.result = None
        self.error = None

    def io(self):
        try:
            ready = self.channel.recv()
            if not isinstance(ready, tuple) or len(ready) != 2 or ready[0] != 'ready':
                raise ResultDecodeError('Decode worker sent an invalid startup handshake.')
            with self.runtime.condition:
                self.decimal_context = ready[1]
                self.ready = True
                self.runtime.condition.notify_all()
            # A full slot can reject cleanup's shutdown token. After the
            # queued job finishes, the runtime state must also stop this loop
            # so it cannot wait forever on the now-empty queue.
            while self.runtime.state in ('starting', 'ready'):
                job = self.jobs.get()
                self.channel.send(job)
                if job is None:
                    return
                result = self.channel.recv()
                with self.runtime.condition:
                    self.result = result
                    self.runtime.condition.notify_all()
        except (Exception, SystemExit) as error:
            with self.runtime.condition:
                self.error = error
                self.runtime.condition.notify_all()


class _Runtime:
    def __init__(self):
        self.condition = threading.Condition()
        self.slots = []
        self.leases = set()
        self.state = 'starting'
        self.error = None
        self._active = None
        self._sequence = 0
        self.cleanup_thread = None
        self.stopped = threading.Event()
        self.startup_done = threading.Event()
        self.startup_error = None

    @property
    def pids(self):
        return tuple(slot.pid for slot in self.slots if slot.pid is not None)

    def _worker_failed(self):
        for slot in self.slots:
            if slot.error is not None:
                return True
            if slot.process is not None and slot.pid is not None:
                try:
                    if wait([slot.process.sentinel], timeout=0):
                        return True
                except (ValueError, OSError):
                    return True
        return False

    def start(self, deadline):
        try:
            context = multiprocessing.get_context('spawn')
            for index in range(2):
                _remaining(deadline)
                with self.condition:
                    if self.error is not None:
                        raise self.error
                    if self.state != 'starting':
                        raise ResultDecodeError('Decoder closed during worker startup.')
                slot = _Slot(self, index)
                self.slots.append(slot)
                parent, child = context.Pipe(duplex=True)
                slot.channel = parent
                slot.process = context.Process(target=decode_worker, args=(child,),
                                               name=WORKER_PREFIX + str(index))
                try:
                    slot.process.start()
                    slot.pid = slot.process.pid
                finally:
                    child.close()
                slot.thread = threading.Thread(target=slot.io,
                                               name=WORKER_PREFIX + 'io-' + str(index), daemon=True)
                slot.thread.start()
            with self.condition:
                while not all(slot.ready for slot in self.slots):
                    if self.error is not None:
                        raise self.error
                    if self._worker_failed():
                        raise ResultDecodeError('Decode worker failed before startup completed.')
                    self.condition.wait(min(.02, _remaining(deadline)))
                _remaining(deadline)
                if self.error is not None:
                    raise self.error
                if self.state != 'starting':
                    raise ResultDecodeError('Decoder closed during worker startup.')
                self.state = 'ready'
                self.startup_done.set()
                self.condition.notify_all()
        except BaseException as error:
            self.startup_error = error
            self.startup_done.set()
            self.quarantine(error, deadline)
            self.stopped.wait(max(0, deadline - time.monotonic()))
            raise

    def await_start(self, deadline):
        with self.condition:
            while not self.startup_done.is_set():
                self.condition.wait(min(.02, _remaining(deadline)))
            if self.startup_error is not None:
                raise self.startup_error
            # A runtime that failed after startup is usable only sequentially.

    def quarantine(self, error, deadline=None):
        with self.condition:
            if self.error is None:
                self.error = error
            self.state = 'failed'
            self.condition.notify_all()
            self._request_cleanup(deadline if deadline is not None else time.monotonic() + .5)

    def _request_cleanup(self, deadline):
        if self.cleanup_thread is None:
            self.cleanup_thread = threading.Thread(target=self._cleanup, args=(deadline,),
                                                   name=WORKER_PREFIX + 'cleanup', daemon=True)
            self.cleanup_thread.start()

    def _cleanup(self, deadline):
        # Startup owns the slot list until it finishes or observes cancellation.
        # Waiting here cannot extend the caller's separate cleanup deadline.
        self.startup_done.wait()
        # Ask idle workers to exit before escalation. Busy workers remain owned
        # until termination unblocks the I/O thread's send or receive.
        for slot in self.slots:
            if slot.thread is not None and slot.thread.is_alive():
                try:
                    slot.jobs.put_nowait(None)
                except queue.Full:
                    pass
        processes = [slot.process for slot in self.slots if slot.pid is not None]
        grace = min(deadline, time.monotonic() + .05)
        for process in processes:
            process.join(timeout=max(0, grace - time.monotonic()))
        for process in processes:
            if process.is_alive():
                process.terminate()
        terminate_end = min(deadline, time.monotonic() + .1)
        for process in processes:
            process.join(timeout=max(0, terminate_end - time.monotonic()))
        for process in processes:
            if process.is_alive():
                process.kill()
        for process in processes:
            process.join(timeout=max(0, deadline - time.monotonic()))
        # This single daemon reaper retains the quarantined runtime even if the
        # caller's bounded cleanup budget expired. No replacement can overlap it.
        while any(process.is_alive() for process in processes):
            for process in processes:
                process.join(timeout=.05)
        for slot in self.slots:
            if slot.channel is not None:
                slot.channel.close()
            if slot.thread is not None:
                slot.thread.join()
            if slot.process is not None:
                slot.process.close()
        with self.condition:
            self.state = 'closed'
            self.stopped.set()
            self.condition.notify_all()
        _logger.debug('result_decode cleanup=stopped workers=%d', len(processes))

    def cancel(self, lease, owner=None):
        with self.condition:
            if isinstance(owner, _DecodeOwner):
                if owner.lease is not lease:
                    return
                owner.cancelled = True
            active = self._active
            if active is not None and active[0] is lease and (owner is None or active[1] is owner):
                self.quarantine(ResultDecodeError('Result decoding was cancelled.'))

    def release(self, lease, deadline, wait=True):
        with self.condition:
            self.cancel(lease)
            self.leases.discard(lease)
            if not self.leases:
                if self.state not in ('failed', 'closed'):
                    self.state = 'closing'
                self._request_cleanup(deadline)
                closing = True
            else:
                closing = False
        if closing and wait:
            self.stopped.wait(max(0, deadline - time.monotonic()))
            _logger.debug('result_decode cleanup=%s workers=%d',
                          'stopped' if self.stopped.is_set() else 'pending', len(self.pids))

    def decode(self, lease, columns, payloads, deadline, owner):
        started = time.monotonic()
        mode, fallback = 'sequential', 'single_chunk'
        admitted = False
        try:
            with self.condition:
                _remaining(deadline)
                if lease._closed:
                    raise ValueError('Decoder lease is closed.')
                if isinstance(owner, _DecodeOwner):
                    if owner.lease is not lease:
                        raise ValueError('Decode owner belongs to another lease.')
                    if owner.cancelled:
                        raise ResultDecodeError('Result decoding was cancelled.')
                if len(payloads) > 1:
                    if self.state != 'ready':
                        fallback = 'unavailable'
                    elif self._active is not None:
                        fallback = 'capacity'
                    elif any(slot.decimal_context != decimal_context_signature() for slot in self.slots):
                        fallback = 'decimal_context'
                    else:
                        self._active = (lease, owner)
                        self._sequence += 1
                        token = self._sequence
                        admitted = True
                        mode, fallback = 'parallel', 'none'
            if not admitted:
                chunks = decode_result_batches(columns, payloads)
                _remaining(deadline)
                return chunks
            try:
                return self._parallel(columns, payloads, deadline, token)
            except BaseException as error:
                self.quarantine(error, deadline)
                raise
        finally:
            if admitted:
                with self.condition:
                    self._active = None
                    self.condition.notify_all()
            _logger.debug('result_decode mode=%s wall_ms=%.3f chunks=%d workers=%d fallback=%s cleanup=%s',
                          mode, (time.monotonic() - started) * 1000, len(payloads),
                          2 if admitted else 0, fallback, self.state)

    def _parallel(self, columns, payloads, deadline, token):
        # The existing vector decoder uses only the number of columns. Plain
        # positions preserve that contract without serializing FieldInfo objects.
        metadata = tuple(range(len(columns)))
        context = decimal.getcontext()
        decimal_signals = {signal.__name__: signal for signal in context.flags}
        output = [None] * len(payloads)
        pending = {}
        next_index = 0
        with self.condition:
            while pending or next_index < len(payloads):
                _remaining(deadline)
                if self.error is not None:
                    raise self.error
                if self._worker_failed():
                    raise ResultDecodeError('Decode worker exited before returning a complete result.')
                for slot in self.slots:
                    if slot.index in pending and slot.result is not None:
                        result, slot.result = slot.result, None
                        index = pending.pop(slot.index)
                        if (not isinstance(result, tuple) or len(result) != 5 or
                                result[1] != token or result[2] != index):
                            raise ResultDecodeError('Decode worker returned an invalid job result.')
                        flags = result[4]
                        if not isinstance(flags, tuple) or any(name not in decimal_signals for name in flags):
                            raise ResultDecodeError('Decode worker returned invalid decimal flags.')
                        for name in flags:
                            context.flags[decimal_signals[name]] = True
                        if result[0] == 'error':
                            raise ResultDecodeError('Result chunk decoding failed in worker (%s).' % result[3])
                        if result[0] != 'result':
                            raise ResultDecodeError('Decode worker returned an invalid result kind.')
                        output[index] = result[3]
                    if slot.index not in pending and next_index < len(payloads):
                        index = next_index
                        next_index += 1
                        pending[slot.index] = index
                        slot.jobs.put_nowait((token, index, metadata, payloads[index]))
                if pending:
                    self.condition.wait(min(.02, _remaining(deadline)))
            _remaining(deadline)
        return [rows for rows in output if rows]


class DecoderLease:
    """One connection's ownership of the shared, bounded process decoder."""

    def __init__(self):
        self._pid = os.getpid()
        self._runtime = None
        self._closed = False
        self._lock = threading.Lock()

    def _check(self):
        if self._pid != os.getpid():
            raise ValueError('Decoder lease belongs to another process.')
        if self._closed:
            raise ValueError('Decoder lease is closed.')

    def start(self, deadline):
        global _runtime, _registry_pid, _registry_lock
        self._check()
        _remaining(deadline)
        _check_environment()
        if self._runtime is not None:
            self._runtime.await_start(deadline)
            return
        # A new connection after fork must never use an inherited Python lock.
        if _registry_pid != os.getpid():
            _registry_pid = os.getpid()
            _registry_lock = threading.Lock()
            _runtime = None
        with self._lock:
            self._check()
            with _registry_lock:
                if self._runtime is not None:
                    runtime, create = self._runtime, False
                else:
                    create = _runtime is None or (not _runtime.leases and _runtime.stopped.is_set())
                    if create:
                        _runtime = _Runtime()
                    runtime = self._runtime = _runtime
                    with runtime.condition:
                        runtime.leases.add(self)
        if create:
            runtime.start(deadline)
        else:
            runtime.await_start(deadline)

    @property
    def worker_pids(self):
        return self._runtime.pids if self._runtime is not None else ()

    def decode(self, columns, payloads, deadline, owner):
        self._check()
        if self._runtime is None:
            raise ValueError('Decoder lease must start before decoding.')
        return self._runtime.decode(self, columns, payloads, deadline, owner)

    def new_owner(self):
        self._check()
        return _DecodeOwner(self)

    def cancel(self, owner):
        if self._pid != os.getpid():
            return
        with self._lock:
            runtime = self._runtime
            if runtime is None:
                if isinstance(owner, _DecodeOwner) and owner.lease is self:
                    owner.cancelled = True
                return
        runtime.cancel(self, owner)

    def retire(self, deadline):
        """Release ownership without waiting; the runtime owns its cleanup thread."""
        if self._pid != os.getpid():
            return
        with self._lock:
            if self._closed:
                return
            self._closed = True
            runtime = self._runtime
        if runtime is not None:
            runtime.release(self, deadline, wait=False)

    @property
    def cleanup_pending(self):
        runtime = self._runtime
        return (self._closed and runtime is not None and runtime.state in ('closing', 'failed')
                and not runtime.stopped.is_set())

    def close(self, deadline):
        self.retire(deadline)
        if self._pid == os.getpid() and self.cleanup_pending:
            self._runtime.stopped.wait(max(0, deadline - time.monotonic()))


def _shutdown():
    runtime = _runtime
    if _registry_pid == os.getpid() and runtime is not None and not runtime.stopped.is_set():
        runtime.quarantine(ResultDecodeError('Interpreter shutdown.'), time.monotonic() + .5)
        runtime.stopped.wait(.5)


atexit.register(_shutdown)
