"""Shared credential state and actual event-loop lifecycle without an issuer double."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time

import pytest

from e6data_python_connector.async_oauth import AsyncClientCredentialsTokenProvider, _LOOP_SLOTS


def provider(**changes):
    options = dict(token_url='https://localhost/shared-test-token', client_id='shared-unit-id',
                   client_secret='unit-input', timeout=.1)
    options.update(changes)
    return AsyncClientCredentialsTokenProvider(**options)


def test_distinct_async_providers_share_cache_and_close_preserves_peer():
    async def run():
        first, second = provider(), provider()
        first._access_token = 'unit-cached-value'
        first._expires_at = time.monotonic() + 60
        assert second._access_token == 'unit-cached-value'
        await first.close()
        assert await second.get_token() == 'unit-cached-value'
        await second.invalidate()
        assert first._access_token is None
        await second.close()
    asyncio.run(run())


def test_separate_loop_threads_share_only_cached_state():
    first = provider()
    first._access_token = 'unit-cached-value'
    first._expires_at = time.monotonic() + 60
    def worker():
        async def run():
            local = provider()
            try:
                return await local.get_token(), local._client
            finally:
                await local.close()
        return asyncio.run(run())
    with ThreadPoolExecutor(max_workers=2) as executor:
        assert list(executor.map(lambda _: worker(), range(2))) == [('unit-cached-value', None)] * 2
    asyncio.run(first.close())


def test_owner_close_does_not_cancel_foreign_waiter():
    async def run():
        loop = asyncio.get_running_loop()
        _LOOP_SLOTS[loop] = asyncio.Semaphore(0)
        first, second = provider(), provider()
        leader = asyncio.create_task(first.get_token())
        await asyncio.sleep(0)
        follower = asyncio.create_task(second.get_token())
        await asyncio.sleep(0)
        try:
            with pytest.raises(TimeoutError):
                await first.close(deadline=time.monotonic() + .01)
            with pytest.raises(asyncio.CancelledError):
                await leader
            with pytest.raises(TimeoutError):
                await follower
            assert first._client is None
        finally:
            await second.close()
            await first.close()
            del _LOOP_SLOTS[loop]
    asyncio.run(run())


def test_owner_task_cancelled_before_start_terminalizes_foreign_waiters():
    from e6data_python_connector.exceptions import OAuthError
    async def run():
        first, second = provider(), provider()
        loop = asyncio.get_running_loop()
        leader = asyncio.create_task(first.get_token())
        # FIFO callback ordering cancels the newly scheduled exchange before its
        # first coroutine instruction. No transport or issuer is substituted.
        loop.call_soon(lambda: first._task.cancel())
        follower = asyncio.create_task(second.get_token())
        try:
            for caller in (leader, follower):
                with pytest.raises(OAuthError):
                    await caller
                assert not caller.cancelled()
            assert first._task.cancelled()
            assert first._state._flight is None
            assert first._waiters == second._waiters == 0
        finally:
            await first.close()
            await second.close()
    asyncio.run(run())


def test_invalidating_peer_rejects_pending_publication():
    from e6data_python_connector.exceptions import OAuthError
    async def run():
        first, second = provider(), provider()
        chosen = first._state.select(time.monotonic() + 1, is_async=True)
        await second.invalidate()
        # Pure publication transition checks the same generation guard used by
        # completed transport work; this is not an issuer response simulation.
        first._state.finish(chosen.flight, token='unit-state-value', reusable_until=time.monotonic() + 60)
        with pytest.raises(OAuthError):
            chosen.flight.result()
        assert first._access_token is second._access_token is None
        await first.close()
        await second.close()
    asyncio.run(run())


def test_close_waits_for_exchange_not_callers_unrelated_work():
    async def run():
        loop = asyncio.get_running_loop()
        _LOOP_SLOTS[loop] = asyncio.Semaphore(0)
        p = provider(timeout=2)
        unrelated = asyncio.Event()
        started = asyncio.Event()
        detached = asyncio.Event()
        async def caller():
            try:
                started.set()
                await p.get_token()
            except asyncio.CancelledError:
                detached.set()
                await unrelated.wait()
        task = asyncio.create_task(caller())
        try:
            async with asyncio.timeout(2):
                # The caller runs through get_token's registration before its
                # first suspension allows this event's waiter to continue.
                await started.wait()
                assert p._waiters == 1
                closing = asyncio.create_task(p.close(deadline=time.monotonic() + 1))
                await detached.wait()
                assert not unrelated.is_set()
                await closing
            assert not task.done()
            assert p._state._flight is None
        finally:
            unrelated.set()
            await task
            await p.close()
            del _LOOP_SLOTS[loop]
    asyncio.run(run())


def test_foreign_loop_owner_cancellation_is_oauth_error_for_peer():
    import threading
    from e6data_python_connector.exceptions import OAuthError
    ready, stop = threading.Event(), threading.Event()
    outcomes = []
    def owner_thread():
        async def run():
            loop = asyncio.get_running_loop()
            _LOOP_SLOTS[loop] = asyncio.Semaphore(0)
            owner = provider(timeout=2)
            caller = asyncio.create_task(owner.get_token())
            await asyncio.sleep(0)
            ready.set()
            try:
                await asyncio.to_thread(stop.wait, 1)
                owner._task.cancel()
                with pytest.raises(OAuthError):
                    await caller
            finally:
                await owner.close()
                del _LOOP_SLOTS[loop]
        try:
            asyncio.run(run())
        except BaseException as error:
            outcomes.append(type(error).__name__)
    thread = threading.Thread(target=owner_thread)
    thread.start()
    async def run():
        assert await asyncio.to_thread(ready.wait, 1)
        peer = provider(timeout=2)
        task = asyncio.create_task(peer.get_token())
        await asyncio.sleep(0)
        assert peer._task is None  # The foreign loop owns the sole exchange.
        stop.set()
        try:
            with pytest.raises(OAuthError):
                await asyncio.wait_for(task, 2)
            assert not task.cancelled()
        finally:
            await peer.close()
    try:
        asyncio.run(run())
    finally:
        stop.set()
        thread.join(3)
    assert not thread.is_alive()
    assert outcomes == []
