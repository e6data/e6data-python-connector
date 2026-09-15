"""Read-only native async query qualification against the explicitly supplied target."""
import asyncio

from e6data_python_connector.aio import AsyncConnection


def test_real_async_query_metadata_and_mixed_fetch(live_config):
    async def run():
        async with AsyncConnection(**live_config.connection_kwargs) as connection:
            async with connection.cursor() as cursor:
                assert await cursor.execute(live_config.read_only_sql)
                assert cursor.query_id
                assert await cursor.get_description() is not None
                assert isinstance(await cursor.get_rowcount(), int)
                assert isinstance((await cursor.status()).status, bool)
                first = await cursor.fetchone() or []
                rest = await cursor.fetchall()
                assert first + rest == live_config.expected_rows
                assert await cursor.fetchone() is None
                await cursor.clear()
                assert cursor.query_id is None
    asyncio.run(run())


def test_real_async_fetch_forms_and_reuse_after_clear(live_config):
    async def run():
        async with AsyncConnection(**live_config.connection_kwargs) as connection:
            async with connection.cursor() as cursor:
                for form in ('fetchmany', 'fetch_batch', 'fetchall_buffer', 'iterator'):
                    await cursor.execute(live_config.read_only_sql)
                    rows = []
                    if form == 'fetchall_buffer':
                        async for batch in cursor.fetchall_buffer():
                            rows.extend(batch)
                    elif form == 'iterator':
                        async for one in cursor:
                            rows.extend(one)
                    else:
                        while True:
                            batch = await getattr(cursor, form)()
                            if not batch:
                                break
                            rows.extend(batch)
                    assert rows == live_config.expected_rows
                    await cursor.clear()
    asyncio.run(run())


def test_real_concurrent_cursors_keep_distinct_registered_routes(live_config):
    async def run():
        async with AsyncConnection(**live_config.connection_kwargs) as connection:
            async def query():
                async with connection.cursor() as cursor:
                    await cursor.execute(live_config.read_only_sql)
                    route = connection._routes[cursor.query_id]
                    assert route.target == connection.target
                    assert await cursor.fetchall() == live_config.expected_rows
                    assert cursor._route == route
                    return route.query_id
            handles = await asyncio.gather(query(), query())
            assert len(set(handles)) == 2
    asyncio.run(run())
