"""Token response syntax checks using explicit local HTTP response test doubles."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from e6data_python_connector.async_oauth import AsyncClientCredentialsTokenProvider
from e6data_python_connector.exceptions import OAuthError
from e6data_python_connector.oauth import ClientCredentialsTokenProvider


class Response:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, limit):
        return self.body[:limit]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def aiter_bytes(self, chunk_size):
        yield self.body


INVALID_JSON = [
    b'{"access_token":"first","access_token":"last","token_type":"Bearer","expires_in":300}',
    b'{"access_token":"fixture","token_type":"Bearer","expires_in":300,"extra":NaN}',
    b'{"access_token":"fixture","token_type":"Bearer","expires_in":300,"extra":Infinity}',
    b'{"access_token":"fixture","token_type":"Bearer","expires_in":300,"extra":-Infinity}',
    b'{"access_token":"fixture","token_type":"Bearer","expires_in":300,"extra":{"a":1,"a":2}}',
    b'{"access_token":"fixture","token_type":"Bearer","expires_in":300} trailing',
    b'{"access_token":"\xff","token_type":"Bearer","expires_in":300}',
]


@pytest.mark.parametrize('body', INVALID_JSON)
@pytest.mark.parametrize('asynchronous', [False, True])
def test_token_transports_reject_ambiguous_or_non_json_syntax(body, asynchronous):
    response = Response(body)
    if asynchronous:
        async def run():
            provider = AsyncClientCredentialsTokenProvider('https://issuer.invalid/token', 'fixture-client', 'fixture-secret')
            provider._client = SimpleNamespace(stream=lambda *args, **kwargs: response)
            with pytest.raises(OAuthError, match='valid JSON') as caught:
                await provider._fetch_token(time.monotonic() + 1)
            assert 'fixture-secret' not in str(caught.value)
            assert 'access_token' not in str(caught.value)
        asyncio.run(run())
    else:
        provider = ClientCredentialsTokenProvider('https://issuer.invalid/token', 'fixture-client', 'fixture-secret')
        provider._opener = SimpleNamespace(open=lambda *args, **kwargs: response)
        with pytest.raises(OAuthError, match='valid JSON') as caught:
            provider._fetch_token(time.monotonic() + 1)
        assert 'fixture-secret' not in str(caught.value)
        assert 'access_token' not in str(caught.value)


@pytest.mark.parametrize('asynchronous', [False, True])
def test_valid_json_extensions_remain_supported(asynchronous):
    response = Response(b'{"access_token":"fixture","token_type":"Bearer","expires_in":300,"extra":{"enabled":true,"data":[null,1,1.5]}}')
    if asynchronous:
        async def run():
            provider = AsyncClientCredentialsTokenProvider('https://issuer.invalid/token', 'fixture-client', 'fixture-secret')
            provider._client = SimpleNamespace(stream=lambda *args, **kwargs: response)
            return await provider._fetch_token(time.monotonic() + 1)
        payload = asyncio.run(run())
    else:
        provider = ClientCredentialsTokenProvider('https://issuer.invalid/token', 'fixture-client', 'fixture-secret')
        provider._opener = SimpleNamespace(open=lambda *args, **kwargs: response)
        payload = provider._fetch_token(time.monotonic() + 1)
    assert payload['access_token'] == 'fixture'
    assert payload['extra'] == {'enabled': True, 'data': [None, 1, 1.5]}
