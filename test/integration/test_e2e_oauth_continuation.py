"""Real issuer renewal with an existing query handle, without fault injection.

Invalidating the local cache forces real acquisition. This does not claim
natural token expiry, server rejection, or continuation across server batches.
"""
import asyncio

import pytest

from e6data_python_connector.aio import AsyncConnection


def test_async_real_token_renewal_preserves_query_continuation(live_config):
    if not all(live_config.connection_kwargs.get(key) for key in
               ('client_id', 'client_secret', 'token_url')):
        pytest.skip('Requires the configured real client-credentials provider')

    async def run():
        options = dict(live_config.connection_kwargs)
        options.update(auto_resume=False, operation_timeout=10,
                       oauth_timeout=10, cleanup_timeout=5)
        async with asyncio.timeout(45):
            async with AsyncConnection(**options) as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute('SELECT 17 AS result_number')
                    handle = cursor.query_id
                    route = cursor._route
                    provider = connection._token_provider
                    await provider.invalidate()
                    assert provider._access_token is None
                    assert await cursor.fetchone() == [[17]]
                    assert cursor.query_id == handle
                    assert cursor._route == route
                    assert provider._access_token is not None
                    # Force another acquisition while the same query remains open.
                    # Status is a real authenticated RPC even if all rows buffered.
                    await provider.invalidate()
                    assert isinstance((await cursor.status()).status, bool)
                    assert provider._access_token is not None
                    assert await cursor.fetchall() == []
                    assert cursor.query_id == handle
                    await cursor.clear()
                assert cursor.cleanup_error is None
    asyncio.run(run())


def test_sync_configured_catalog_dry_run(live_config):
    """Real V2 dry-run; the secure runner supplies the process time limit."""
    from e6data_python_connector import Connection

    if not live_config.connection_kwargs.get('catalog'):
        pytest.skip('Requires a configured real catalog')
    options = dict(live_config.connection_kwargs)
    options['auto_resume'] = False
    with Connection(**options) as connection:
        result = connection.dry_run('SELECT 17 AS result_number')
        assert isinstance(result, str) and result.strip()
