"""Application-owned async query helpers, without embedded configuration.

Import these functions and pass your own connection dictionary and SQL. They do
not create credentials, endpoints or expected results. Requires Python 3.11+ and
the connector's async extra. Close contexts even when consumption stops early.
"""
from contextlib import aclosing

from e6data_python_connector.aio import AsyncConnection, AsyncConnectionPool


async def fetch_rows(config, sql, parameters=None):
    """Return complete rows or propagate an incomplete/ambiguous result error."""
    async with AsyncConnection(**config) as connection:
        async with connection.cursor() as cursor:
            await cursor.execute(sql, parameters)
            return await cursor.fetchall()


async def consume_batches(config, sql, consume_batch):
    """Call the application's async consumer once for each complete batch."""
    async with AsyncConnection(**config) as connection:
        async with connection.cursor() as cursor:
            query_id = await cursor.execute(sql)
            async with aclosing(cursor.fetchall_buffer()) as batches:
                async for batch in batches:
                    await consume_batch(query_id, batch)


async def fetch_with_pool(config, sql):
    """Keep every cursor inside the acquiring task's active lease."""
    async with AsyncConnectionPool(min_size=0, max_size=4,
                                   max_overflow=0, **config) as pool:
        async with pool.get_connection_context() as lease:
            async with lease.cursor() as cursor:
                await cursor.execute(sql)
                return await cursor.fetchall()
