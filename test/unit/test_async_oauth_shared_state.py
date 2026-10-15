"""Shared credential lifecycle with explicit deterministic exchange test doubles."""
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


def hold_exchange(monkeypatch, p):
    """Block an admitted test-double exchange until its owner cancels it."""
    started = asyncio.Event()

    async def fetch(deadline):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(p, '_fetch_token', fetch)
    return started


def test_saturated_capacity_preserves_cache_and_matching_flight_without_work(monkeypatch):
    """Deterministic exchange doubles hold every slot without contacting an issuer."""
    async def run():
        active = [provider(client_id=f'capacity-owner-{index}', timeout=2) for index in range(4)]
        cached = provider(client_id='capacity-cached', timeout=2)
        peer = provider(client_id='capacity-owner-0', timeout=2)
        rejected = provider(client_id='capacity-rejected', timeout=2)
        release = asyncio.Event()
        started = [asyncio.Event() for _ in active]
        calls = []

        for index, owner in enumerate(active):
            async def fetch(deadline, index=index):
                calls.append(index)
                started[index].set()
                await release.wait()
                return {'access_token': f'test-double-token-{index}', 'token_type': 'Bearer', 'expires_in': 120}
            monkeypatch.setattr(owner, '_fetch_token', fetch)

        cached._access_token = 'test-double-cached-token'
        cached._expires_at = time.monotonic() + 60
        tasks = [asyncio.create_task(owner.get_token()) for owner in active]
        peer_task = None
        try:
            async with asyncio.timeout(1):
                await asyncio.gather(*(event.wait() for event in started))
            assert await cached.get_token() == 'test-double-cached-token'
            peer_task = asyncio.create_task(peer.get_token())
            await asyncio.sleep(0)
            assert peer._task is None
            assert peer._waiters == 1
            assert not peer_task.done()
            outcomes = await asyncio.wait_for(asyncio.gather(
                rejected.get_token(deadline=time.monotonic() + 1), return_exceptions=True), .1)
            assert len(outcomes) == 1
            assert isinstance(outcomes[0], TimeoutError)
            assert rejected._task is None
            assert rejected._client is None
            assert rejected._state._flight is None
            assert not rejected._state._waiters
            assert calls == [0, 1, 2, 3]
            release.set()
            assert await asyncio.gather(*tasks, peer_task) == [
                'test-double-token-0', 'test-double-token-1', 'test-double-token-2',
                'test-double-token-3', 'test-double-token-0',
            ]
        finally:
            release.set()
            await asyncio.gather(*tasks, *([peer_task] if peer_task else []), return_exceptions=True)
            await asyncio.gather(*(p.close() for p in [*active, cached, peer, rejected]))
    asyncio.run(run())


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


def test_each_event_loop_can_admit_four_distinct_exchanges(monkeypatch):
    import threading
    barrier = threading.Barrier(2)

    def worker(loop_index):
        async def run():
            owners = [provider(client_id=f'loop-{loop_index}-owner-{index}', timeout=2)
                      for index in range(4)]
            started = [asyncio.Event() for _ in owners]
            release = asyncio.Event()
            for index, owner in enumerate(owners):
                async def fetch(deadline, index=index):
                    started[index].set()
                    await release.wait()
                    return {'access_token': f'test-double-loop-{loop_index}-{index}',
                            'token_type': 'Bearer', 'expires_in': 120}
                monkeypatch.setattr(owner, '_fetch_token', fetch)
            tasks = [asyncio.create_task(owner.get_token()) for owner in owners]
            try:
                async with asyncio.timeout(1):
                    await asyncio.gather(*(event.wait() for event in started))
                    await asyncio.to_thread(barrier.wait, 1)
                release.set()
                return await asyncio.gather(*tasks)
            finally:
                release.set()
                await asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.gather(*(owner.close() for owner in owners))
        return asyncio.run(run())

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(worker, range(2)))
    assert outcomes == [[f'test-double-loop-{loop_index}-{index}' for index in range(4)]
                        for loop_index in range(2)]


def test_owner_close_does_not_cancel_foreign_waiter(monkeypatch):
    async def run():
        first = provider(client_id='owner-close-shared', timeout=2)
        second = provider(client_id='owner-close-shared', timeout=2)
        started, release = asyncio.Event(), asyncio.Event()

        async def fetch(deadline):
            started.set()
            await release.wait()
            return {'access_token': 'test-double-shared-token', 'token_type': 'Bearer', 'expires_in': 120}

        monkeypatch.setattr(first, '_fetch_token', fetch)
        caller = asyncio.create_task(first.get_token())
        await started.wait()
        peer = asyncio.create_task(second.get_token())
        await asyncio.sleep(0)
        try:
            assert second._waiters == 1
            with pytest.raises(TimeoutError):
                await first.close(deadline=time.monotonic() + .01)
            with pytest.raises(asyncio.CancelledError):
                await caller
            assert not first._task.done()
            assert not peer.done()
            release.set()
            assert await peer == 'test-double-shared-token'
            assert await second.get_token() == 'test-double-shared-token'
            assert first._client is None
        finally:
            release.set()
            await asyncio.gather(caller, peer, return_exceptions=True)
            await second.close()
            await first.close()
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
            assert _LOOP_SLOTS[loop]._value == 4
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
        first._state.finish(chosen.flight, token='unit-state-value', reusable_until=time.monotonic() + 60, expires_at=time.monotonic() + 3600)
        with pytest.raises(OAuthError):
            chosen.flight.result()
        assert first._access_token is second._access_token is None
        await first.close()
        await second.close()
    asyncio.run(run())


def test_close_waits_for_exchange_not_callers_unrelated_work(monkeypatch):
    async def run():
        p = provider(timeout=2)
        hold_exchange(monkeypatch, p)
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
    asyncio.run(run())


def test_foreign_loop_owner_cancellation_is_oauth_error_for_peer(monkeypatch):
    import threading
    from e6data_python_connector.exceptions import OAuthError
    ready, stop = threading.Event(), threading.Event()
    outcomes = []
    def owner_thread():
        async def run():
            owner = provider(timeout=2)
            exchange_started = hold_exchange(monkeypatch, owner)
            caller = asyncio.create_task(owner.get_token())
            try:
                await asyncio.wait_for(exchange_started.wait(), 1)
                ready.set()
                await asyncio.to_thread(stop.wait, 1)
                owner._task.cancel()
                with pytest.raises(OAuthError):
                    await caller
            finally:
                await owner.close()
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
