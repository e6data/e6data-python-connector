"""Real issuer sharing across distinct pools, threads and event loops."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import threading

from e6data_python_connector.connection_pool import ConnectionPool
from e6data_python_connector.async_connection_pool import AsyncConnectionPool
from e6data_python_connector.oauth import ClientCredentialsTokenProvider
from e6data_python_connector.async_oauth import AsyncClientCredentialsTokenProvider
from test.integration.token_observation import FetchObservation, provider_options, token_digest


def test_real_sync_pools_share_one_issuer_exchange_across_threads(live_config):
    options = dict(live_config.connection_kwargs, auto_resume=False)
    pools = [ConnectionPool(min_size=2, max_size=2, max_overflow=0, timeout=10,
                            **options) for _ in range(2)]
    try:
        providers = [connection.connection._token_provider for pool in pools
                     for connection in pool._all_connections]
        assert len(providers) == 4
        assert len({id(provider) for provider in providers}) == 4
        providers[0].invalidate()
        barrier = threading.Barrier(4, timeout=15)
        def acquire(index):
            with pools[index % 2].get_connection_context() as lease:
                barrier.wait()
                return token_digest(lease.connection._token_provider.get_token())
        with FetchObservation() as observation:
            with ThreadPoolExecutor(max_workers=4) as workers:
                values = list(workers.map(acquire, range(4)))
            assert len(set(values)) == 1
            assert observation.count == 1
            pools[0].close_all()
            with pools[1].get_connection_context() as lease:
                assert token_digest(lease.connection._token_provider.get_token()) == values[0]
            assert observation.count == 1
        print(json.dumps({'sharing': 'two_sync_pools_four_threads', 'issuer_exchanges': 1}))
    finally:
        for pool in pools:
            pool.close_all()


def test_real_async_pools_share_one_issuer_exchange(live_config):
    async def run():
        options = dict(live_config.connection_kwargs, auto_resume=False,
                       operation_timeout=10, cleanup_timeout=5)
        pools = [AsyncConnectionPool(min_size=0, max_size=2, max_overflow=0,
                                     timeout=10, **options) for _ in range(2)]
        async with asyncio.timeout(45):
            try:
                for pool in pools:
                    await pool.open()
                assert pools[0]._token_provider is not pools[1]._token_provider
                await pools[0]._token_provider.invalidate()
                async def acquire(index):
                    async with pools[index % 2].get_connection_context():
                        return token_digest(await pools[index % 2]._token_provider.get_token())
                with FetchObservation() as observation:
                    values = await asyncio.gather(*(acquire(i) for i in range(4)))
                    assert len(set(values)) == 1
                    assert observation.count == 1
                    await pools[0].close_all()
                    assert token_digest(await pools[1]._token_provider.get_token()) == values[0]
                    assert observation.count == 1
                print(json.dumps({'sharing': 'two_async_pools_four_tasks', 'issuer_exchanges': 1}))
            finally:
                await asyncio.gather(*(pool.close_all() for pool in pools))
    asyncio.run(run())


def test_real_sync_and_async_loop_threads_share_issuer_exchange(live_config):
    options = provider_options(live_config)
    control = ClientCredentialsTokenProvider(**options)
    control.invalidate()
    barrier = threading.Barrier(3, timeout=15)
    def worker(index):
        if index == 0:
            provider = ClientCredentialsTokenProvider(**options)
            barrier.wait()
            return token_digest(provider.get_token())
        async def run():
            provider = AsyncClientCredentialsTokenProvider(**options)
            try:
                await asyncio.to_thread(barrier.wait)
                return token_digest(await provider.get_token())
            finally:
                await provider.close()
        return asyncio.run(run())
    with FetchObservation() as observation:
        with ThreadPoolExecutor(max_workers=3) as workers:
            values = list(workers.map(worker, range(3)))
        assert len(set(values)) == 1
        assert observation.count == 1
        assert token_digest(control.get_token()) == values[0]
        assert observation.count == 1
    print(json.dumps({'sharing': 'sync_and_two_async_loop_threads', 'issuer_exchanges': 1}))
