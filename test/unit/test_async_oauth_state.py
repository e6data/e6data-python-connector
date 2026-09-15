"""Pure provider cache/lifecycle state, no fabricated issuer or transport."""
import asyncio
import time
import pytest
from e6data_python_connector.async_oauth import AsyncClientCredentialsTokenProvider
from e6data_python_connector.exceptions import OAuthError


def provider(**kwargs):
    return AsyncClientCredentialsTokenProvider('https://localhost/token', 'unit-id', 'unit-input', **kwargs)


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


def test_short_waiter_detaches_without_cancelling_other_waiter():
    from e6data_python_connector.async_oauth import _LOOP_SLOTS
    async def scenario():
        loop = asyncio.get_running_loop()
        _LOOP_SLOTS[loop] = asyncio.Semaphore(0)
        p = provider(timeout=.06)
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
            del _LOOP_SLOTS[loop]
    asyncio.run(scenario())


def test_last_waiter_cancels_owned_phase():
    from e6data_python_connector.async_oauth import _LOOP_SLOTS
    async def scenario():
        loop = asyncio.get_running_loop()
        _LOOP_SLOTS[loop] = asyncio.Semaphore(0)
        p = provider()
        try:
            task = asyncio.create_task(p.get_token())
            await asyncio.sleep(0)
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
            del _LOOP_SLOTS[loop]
    asyncio.run(scenario())


def test_cross_loop_use_rejected():
    p = provider()
    asyncio.run(p.invalidate())
    with pytest.raises(OAuthError, match='another'):
        asyncio.run(p.invalidate())


def test_shared_phase_deadline_includes_admission():
    from e6data_python_connector.async_oauth import _LOOP_SLOTS
    async def scenario():
        loop = asyncio.get_running_loop()
        slots = asyncio.Semaphore(0)
        _LOOP_SLOTS[loop] = slots
        p = provider(timeout=.02)
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
            del _LOOP_SLOTS[loop]
    asyncio.run(scenario())


def test_immediate_retry_waits_for_retired_phase_before_new_admission():
    from e6data_python_connector.async_oauth import _LOOP_SLOTS
    async def scenario():
        loop = asyncio.get_running_loop()
        _LOOP_SLOTS[loop] = asyncio.Semaphore(0)
        p = provider(timeout=.02)
        try:
            with pytest.raises(TimeoutError):
                await p.get_token(deadline=time.monotonic() + 1)
            old_phase = p._task
            # Retry immediately without a separate cleanup wait. This call has
            # a fresh budget to await any retirement and try admission.
            with pytest.raises(TimeoutError):
                await p.get_token(deadline=time.monotonic() + 1)
            assert p._task is not old_phase
            assert old_phase.done()
            async with asyncio.timeout(1):
                await asyncio.shield(asyncio.gather(p._task, return_exceptions=True))
            assert p._state._flight is None
            assert not p._state._waiters
            assert p._client is None
            assert p._access_token is None
        finally:
            await p.close()
            del _LOOP_SLOTS[loop]
    asyncio.run(scenario())


def test_short_first_waiter_does_not_own_shared_budget():
    from e6data_python_connector.async_oauth import _LOOP_SLOTS
    async def scenario():
        loop = asyncio.get_running_loop()
        _LOOP_SLOTS[loop] = asyncio.Semaphore(0)
        p = provider(timeout=.08)
        try:
            short = asyncio.create_task(p.get_token(deadline=time.monotonic() + .01))
            await asyncio.sleep(0)
            long = asyncio.create_task(p.get_token(deadline=time.monotonic() + 1))
            with pytest.raises(TimeoutError):
                await short
            assert not p._task.done()
            assert not long.done()
            with pytest.raises(TimeoutError):
                await long
        finally:
            await p.close()
            del _LOOP_SLOTS[loop]
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


def test_close_cancels_admission_without_creating_client():
    from e6data_python_connector.async_oauth import _LOOP_SLOTS
    async def scenario():
        loop = asyncio.get_running_loop()
        _LOOP_SLOTS[loop] = asyncio.Semaphore(0)
        p = provider()
        task = asyncio.create_task(p.get_token())
        await asyncio.sleep(0)
        await p.close()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert p._client is None
        del _LOOP_SLOTS[loop]
    asyncio.run(scenario())


def test_close_accepts_shared_cleanup_deadline():
    async def scenario():
        p = provider()
        await p.close(deadline=time.monotonic() + .1)
        assert p._closed
        with pytest.raises(ValueError):
            await p.close(deadline=float('nan'))
    asyncio.run(scenario())
