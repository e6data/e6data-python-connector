"""Shared credential coordination contracts without an issuer test double."""
import gc
import os
import threading
import time
import weakref

import pytest

from e6data_python_connector.oauth import ClientCredentialsTokenProvider
from e6data_python_connector.exceptions import OAuthError


@pytest.fixture
def provider(request):
    def create(**changes):
        options = dict(token_url='https://example.com/token', client_id='shared-contract',
                       client_secret='unit-input', timeout=1)
        options.update(changes)
        # Matching providers share naturally within a test. Unrelated tests must
        # not depend on when Python collects earlier providers and their cycles.
        options['client_id'] = f"{request.node.nodeid}:{options['client_id']}"
        return ClientCredentialsTokenProvider(**options)
    return create


def test_distinct_providers_share_live_cache_and_invalidation(provider):
    first, second = provider(), provider()
    first._access_token = 'cached-input'
    first._expires_at = time.monotonic() + 60
    assert second.get_token() == 'cached-input'
    second.invalidate()
    assert first._access_token is None


def test_same_identity_state_has_provider_object_lifetime(provider):
    first, second = provider(), provider()
    assert first._state is second._state
    ref = weakref.ref(first._state)
    del first
    gc.collect()
    assert ref() is second._state
    del second
    gc.collect()
    assert ref() is None


@pytest.mark.parametrize('changed', [dict(client_secret='rotated'), dict(scope='other'),
    dict(token_url='https://example.com/other'), dict(client_id='other'),
    dict(client_auth_method='post'), dict(timeout=2), dict(refresh_leeway_seconds=1)])
def test_distinct_credentials_or_policy_are_isolated(changed, provider):
    first, second = provider(), provider(**changed)
    assert first._state is not second._state


def test_single_flight_waiter_departure_and_stale_publication(provider):
    state = provider()._state
    a = state.select(time.monotonic() + .01)
    b = state.select(time.monotonic() + 1)
    assert a.owner and not b.owner and a.flight is b.flight
    assert a.flight.deadline > time.monotonic() + .5
    called = []
    state.install_cancel(a.flight, lambda: called.append('cancel'))
    state.detach(a.waiter)
    assert called == []
    state.detach(b.waiter)
    assert called == ['cancel']
    retiring = state.select(time.monotonic() + 1)
    assert retiring.retiring and retiring.waiter is None
    state.finish(a.flight, 'discarded', time.monotonic() + 60)
    assert state.token is None
    with pytest.raises(OAuthError):
        a.flight.result()
    new = state.select(time.monotonic() + 1)
    assert new.owner
    state.finish(a.flight, 'stale', time.monotonic() + 60)
    state.finish(new.flight, 'fresh', time.monotonic() + 60)
    assert new.flight.result() == 'fresh'


def test_completion_subscriptions_removable_and_errors_fresh(provider):
    state = provider()._state
    a = state.select(time.monotonic() + 1)
    called = []
    remove = a.flight.subscribe(lambda: called.append('removed'))
    remove()
    a.flight.subscribe(lambda: called.append(state.token))
    state.finish(a.flight, error=RuntimeError('secret must not survive'))
    assert called == [None]
    errors = []
    for _ in range(2):
        with pytest.raises(OAuthError) as error:
            a.flight.result()
        errors.append(error.value)
        assert 'secret' not in str(error.value)
    assert errors[0] is not errors[1]


def test_sync_wait_on_async_owner_same_thread_fails_without_joining(provider):
    state = provider()._state
    a = state.select(time.monotonic() + 1, is_async=True)
    with pytest.raises(OAuthError, match='thread'):
        state.select(time.monotonic() + 1)
    state.detach(a.waiter)
    state.finish(a.flight, error=OAuthError('cancelled'))


@pytest.mark.skipif(not hasattr(os, 'fork'), reason='fork required')
def test_inherited_provider_rejected_before_locked_state(provider):
    p = provider()
    p._state._lock.acquire()
    child = os.fork()
    if child == 0:
        try:
            with pytest.raises(OAuthError, match='process'):
                p.get_token()
            fresh = provider()
            assert fresh._state is not p._state
            os._exit(0)
        except BaseException:
            os._exit(1)
    p._state._lock.release()
    _, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 0


