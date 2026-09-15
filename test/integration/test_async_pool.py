"""Opt-in pool qualification against the explicitly configured real receiver."""
import asyncio

from e6data_python_connector.async_connection_pool import AsyncConnectionPool
from e6data_python_connector.exceptions import ProgrammingError


def test_real_pool_parallel_queries_and_stale_lease(live_config):
    async def run():
        options = dict(live_config.connection_kwargs)
        options.update(operation_timeout=10, cleanup_timeout=5, auto_resume=False)
        # Reserve up to ten seconds for cancellation-safe worker and pool cleanup.
        # Work expires at 35 seconds, keeping the aggregate within 45 seconds.
        async with asyncio.timeout(35):
            async with AsyncConnectionPool(min_size=0, max_size=2, max_overflow=0,
                                           timeout=10, **options) as pool:
                entered, release = asyncio.Queue(), asyncio.Event()
                async def query():
                    async with pool.get_connection_context() as lease:
                        entered.put_nowait(lease)
                        await release.wait()
                        async with lease.cursor() as cursor:
                            await cursor.execute(live_config.read_only_sql)
                            rows = await cursor.fetchall()
                            if live_config.expected_rows is not None:
                                assert rows == live_config.expected_rows
                            return rows
                # TaskGroup interrupts admission waiting on any worker failure,
                # cancels its siblings and joins every worker before leaving.
                async with asyncio.TaskGroup() as workers:
                    workers.create_task(query())
                    workers.create_task(query())
                    try:
                        first, second = await entered.get(), await entered.get()
                        assert first is not second
                    finally:
                        release.set()
                old = await pool.get_connection()
                cursor = old.cursor()
                await old.close()
                new = await pool.get_connection()
                try:
                    try:
                        await cursor.execute(live_config.read_only_sql)
                    except ProgrammingError:
                        pass
                    else:
                        raise AssertionError('Stale cursor accepted execution.')
                finally:
                    await new.close()
    asyncio.run(run())
