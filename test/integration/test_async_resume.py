"""Opt-in recovery on an externally suspended exclusive-use real target.

The operator must prepare the suspended target before opting in. This case never
suspends or changes target configuration and does not prove historical state.
"""
import asyncio
import os

import pytest


@pytest.mark.integration
def test_real_async_resume_and_query(live_config):
    if os.environ.get('E6_ASYNC_RESUME_AUTHORIZED') != '1':
        pytest.skip('Requires explicit E6_ASYNC_RESUME_AUTHORIZED=1 for a prepared target')

    async def run():
        from e6data_python_connector.aio import connect
        kwargs = dict(live_config.connection_kwargs)
        kwargs['auto_resume'] = True
        async with await connect(**kwargs) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(live_config.read_only_sql)
                rows = await cursor.fetchall()
                assert [list(row) for row in rows] == live_config.expected_rows
    asyncio.run(run())