def test_threads_on_distinct_providers_share_one_flight_result(provider):
    from concurrent.futures import ThreadPoolExecutor
    providers = [provider() for _ in range(6)]
    state = providers[0]._state
    leader = state.select(time.monotonic() + 1)
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(p.get_token) for p in providers]
        until = time.monotonic() + 1
        while len(state._waiters) < 7 and time.monotonic() < until:
            time.sleep(.001)
        assert len(state._waiters) == 7
        state.finish(leader.flight, 'shared-state-input', time.monotonic() + 60)
        assert [future.result(timeout=1) for future in futures] == ['shared-state-input'] * 6
    assert state._flight is None
    assert state._waiters == {}


def test_rejection_of_old_token_preserves_new_publication(provider):
    p = provider()
    a = p._state.select(time.monotonic() + 1)
    p._state.finish(a.flight, 'replacement-input', time.monotonic() + 60)
    assert p.get_token(force_refresh=True, rejected_token='old-input') == 'replacement-input'


def test_invalidation_rejects_active_result_and_phase_deadline_expires(provider):
    p = provider(timeout=.02)
    a = p._state.select(time.monotonic() + 1)
    p.invalidate()
    assert p._state.generation == 1
    p._state.finish(a.flight, 'stale', time.monotonic() + 60)
    with pytest.raises(OAuthError, match='invalidated'):
        a.flight.result()
    b = p._state.select(time.monotonic() + 1)
    time.sleep(.025)
    p._state.finish(b.flight, 'late', time.monotonic() + 60)
    with pytest.raises(TimeoutError):
        b.flight.result()
    assert p._access_token is None


def test_subscribe_after_completion_and_late_cancel_registration(provider):
    p = provider()
    a = p._state.select(time.monotonic() + 1)
    with pytest.raises(RuntimeError, match='not complete'):
        a.flight.result()
    p._state.detach(a.waiter)
    calls = []
    p._state.install_cancel(a.flight, lambda: calls.append('cancel'))
    p._state.finish(a.flight, error=TimeoutError())
    remove = a.flight.subscribe(lambda: calls.append('done'))
    remove()
    p._state.detach(a.waiter)
    p._state.install_cancel(a.flight, lambda: calls.append('wrong'))
    assert calls == ['cancel', 'done']


def test_two_sync_pools_share_only_credentials_and_close_preserves_peer():
    from e6data_python_connector import ConnectionPool
    options = dict(min_size=1, max_size=1, pre_ping=False, host='localhost', port=1,
                   client_id='pool-state-contract', client_secret='unit-input',
                   token_url='https://example.com/token')
    first, second = ConnectionPool(**options), ConnectionPool(**options)
    try:
        a, b = first._all_connections[0].connection, second._all_connections[0].connection
        assert a is not b
        assert a._token_provider is not b._token_provider
        assert a._token_provider._state is b._token_provider._state
        a._token_provider._access_token = 'pool-cache-input'
        a._token_provider._expires_at = time.monotonic() + 60
        first.close_all()
        assert b._bearer_token() == 'pool-cache-input'
    finally:
        first.close_all()
        second.close_all()


def test_saturated_capacity_preserves_cache_and_matching_flight_without_workers(provider):
    from concurrent.futures import ThreadPoolExecutor
    from e6data_python_connector.oauth import _EXCHANGE_SLOTS
    cached, joined, other = provider(client_id='cache-capacity'), provider(client_id='join-capacity'), provider(client_id='new-capacity')
    cached._access_token = 'cached-input'
    cached._expires_at = time.monotonic() + 60
    selection = joined._state.select(time.monotonic() + 1)
    for _ in range(4):
        assert _EXCHANGE_SLOTS.acquire(blocking=False)
    try:
        assert cached.get_token() == 'cached-input'
        before = {thread.ident for thread in threading.enumerate()}
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            other.get_token()
        assert time.monotonic() - started < .1
        assert before == {thread.ident for thread in threading.enumerate()}
        assert other._state._flight is None
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(joined.get_token)
            until = time.monotonic() + 1
            while len(joined._state._waiters) < 2 and time.monotonic() < until:
                time.sleep(.001)
            assert len(joined._state._waiters) == 2
            joined._state.finish(selection.flight, 'joined-input', time.monotonic() + 60)
            assert future.result(timeout=1) == 'joined-input'
    finally:
        for _ in range(4):
            _EXCHANGE_SLOTS.release()
        joined._state.finish(selection.flight, error=TimeoutError())
    # Terminal overload leaves the identity available to a later explicit call.
    retry = other._state.select(time.monotonic() + 1)
    assert retry.owner
    other._state.finish(retry.flight, 'recovery-input', time.monotonic() + 60)
    assert other.get_token() == 'recovery-input'
