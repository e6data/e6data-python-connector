"""Explicit-only issuer lifetime probe. Never prints a token or identity claims."""
import asyncio
import base64
import json
import time

from e6data_python_connector.async_oauth import AsyncClientCredentialsTokenProvider


def test_real_issuer_declared_lifetime(live_config):
    async def run():
        options = live_config.connection_kwargs
        provider = AsyncClientCredentialsTokenProvider(
            options['token_url'], options['client_id'], options['client_secret'],
            scope=options.get('oauth_scope'),
            client_auth_method=options.get('client_auth_method', 'basic'),
        )
        try:
            token = await provider.get_token()
            parts = token.split('.')
            if len(parts) != 3:
                raise ValueError('Issuer token has no inspectable JWT lifetime')
            claims = json.loads(base64.urlsafe_b64decode(parts[1] + '=' * (-len(parts[1]) % 4)))
            expiry, issued = claims.get('exp'), claims.get('iat')
            if not all(isinstance(value, (int, float)) for value in (expiry, issued)):
                raise ValueError('Issuer token has no numeric issuance/expiry timestamps')
            print(json.dumps({
                'observation': 'issuer_declared_lifetime_not_receiver_expiry_proof',
                'issued_at_epoch': issued,
                'expires_at_epoch': expiry,
                'declared_lifetime_seconds': expiry - issued,
                'remaining_seconds': max(0, expiry - time.time()),
                'local_reuse_remaining_seconds': max(0, provider._expires_at - time.monotonic()),
            }))
        finally:
            await provider.close()
    asyncio.run(run())
