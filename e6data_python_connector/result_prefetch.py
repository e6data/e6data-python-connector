"""Track raw result downloads without publishing cursor state."""

import os
import logging
import threading
import time
from collections import deque


_slots = threading.BoundedSemaphore(4)
_logger = logging.getLogger(__name__)


class ContinuousResultStream:
    """Retain ordered raw responses while one producer keeps downloading.

    Queue size is deliberately unlimited. Only the producer advances session
    identity; taking an older response never rolls the cleanup session back.
    The completion handle covers the producer's entire lifetime, including
    metadata preparation and transport registration.
    """

    def __init__(self, session_id=None, deadline=None, notify=None):
        self.handle = None
        self.deadline = deadline
        self._pid = os.getpid()
        self._condition = threading.Condition(threading.RLock())
        self._queue = deque()
        self._transport = None
        self._session_id = session_id
        self._elapsed = 0.0
        self._retired = False
        self._finished = False
        self._failed = False
        self._notify = notify
        self._queued_bytes = 0
        self._downloaded_count = 0
        self._downloaded_bytes = 0
        self._started = time.monotonic()
        self._finished_at = None

    def _check_pid(self):
        if self._pid != os.getpid():
            raise RuntimeError('Result download belongs to another process.')

    def _signal(self):
        with self._condition:
            self._condition.notify_all()
        if self._notify is not None:
            self._notify()

    def _log(self, event):
        if _logger.isEnabledFor(logging.DEBUG):
            with self._condition:
                count, size = len(self._queue), self._queued_bytes
                downloaded, downloaded_bytes = self._downloaded_count, self._downloaded_bytes
            _logger.debug(
                'Result download %s queued_envelopes=%d queued_protobuf_bytes=%d',
                event, count, size,
                extra={'result_batch_download_event': event,
                       'result_batch_queued_envelopes': count,
                       'result_batch_queued_protobuf_bytes': size,
                       'result_batch_downloaded_envelopes': downloaded,
                       'result_batch_downloaded_protobuf_bytes': downloaded_bytes,
                       'result_batch_background_download_seconds': self.download_seconds})

    def set_handle(self, handle):
        self._check_pid()
        with self._condition:
            if self.handle is not None:
                raise RuntimeError('Result producer is already registered.')
            self.handle = handle
            retired = self._retired
        handle.add_done_callback(self._producer_done)
        if retired:
            handle.cancel()

    def _producer_done(self, handle):
        if self._pid != os.getpid():
            return
        try:
            handle.result()
        except BaseException as error:
            self.fail(error, 0.0)
        self.finish()
        self._release_retired_handles()

    def set_transport(self, handle):
        self._check_pid()
        with self._condition:
            old = self._transport
            if old is not None and not old.done():
                raise RuntimeError('A result RPC is already running.')
            if old is not None:
                self._capture_transport(old)
            self._transport = handle
            retired = self._retired
        handle.add_done_callback(self._transport_done)
        if retired:
            handle.cancel()

    def _capture_transport(self, handle):
        with self._condition:
            if handle is not self._transport or not handle.done():
                return
            try:
                response = handle.result()
            except BaseException:
                return
            self._session_id = getattr(response, 'sessionId', '') or self._session_id

    def _transport_done(self, handle):
        if self._pid != os.getpid():
            return
        self._capture_transport(handle)
        self._release_retired_handles()
        self._signal()

    def clear_transport(self, handle):
        self._check_pid()
        with self._condition:
            if handle is self._transport:
                self._capture_transport(handle)
                if not handle.done():
                    raise RuntimeError('Cannot forget a running result RPC.')
                self._transport = None

    def push(self, response, rpc_seconds):
        self._check_pid()
        size = response.ByteSize()
        with self._condition:
            self._session_id = getattr(response, 'sessionId', '') or self._session_id
            if self._retired or self._finished or self._failed:
                return
            self._queue.append((response, None, rpc_seconds, size))
            self._queued_bytes += size
            self._downloaded_count += 1
            self._downloaded_bytes += size
        self._log('queued')
        self._signal()

    def fail(self, error, rpc_seconds):
        self._check_pid()
        with self._condition:
            if self._retired or self._finished or self._failed:
                return
            self._failed = True
            self._queue.append((None, error, rpc_seconds, 0))
        self._log('failed')
        self._signal()

    def finish(self):
        self._check_pid()
        with self._condition:
            self._finished = True
            if self._finished_at is None:
                self._finished_at = time.monotonic()
        self._log('finished')
        self._signal()

    def take(self):
        self._check_pid()
        with self._condition:
            if self._retired or not self._queue:
                raise RuntimeError('No downloaded result is available.')
            response, error, self._elapsed, size = self._queue.popleft()
            self._queued_bytes -= size
        if error is not None:
            raise error
        return response

    def wait(self, timeout):
        self._check_pid()
        with self._condition:
            if not self._condition.wait_for(
                    lambda: self._queue or self._retired or self._finished, timeout):
                raise TimeoutError('Result download exceeded operation deadline.')

    @property
    def ready(self):
        self._check_pid()
        with self._condition:
            return bool(self._queue) or self._retired or self._finished

    @property
    def retired(self):
        self._check_pid()
        with self._condition:
            return self._retired

    def _release_retired_handles(self):
        with self._condition:
            if not self._retired:
                return
            if self._transport is not None and self._transport.done():
                self._capture_transport(self._transport)
                self._transport = None
            if self._transport is None and self.handle is not None and self.handle.done():
                self.handle = None

    @property
    def settled(self):
        self._check_pid()
        with self._condition:
            if self._transport is not None:
                self._capture_transport(self._transport)
            settled = ((self.handle is None or self.handle.done()) and
                       (self._transport is None or self._transport.done()) and
                       (self._finished or self._retired))
            self._release_retired_handles()
            return settled

    @property
    def session_id(self):
        self._check_pid()
        with self._condition:
            if self._transport is not None:
                self._capture_transport(self._transport)
            return self._session_id

    @property
    def elapsed(self):
        self._check_pid()
        with self._condition:
            return self._elapsed

    @property
    def queued_count(self):
        self._check_pid()
        with self._condition:
            return len(self._queue)

    @property
    def queued_bytes(self):
        self._check_pid()
        with self._condition:
            return self._queued_bytes

    @property
    def download_seconds(self):
        self._check_pid()
        with self._condition:
            return (self._finished_at or time.monotonic()) - self._started

    def retire(self):
        self._check_pid()
        with self._condition:
            self._retired = True
            self._queue.clear()
            self._queued_bytes = 0
            transport, producer = self._transport, self.handle
        # Cancellation callbacks may enter this record immediately.
        if transport is not None:
            transport.cancel()
        if producer is not None:
            producer.cancel()
        self._release_retired_handles()
        self._log('retired')
        self._signal()


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
