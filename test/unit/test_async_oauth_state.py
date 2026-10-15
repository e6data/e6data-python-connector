"""Provider lifecycle with explicit deterministic exchange test doubles."""
import asyncio
import time
import pytest
from e6data_python_connector.async_oauth import AsyncClientCredentialsTokenProvider
from e6data_python_connector.exceptions import OAuthError


def provider(**kwargs):
    return AsyncClientCredentialsTokenProvider('https://localhost/token', 'unit-id', 'unit-input', **kwargs)


def hold_exchange(monkeypatch, p):
    """Block an admitted test-double exchange until its owner cancels it."""
    started = asyncio.Event()

    async def fetch(deadline):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(p, '_fetch_token', fetch)
    return started


@pytest.mark.parametrize('kwargs', [{'timeout': 0}, {'refresh_leeway_seconds': -1}, {'client_auth_method': 'other'}])
def test_bad_config(kwargs):
    with pytest.raises(ValueError):
        provider(**kwargs)


def test_cached_replacement_invalidation_and_close():
    async def scenario():
        p = provider()
        p._access_token = 'unit-new-token'
        p._expires_at = time.monotonic() + 120
        assert await p.get_token(force_refresh=True, rejected_token='unit-old-token') == 'unit-new-token'
        await p.invalidate()
        assert p._access_token is None
        assert p._generation == 1
        await p.close()
        await p.close()
        with pytest.raises(OAuthError):
            await p.get_token()
    asyncio.run(scenario())


def test_short_waiter_detaches_without_cancelling_other_waiter(monkeypatch):
    async def scenario():
        p = provider(timeout=.06)
        hold_exchange(monkeypatch, p)
        try:
            long = asyncio.create_task(p.get_token(deadline=time.monotonic() + 1))
            short = asyncio.create_task(p.get_token(deadline=time.monotonic() + .01))
            with pytest.raises(TimeoutError):
                await short
            assert not p._task.done()
            assert p._waiters == 1
            with pytest.raises(TimeoutError):
                await long
        finally:
            await p.close()
    asyncio.run(scenario())


def test_last_waiter_cancels_owned_phase(monkeypatch):
    async def scenario():
        p = provider()
        started = hold_exchange(monkeypatch, p)
        try:
            task = asyncio.create_task(p.get_token())
            await started.wait()
            phase = p._task
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.gather(phase, return_exceptions=True)
            assert phase.cancelled()
            assert p._waiters == 0
            assert p._state._flight is None
        finally:
            await p.close()
    asyncio.run(scenario())


def test_cross_loop_use_rejected():
    p = provider()
    asyncio.run(p.invalidate())
    with pytest.raises(OAuthError, match='another'):
        asyncio.run(p.invalidate())


def test_shared_phase_deadline_includes_exchange(monkeypatch):
    async def scenario():
        p = provider(timeout=.02)
        hold_exchange(monkeypatch, p)
        try:
            with pytest.raises(TimeoutError):
                await p.get_token()
            # The caller deadline does not include waiting for cancellation to
            # drain, but the owned phase must actually terminate within a bound.
            async with asyncio.timeout(1):
                await asyncio.shield(asyncio.gather(p._task, return_exceptions=True))
            assert p._task.done()
            assert p._state._flight is None
            assert not p._state._waiters
            assert p._client is None
            assert p._access_token is None
        finally:
            await p.close()
    asyncio.run(scenario())


def test_immediate_retry_waits_for_retired_phase_before_new_admission(monkeypatch):
    async def scenario():
        p = provider(timeout=2)
        cancellation_started = asyncio.Event()
        release_cleanup = asyncio.Event()
        calls = []

        async def fetch(deadline):
            calls.append(deadline)
            if len(calls) == 1:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancellation_started.set()
                    await release_cleanup.wait()
                token = 'test-double-retired-token'
            else:
                token = 'test-double-fresh-token'
            return {'access_token': token, 'token_type': 'Bearer', 'expires_in': 120}

        monkeypatch.setattr(p, '_fetch_token', fetch)
        retry = None
        try:
            with pytest.raises(TimeoutError):
                await p.get_token(deadline=time.monotonic() + .02)
            old_phase = p._task
            await cancellation_started.wait()
            retry = asyncio.create_task(p.get_token(deadline=time.monotonic() + 1))
            await asyncio.sleep(0)
            assert not old_phase.done()
            assert p._task is old_phase
            assert not retry.done()
            assert len(calls) == 1
            release_cleanup.set()
            assert await retry == 'test-double-fresh-token'
            assert old_phase.done()
            assert p._task is not old_phase
            assert len(calls) == 2
            assert p._state._flight is None
            assert not p._state._waiters
            assert p._client is None
            assert p._access_token == 'test-double-fresh-token'
        finally:
            release_cleanup.set()
            if retry is not None:
                await asyncio.gather(retry, return_exceptions=True)
            await p.close()
    asyncio.run(scenario())


