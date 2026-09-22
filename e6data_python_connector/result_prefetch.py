"""Bound retained speculative envelopes without publishing cursor state."""

import os
import logging
import threading
import time


_slots = threading.BoundedSemaphore(4)
_logger = logging.getLogger(__name__)


def _reset_child_capacity():
    global _slots
    _slots = threading.BoundedSemaphore(4)


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_reset_child_capacity)


class _Permit:
    def __init__(self, slots):
        self._slots = slots
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._released = False

    def release(self):
        if self._pid != os.getpid():
            raise RuntimeError('Prefetch permit belongs to another process.')
        with self._lock:
            if not self._released:
                self._released = True
                self._slots.release()


def reserve_prefetch():
    """Return a permit immediately, or None when four envelopes are retained."""
    slots = _slots
    if not slots.acquire(blocking=False):
        return None
    return _Permit(slots)


class PendingFetch:
    """Retain a transport outcome and old-query session until its owner takes it.

    Completion callbacks never access a cursor or connection. Retirement is
    nonblocking and keeps admission until cancellation or completion settles.
    A completed success has no expiry here; its consuming operation sets the
    deadline for decoding and publishing it.
    """

    def __init__(self, handle, permit, session_id=None, deadline=None):
        self.handle = handle
        self.deadline = deadline
        self._permit = permit
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._started = time.monotonic()
        self._elapsed = 0.0
        self._session_id = session_id
        self._settled = False
        self._retired = False
        self._taken = False
        self._response = None
        self._error = None
        handle.add_done_callback(self._complete)

    def _check_pid(self):
        if self._pid != os.getpid():
            raise RuntimeError('Pending result belongs to another process.')

    def _complete(self, handle):
        if self._pid != os.getpid():
            return
        try:
            response, error = handle.result(), None
        except BaseException as caught:
            response, error = None, caught
        with self._lock:
            if self._settled:
                return
            self._elapsed = time.monotonic() - self._started
            self._session_id = getattr(response, 'sessionId', '') or self._session_id
            self._response = None if self._retired else response
            self._error = None if self._retired else error
            self._settled = True
            retained = int(not self._retired)
            if self._retired:
                self.handle = None
            if self._retired and self._permit is not None:
                self._permit.release()
        if self._permit is not None and _logger.isEnabledFor(logging.DEBUG):
            size = response.ByteSize() if hasattr(response, 'ByteSize') else 0
            status = 'error' if error is not None else 'ok'
            _logger.debug(
                'Result prefetch completed status=%s pending_protobuf_bytes=%d retained=%d',
                status, size if retained else 0, retained,
                extra={'result_batch_prefetch_event': 'completed',
                       'result_batch_prefetch_status': status,
                       'result_batch_pending_protobuf_bytes': size if retained else 0,
                       'result_batch_prefetch_inflight': 0,
                       'result_batch_prefetch_retained': retained})

    def _capture_completed(self):
        self._check_pid()
        # asyncio schedules its callback. Owner consumption need not wait for
        # that callback's next event-loop turn after the transport has finished.
        handle = self.handle
        if handle is not None and handle.done():
            self._complete(handle)

    @property
    def settled(self):
        self._capture_completed()
        with self._lock:
            return self._settled

    @property
    def session_id(self):
        self._capture_completed()
        with self._lock:
            return self._session_id

    @property
    def elapsed(self):
        self._capture_completed()
        with self._lock:
            return self._elapsed

    def take(self):
        """Take a settled outcome once, preserving the original exception."""
        self._capture_completed()
        with self._lock:
            if not self._settled or self._taken or self._retired:
                raise RuntimeError('Pending result is not available to consume.')
            self._taken = True
            response, error = self._response, self._error
            self._response = self._error = None
            if self._permit is not None:
                self._permit.release()
        if error is not None:
            raise error
        return response

    def retire(self):
        """Discard payloads, cancel transport, and keep late cleanup identity."""
        self._check_pid()
        handle = self.handle
        with self._lock:
            first_retirement = not self._retired
            discarded = int(self._response is not None and not self._taken)
            inflight = int(not self._settled)
            self._retired = True
            self._response = None
            self._error = None
            if self._settled:
                self.handle = None
            if self._settled and self._permit is not None:
                self._permit.release()
        if first_retirement and self._permit is not None:
            _logger.debug(
                'Result prefetch retired inflight=%d discarded=%d', inflight, discarded,
                extra={'result_batch_prefetch_event': 'retired',
                       'result_batch_prefetch_inflight': inflight,
                       'result_batch_prefetch_discarded': discarded})
        # Future.cancel may run our callback inline. Never hold the record lock.
        if handle is not None:
            handle.cancel()
        self._capture_completed()
