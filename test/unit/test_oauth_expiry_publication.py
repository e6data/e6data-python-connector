"""Expiry races use deterministic clocks and exchange test doubles only."""

import asyncio
from types import SimpleNamespace

import pytest

from e6data_python_connector import async_oauth, oauth, oauth_cache
from e6data_python_connector.exceptions import OAuthError


@pytest.fixture
def clock(monkeypatch):
    clock = SimpleNamespace(now=100.0)
    test_time = SimpleNamespace(monotonic=lambda: clock.now)
    for module in (oauth, async_oauth, oauth_cache):
        monkeypatch.setattr(module, 'time', test_time)
    return clock


def make_provider(kind, monkeypatch, identity):
    provider_type = (oauth.ClientCredentialsTokenProvider if kind == 'sync'
                     else async_oauth.AsyncClientCredentialsTokenProvider)
    provider = provider_type('https://localhost/expiry-test', identity,
                             'test-only-secret', timeout=10)
    payload = {'access_token': 'test-only-token', 'token_type': 'Bearer', 'expires_in': 1}
    if kind == 'sync':
        monkeypatch.setattr(provider, '_fetch_token', lambda deadline: payload)
    else:
        async def fetch(deadline):
            return payload
        monkeypatch.setattr(provider, '_fetch_token', fetch)
    return provider


def acquire(kind, provider):
    if kind == 'sync':
        return provider.get_token()

    async def run():
        try:
            return await provider.get_token()
        finally:
            await provider.close()
    return asyncio.run(run())


@pytest.mark.parametrize('kind', ['sync', 'async'])
def test_token_expiring_before_publication_is_rejected(kind, monkeypatch, clock):
    provider = make_provider(kind, monkeypatch, 'publication-' + kind)
    finish = provider._state.finish

    def delayed_finish(*args, **kwargs):
        clock.now = 101.0
        return finish(*args, **kwargs)

    monkeypatch.setattr(provider._state, 'finish', delayed_finish)
    with pytest.raises(OAuthError, match='expired'):
        acquire(kind, provider)
    assert provider._state.token is None


@pytest.mark.parametrize('kind', ['sync', 'async'])
def test_token_expiring_before_waiter_delivery_is_rejected(kind, monkeypatch, clock):
    provider = make_provider(kind, monkeypatch, 'delivery-' + kind)
    result = oauth_cache.Flight.result

    def delayed_result(flight):
        clock.now = 101.0
        return result(flight)

    monkeypatch.setattr(oauth_cache.Flight, 'result', delayed_result)
    with pytest.raises(OAuthError, match='expired'):
        acquire(kind, provider)


@pytest.mark.parametrize('kind', ['sync', 'async'])
def test_valid_short_lived_token_is_delivered_without_reuse(kind, monkeypatch, clock):
    provider = make_provider(kind, monkeypatch, 'valid-delivery-' + kind)
    assert acquire(kind, provider) == 'test-only-token'
    assert provider._state.token is None


def test_each_waiter_rechecks_expiry_and_short_lived_token_is_not_cached(monkeypatch, clock):
    provider = make_provider('sync', monkeypatch, 'each-waiter')
    first = provider._state.select(110)
    second = provider._state.select(110)
    assert first.flight is second.flight
    provider._start_refresh(first.flight)
    assert first.flight.done.wait(2)
    assert first.flight.result() == 'test-only-token'
    assert provider._state.token is None
    clock.now = 101.0
    with pytest.raises(OAuthError, match='expired'):
        second.flight.result()