def test_short_first_waiter_does_not_own_shared_budget(monkeypatch):
    async def scenario():
        p = provider(timeout=.08)
        started = hold_exchange(monkeypatch, p)
        try:
            short = asyncio.create_task(p.get_token(deadline=time.monotonic() + .01))
            await started.wait()
            long = asyncio.create_task(p.get_token(deadline=time.monotonic() + 1))
            with pytest.raises(TimeoutError):
                await short
            assert not p._task.done()
            assert not long.done()
            with pytest.raises(TimeoutError):
                await long
        finally:
            await p.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('deadline', [float('nan'), True, 'bad', -1])
def test_invalid_or_expired_deadline_does_not_dispatch(deadline):
    async def scenario():
        p = provider()
        with pytest.raises((ValueError, TimeoutError)):
            await p.get_token(deadline=deadline)
        assert p._task is None
        await p.close()
    asyncio.run(scenario())


def test_close_cancels_owned_exchange_without_creating_client(monkeypatch):
    async def scenario():
        p = provider()
        started = hold_exchange(monkeypatch, p)
        task = asyncio.create_task(p.get_token())
        await started.wait()
        await p.close()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert p._client is None
    asyncio.run(scenario())


def test_close_accepts_shared_cleanup_deadline():
    async def scenario():
        p = provider()
        await p.close(deadline=time.monotonic() + .1)
        assert p._closed
        with pytest.raises(ValueError):
            await p.close(deadline=float('nan'))
    asyncio.run(scenario())


def test_task_start_failure_releases_capacity_and_terminalizes_flight(monkeypatch):
    from e6data_python_connector.async_oauth import _LOOP_SLOTS

    async def scenario():
        loop = asyncio.get_running_loop()
        p = provider()
        original_create_task = loop.create_task

        def reject_exchange_start(coroutine, **kwargs):
            if coroutine.cr_code.co_name == '_refresh':
                raise RuntimeError('test-double task-start failure')
            return original_create_task(coroutine, **kwargs)

        try:
            with monkeypatch.context() as patch:
                patch.setattr(loop, 'create_task', reject_exchange_start)
                with pytest.raises(RuntimeError, match='task-start failure'):
                    await p.get_token()
            assert _LOOP_SLOTS[loop]._value == 4
            assert p._task is None
            assert p._client is None
            assert p._state._flight is None
            assert not p._state._waiters
        finally:
            await p.close()
    asyncio.run(scenario())


def test_caller_departure_keeps_capacity_until_exchange_cleanup_finishes(monkeypatch):
    from e6data_python_connector.async_oauth import _LOOP_SLOTS

    async def scenario():
        owners = [AsyncClientCredentialsTokenProvider(
            'https://localhost/token', f'cleanup-owner-{index}', 'unit-input', timeout=2)
            for index in range(4)]
        rejected = AsyncClientCredentialsTokenProvider(
            'https://localhost/token', 'cleanup-new-owner', 'unit-input', timeout=2)
        started = [asyncio.Event() for _ in owners]
        cancelled = asyncio.Event()
        release_cleanup = asyncio.Event()
        release_others = asyncio.Event()

        for index, owner in enumerate(owners):
            async def fetch(deadline, index=index):
                started[index].set()
                try:
                    await release_others.wait()
                except asyncio.CancelledError:
                    if index != 0:
                        raise
                    cancelled.set()
                    await release_cleanup.wait()
                return {'access_token': f'test-double-late-{index}', 'token_type': 'Bearer', 'expires_in': 120}
            monkeypatch.setattr(owner, '_fetch_token', fetch)

        async def fetch_new(deadline):
            return {'access_token': 'test-double-new', 'token_type': 'Bearer', 'expires_in': 120}

        monkeypatch.setattr(rejected, '_fetch_token', fetch_new)
        tasks = [asyncio.create_task(owner.get_token()) for owner in owners]
        try:
            async with asyncio.timeout(1):
                await asyncio.gather(*(event.wait() for event in started))
            tasks[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await tasks[0]
            await cancelled.wait()
            assert not owners[0]._task.done()
            assert _LOOP_SLOTS[asyncio.get_running_loop()].locked()
            outcomes = await asyncio.wait_for(asyncio.gather(
                rejected.get_token(), return_exceptions=True), .1)
            assert len(outcomes) == 1
            assert isinstance(outcomes[0], TimeoutError)
            assert rejected._task is None
            release_cleanup.set()
            await owners[0]._task
            await asyncio.sleep(0)
            assert owners[0]._access_token is None
            assert owners[0]._state._flight is None
            assert await rejected.get_token() == 'test-double-new'
        finally:
            release_cleanup.set()
            release_others.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.gather(*(p.close() for p in [*owners, rejected]))
    asyncio.run(scenario())
