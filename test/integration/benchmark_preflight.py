"""Explicit-only metadata preflight for the user-approved table benchmark."""
import asyncio
import json

from e6data_python_connector.aio import AsyncConnection


def test_benchmark_table_preflight(live_config):
    async def run():
        options = dict(live_config.connection_kwargs)
        options.update(auto_resume=False, operation_timeout=15, cleanup_timeout=5)
        async with asyncio.timeout(45):
            async with AsyncConnection(**options) as connection:
                columns = await connection.get_columns('vishal1', 'tpcds_1000_delta', 'date_dim')
                names = {column['fieldName'] for column in columns}
                required = {'d_date_sk', 'd_year', 'd_moy', 'd_dom'}
                assert required.issubset(names)
                query = ('SELECT d_date_sk, d_year, d_moy, d_dom '
                         'FROM vishal1.tpcds_1000_delta.date_dim '
                         'ORDER BY d_date_sk LIMIT 1000')
                async with connection.cursor() as cursor:
                    await cursor.execute(query)
                    rows = await cursor.fetchall()
                    assert len(rows) == 1000
                    assert all(len(row) == 4 for row in rows)
                    await cursor.clear()
                print(json.dumps({'table': 'vishal1.tpcds_1000_delta.date_dim',
                                  'columns': sorted(required), 'rows': len(rows),
                                  'query': query}))
    asyncio.run(run())
