"""Real local worker ownership tests; no network services or test doubles."""
import asyncio
import os
import subprocess
import sys
import threading
import time
import pytest
from e6data_python_connector.async_work import reserve_work, run_blocking


def test_reservations_bound_admission_and_release():
    async def scenario():
        slots = [await reserve_work() for _ in range(4)]
        try:
            with pytest.raises(TimeoutError):
                await reserve_work(deadline=time.monotonic() + .02)
        finally:
            for slot in slots:
                slot.release()
        assert await run_blocking(sum, [1, 2]) == 3
    asyncio.run(scenario())


def test_cancelled_worker_retains_slot_until_completion():
    async def scenario():
        started, finish = threading.Event(), threading.Event()
        def work():
            started.set()
            finish.wait(2)
        slots = [await reserve_work() for _ in range(3)]
        task = asyncio.create_task(run_blocking(work))
        try:
            while not started.is_set():
                await asyncio.sleep(.001)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(TimeoutError):
                await reserve_work(deadline=time.monotonic() + .02)
        finally:
            finish.set()
            for slot in slots:
                slot.release()
        await asyncio.sleep(.02)
    asyncio.run(scenario())


def test_reservation_cannot_submit_twice():
    async def scenario():
        slot = await reserve_work()
        assert await slot.run(len, [1]) == 1
        with pytest.raises(RuntimeError):
            await slot.run(len, [])
    asyncio.run(scenario())


def test_capacity_is_shared_across_event_loops():
    async def scenario():
        slots = [await reserve_work() for _ in range(4)]
        outcomes = []
        def other_loop():
            async def attempt():
                try:
                    reservation = await reserve_work(deadline=time.monotonic() + .02)
                except TimeoutError:
                    outcomes.append('bounded')
                else:
                    reservation.release()
                    outcomes.append('incorrectly admitted')
            asyncio.run(attempt())
        thread = threading.Thread(target=other_loop)
        thread.start()
        try:
            while thread.is_alive():
                await asyncio.sleep(.001)
            assert outcomes == ['bounded']
        finally:
            for slot in slots:
                slot.release()
    asyncio.run(scenario())


@pytest.mark.skipif(not hasattr(os, 'fork'), reason='POSIX fork regression')
def test_child_work_capacity_is_new_and_inherited_reservations_are_invalid():
    result = subprocess.run([sys.executable, '-c', '''
import asyncio, os
from e6data_python_connector.async_work import reserve_work, run_blocking
async def reserve():
    return [await reserve_work() for _ in range(4)]
reservations = asyncio.run(reserve())
pid = os.fork()
if pid == 0:
    async def verify():
        try:
            reservations[0].release()
        except RuntimeError:
            pass
        else:
            return 2
        try:
            result = await run_blocking(sum, [1, 2], deadline=asyncio.get_running_loop().time() + .2)
        except TimeoutError:
            return 3
        return 0 if result == 3 else 4
    os._exit(asyncio.run(verify()))
_, status = os.waitpid(pid, 0)
for reservation in reservations:
    reservation.release()
assert os.waitstatus_to_exitcode(status) == 0, 'Child work ownership/capacity was inherited'
'''], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
