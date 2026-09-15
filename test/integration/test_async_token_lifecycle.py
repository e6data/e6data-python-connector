"""Opt-in real issuer acquisition; no synthetic issuer or invented proxy protocol."""
import asyncio
import unittest

import pytest


class RealAsyncTokenLifecycle(unittest.IsolatedAsyncioTestCase):
    @pytest.fixture(autouse=True)
    def configure(self, live_config):
        self.live_config = live_config

    async def test_parallel_real_issuer_acquisition(self):
        kwargs = self.live_config.connection_kwargs
        if not all(kwargs.get(key) for key in ('token_url', 'client_id', 'client_secret')):
            self.skipTest('Real client-credentials issuer configuration required')
        from e6data_python_connector.async_oauth import AsyncClientCredentialsTokenProvider
        provider = AsyncClientCredentialsTokenProvider(
            kwargs['token_url'], kwargs['client_id'], kwargs['client_secret'],
            scope=kwargs.get('oauth_scope'), client_auth_method=kwargs.get('client_auth_method', 'basic'))
        try:
            tokens = await asyncio.gather(*(provider.get_token() for _ in range(20)))
            # Do not include credential values in assertion diagnostics.
            self.assertTrue(all(token == tokens[0] for token in tokens))
            self.assertTrue(all(isinstance(token, str) and bool(token) for token in tokens))
            await provider.invalidate()
            self.assertIsNone(provider._access_token)
            replacement = await provider.get_token(force_refresh=True)
            self.assertTrue(isinstance(replacement, str) and bool(replacement))
            # Issuers may return an identical bearer within one issuance window.
            # Validate publication, not token inequality or assumed revocation.
            self.assertTrue(provider._task.done())
        finally:
            await provider.close()
        self.assertTrue(provider._client.is_closed)
