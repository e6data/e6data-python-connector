"""Pure OAuth validation and admission regression tests, with no test services."""
import math
import time
import pytest
from e6data_python_connector.exceptions import OAuthError
from e6data_python_connector.oauth import ClientCredentialsTokenProvider


def validate(payload, **kwargs):
    from e6data_python_connector.oauth_common import validate_token_response
    return validate_token_response(payload, started_at=100.0, now=kwargs.get('now', 101.0), leeway=60.0)


@pytest.mark.parametrize('lifetime', [None, True, False, 0, -1, 1.5, '3600', math.inf, 10**400])
def test_invalid_lifetime_is_rejected(lifetime):
    with pytest.raises(OAuthError):
        validate({'access_token': 'unit-input', 'token_type': 'Bearer', 'expires_in': lifetime})


@pytest.mark.parametrize('payload', [None, [], {}, {'access_token': 123},
    {'access_token': 'unit-input', 'expires_in': 3600},
    {'access_token': 'unit-input', 'token_type': 'MAC', 'expires_in': 3600},
    {'access_token': 'has\nnewline', 'token_type': 'Bearer', 'expires_in': 3600}])
def test_invalid_response_shape_is_rejected(payload):
    with pytest.raises(OAuthError):
        validate(payload)


def test_exchange_start_determines_reusable_deadline():
    assert validate({'access_token': 'unit-input', 'token_type': 'bearer', 'expires_in': 3600}, now=150) == ('unit-input', 3640)


def test_short_lifetime_is_returned_uncached():
    token, until = validate({'access_token': 'unit-input', 'token_type': 'Bearer', 'expires_in': 30})
    assert token == 'unit-input'
    assert until <= 101


def test_response_expired_in_transit_is_rejected():
    with pytest.raises(OAuthError):
        validate({'access_token': 'unit-input', 'token_type': 'Bearer', 'expires_in': 30}, now=131)


@pytest.mark.parametrize('url', ['http://example.com/token', 'https://u:p@example.com/token',
    'https://example.com/token#fragment', 'https:///token', 'https://example.com:bad/token',
    'https://example.com/\ntoken'])
def test_unsafe_endpoint_is_rejected_locally(url):
    with pytest.raises(ValueError):
        ClientCredentialsTokenProvider(url, 'unit-client', 'unit-secret')


@pytest.mark.parametrize('timeout', [0, -1, math.inf, math.nan, True])
def test_unbounded_timeout_is_rejected_locally(timeout):
    with pytest.raises(ValueError):
        ClientCredentialsTokenProvider('https://example.com/token', 'unit-client', 'unit-secret', timeout=timeout)


def test_lock_wait_is_bounded_without_caller_deadline():
    provider = ClientCredentialsTokenProvider('https://example.com/token', 'unit-client', 'unit-secret', timeout=.02)
    flight = provider._state.select(time.monotonic() + 1).flight
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError):
            provider.get_token()
        assert time.monotonic() - started < .1
    finally:
        provider._state.finish(flight, error=TimeoutError())


def test_invalidation_is_shared_even_during_refresh():
    provider = ClientCredentialsTokenProvider('https://example.com/token', 'unit-client', 'unit-secret')
    flight = provider._state.select(time.monotonic() + 1).flight
    provider.invalidate()
    provider._state.finish(flight, 'invalidated-input', time.monotonic() + 3600)
    assert provider._access_token is None
    assert provider._expires_at == 0


def test_rejected_token_is_dropped_before_capacity_timeout():
    from e6data_python_connector.oauth import _EXCHANGE_SLOTS
    provider = ClientCredentialsTokenProvider('https://example.com/token', 'unit-client', 'unit-secret', timeout=.02)
    provider._access_token = 'rejected-input'
    provider._expires_at = time.monotonic() + 3600
    for _ in range(4):
        assert _EXCHANGE_SLOTS.acquire(blocking=False)
    try:
        with pytest.raises(TimeoutError):
            provider.get_token(force_refresh=True, rejected_token='rejected-input')
        assert provider._access_token is None
        assert not _EXCHANGE_SLOTS.acquire(blocking=False)
        assert provider._state._flight is None
    finally:
        for _ in range(4):
            _EXCHANGE_SLOTS.release()


@pytest.mark.parametrize('now', [99, math.inf, math.nan])
def test_invalid_monotonic_clock_arithmetic_is_rejected(now):
    with pytest.raises(OAuthError):
        validate({'access_token': 'unit-input', 'token_type': 'Bearer', 'expires_in': 3600}, now=now)


def test_redirect_handler_rejects_without_dispatch():
    from e6data_python_connector.oauth import _RejectRedirects
    with pytest.raises(OAuthError, match='redirects'):
        _RejectRedirects().redirect_request(None, None, 302, None, None, 'https://other.example/token')
