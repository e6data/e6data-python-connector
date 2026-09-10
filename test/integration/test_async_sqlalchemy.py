"""Opt-in SQLAlchemy integration with real service settings and no substitutes."""
import asyncio

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.util.concurrency import greenlet_spawn


def test_real_async_sqlalchemy_surface(live_config):
    async def run():
        engine = create_async_engine('e6data+asyncio://',
                                     connect_args=dict(live_config.connection_kwargs),
                                     pool_pre_ping=True, pool_size=1, max_overflow=0)
        try:
            async with engine.connect() as conn:
                rows = (await conn.execute(text(live_config.read_only_sql))).all()
                assert [list(row) for row in rows] == live_config.expected_rows
                async with conn.stream(text(live_config.read_only_sql)) as stream:
                    streamed = [list(row) async for row in stream]
                assert streamed == live_config.expected_rows
                async with conn.stream(text(live_config.read_only_sql)) as stream:
                    row = await stream.fetchone()
                    assert (list(row) if row is not None else None) == (
                        live_config.expected_rows[0] if live_config.expected_rows else None)
                schemas = await conn.run_sync(lambda sync: inspect(sync).get_schema_names())
                if live_config.schema_name:
                    assert live_config.schema_name in schemas
                    tables = await conn.run_sync(lambda sync: inspect(sync).get_table_names(schema=live_config.schema_name))
                    if tables:
                        columns = await conn.run_sync(lambda sync: inspect(sync).get_columns(tables[0], schema=live_config.schema_name))
                        assert all('name' in column and 'type' in column for column in columns)
                # DBAPI executemany uses the supplied read-only SQL unchanged.
                raw = await conn.get_raw_connection()
                cursor = raw.dbapi_connection.cursor()
                try:
                    await greenlet_spawn(cursor.executemany, live_config.read_only_sql, [None, None])
                    assert [list(row) for row in cursor.fetchall()] == live_config.expected_rows
                finally:
                    await greenlet_spawn(cursor.close)
            # A second checkout exercises real pool pre-ping and prior reset.
            async with engine.connect() as conn:
                assert [list(row) for row in (await conn.execute(text(live_config.read_only_sql))).all()] == live_config.expected_rows
        finally:
            await engine.dispose()
    asyncio.run(run())
