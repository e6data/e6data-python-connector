"""Opt-in real service connection qualification; no synthetic transport."""
import asyncio

from e6data_python_connector.aio import AsyncConnection


def test_real_async_session_and_discovery(live_config):
    async def run():
        async with AsyncConnection(**live_config.connection_kwargs) as connection:
            session = await connection.get_session_id()
            if connection._oauth_enabled:
                assert session == ''
            else:
                assert session
            schemas = await connection.get_schema_names(connection.catalog)
            assert isinstance(schemas, list)
            if live_config.schema_name:
                assert live_config.schema_name in schemas
                tables = await connection.get_tables(connection.catalog, live_config.schema_name)
                assert isinstance(tables, list)
                if tables:
                    columns = await connection.get_columns(connection.catalog, live_config.schema_name, tables[0])
                    assert all(set(column) == {'fieldName', 'fieldType'} for column in columns)
    asyncio.run(run())
