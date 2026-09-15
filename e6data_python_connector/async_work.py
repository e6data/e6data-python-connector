"""Process-wide bounded local work with reservations retained by actual workers."""
import asyncio
import math
import os
import threading
import time

_SLOTS = threading.BoundedSemaphore(4)


def _reset_child_capacity():
    global _SLOTS
    _SLOTS = threading.BoundedSemaphore(4)


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_reset_child_capacity)


def _validate_deadline(deadline):
    if deadline is not None and (isinstance(deadline, bool) or not isinstance(deadline, (int, float))
                                 or not math.isfinite(deadline)):
        raise ValueError('deadline must be a finite monotonic timestamp.')


class WorkReservation:
    """An admitted batch/certificate job; submitted work owns its slot to completion."""
    def __init__(self, deadline=None, slots=None):
        self._deadline = deadline
        self._pid = os.getpid()
        self._slots = _SLOTS if slots is None else slots
        self._state = 'reserved'
        self._loop = asyncio.get_running_loop()

    def release(self):
        if self._pid != os.getpid():
            raise RuntimeError('Work reservation belongs to another process.')
        if self._state == 'reserved':
            self._state = 'released'
            self._slots.release()

    async def run(self, function, *args):
        if self._pid != os.getpid() or self._loop is not asyncio.get_running_loop() or self._state != 'reserved':
            raise RuntimeError('Work reservation is unavailable or belongs to another loop.')
        if self._deadline is not None and time.monotonic() >= self._deadline:
            self.release()
            raise TimeoutError('Local work deadline exceeded.')
        future = self._loop.create_future()
        self._state = 'submitted'

        def publish(value, error):
            if not future.done():
                if error is not None:
                    future.set_exception(error)
                else:
                    future.set_result(value)

        def worker():
            value, error = None, None
            try:
                value = function(*args)
            except BaseException as exc:
                error = exc
            finally:
                self._state = 'completed'
                self._slots.release()
            try:
                self._loop.call_soon_threadsafe(publish, value, error)
            except RuntimeError:
                pass  # The owner loop closed; the actual worker already freed capacity.

        try:
            threading.Thread(target=worker, daemon=True).start()
        except BaseException:
            self._state = 'released'
            self._slots.release()
            raise
        try:
            remaining = None if self._deadline is None else max(0, self._deadline - time.monotonic())
            async with asyncio.timeout(remaining):
                return await future
        finally:
            # Cancelling this future discards late output, never releases worker capacity.
            if not future.done():
                future.cancel()


async def reserve_work(deadline=None):
    """Wait asynchronously for admission without queueing background work."""
    _validate_deadline(deadline)
    while True:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError('Local work admission deadline exceeded.')
        slots = _SLOTS
        if slots.acquire(blocking=False):
            return WorkReservation(deadline, slots)
        await asyncio.sleep(.005 if deadline is None else min(.005, max(0, deadline - time.monotonic())))


async def run_blocking(function, *args, deadline=None):
    reservation = await reserve_work(deadline)
    try:
        return await reservation.run(function, *args)
    finally:
        reservation.release()
