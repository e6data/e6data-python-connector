"""Opt-in deterministic read-only success cases missing from the original suite.

Root owns live configuration and the external 180-second run cap. Native async
cases also enforce their own aggregate deadline. No resume or fault injection.
"""
import asyncio

import pytest

from e6data_python_connector import Connection
from e6data_python_connector.aio import AsyncConnection


PARAMETER_SQL = 'SELECT %(number)s AS result_number, %(label)s AS result_label'
PARAMETERS = {'number': 17, 'label': "e2e's literal"}
PARAMETER_ROWS = [[17, "e2e's literal"]]
ORDERED_SQL = ('SELECT 1 AS result_number UNION ALL SELECT 2 AS result_number '
               'UNION ALL SELECT 3 AS result_number ORDER BY result_number')
ORDERED_ROWS = [[1], [2], [3]]
EMPTY_SQL = ('SELECT result_number FROM (SELECT 1 AS result_number) AS empty_input '
             'WHERE 1 = 0')


def _connection_options(live_config, version, *, native=False):
    options = dict(live_config.connection_kwargs)
    if version == 'v2' and not options.get('catalog'):
        pytest.skip('V2 qualification requires a configured real catalog')
    if version == 'v1':
        # V1 has no catalog field on the wire. A missing server default catalog
        # must remain a qualification failure, not become a skip or a V2 call.
        options['catalog'] = ''
    options['auto_resume'] = False
    grpc_options = dict(options.get('grpc_options') or {})
    grpc_options['grpc_prepare_timeout'] = 15
    options['grpc_options'] = grpc_options
    if native:
        options.update(operation_timeout=15, cleanup_timeout=5)
    return options


def _assert_description(description, names):
    assert description is not None
    assert [column[0].lower() for column in description] == names


@pytest.mark.parametrize('version', ['v1', 'v2'])
def test_sync_parameter_success_metadata_status_and_cleanup(live_config, version):
    with Connection(**_connection_options(live_config, version)) as connection:
        cursor = connection.cursor()
        try:
            handle = cursor.execute(PARAMETER_SQL, PARAMETERS)
            assert isinstance(handle, str) and handle
            assert cursor.query_id == handle
            assert cursor.fetchone() == PARAMETER_ROWS
            assert cursor.fetchall() == []
            assert cursor.rowcount == 1
            _assert_description(cursor.description, ['result_number', 'result_label'])
            assert isinstance(cursor.status(handle).status, bool)
            explanation = cursor.explain()
            assert isinstance(explanation, str) and explanation.strip()
            cursor.clear(timeout=5)
            if connection._uses_oauth:
                assert cursor.query_id is None
        finally:
            cursor.close(timeout=5)
        assert cursor._cleanup_error is None


@pytest.mark.parametrize('version', ['v1', 'v2'])
def test_async_parameter_executemany_and_explanation_success(live_config, version):
    async def run():
        async with asyncio.timeout(45):
            async with AsyncConnection(**_connection_options(live_config, version, native=True)) as connection:
                async with connection.cursor() as cursor:
                    assert await cursor.execute(PARAMETER_SQL, PARAMETERS)
                    assert await cursor.fetchall() == PARAMETER_ROWS
                    assert await cursor.get_rowcount() == 1
                    _assert_description(await cursor.get_description(), ['result_number', 'result_label'])
                    assert isinstance((await cursor.status()).status, bool)
                    explanation = await cursor.explain()
                    assert isinstance(explanation, str) and explanation.strip()
                    analysis = await cursor.explain_analyse()
                    assert isinstance(analysis['is_cached'], bool)
                    assert isinstance(analysis['planner'], str)
                    await cursor.clear()
                    assert cursor.query_id is None
                    assert await cursor.executemany(PARAMETER_SQL, [
                        {'number': 1, 'label': 'intermediate'},
                        {'number': 29, 'label': 'final'},
                    ]) is None
                    assert await cursor.fetchall() == [[29, 'final']]
                    await cursor.clear()
                assert cursor.cleanup_error is None
                assert not connection._routes
                assert not connection._ambiguous_submissions
    asyncio.run(run())


def test_sync_ordered_fetch_forms_and_empty_result(live_config):
    with Connection(**_connection_options(live_config, 'configured')) as connection:
        for form in ('mixed', 'batch', 'buffer', 'iterator', 'empty'):
            cursor = connection.cursor()
            try:
                cursor.execute(EMPTY_SQL if form == 'empty' else ORDERED_SQL)
                if form == 'mixed':
                    rows = (cursor.fetchone() or []) + cursor.fetchmany(1) + cursor.fetchall()
                    assert cursor.fetchone() is None
                elif form == 'batch':
                    rows = []
                    while True:
                        batch = cursor.fetch_batch()
                        if not batch:
                            break
                        rows.extend(batch)
                elif form == 'buffer':
                    rows = [row for batch in cursor.fetchall_buffer() for row in batch]
                elif form == 'iterator':
                    rows = [row for one in cursor for row in one]
                else:
                    assert cursor.fetchone() is None
                    rows = cursor.fetchall()
                assert rows == ([] if form == 'empty' else ORDERED_ROWS)
                cursor.clear(timeout=5)
            finally:
                cursor.close(timeout=5)
            assert cursor._cleanup_error is None


def test_async_connection_dry_run_configured_catalog(live_config):
    # Exercise the configured catalog through the public dry-run API.
    async def run():
        async with asyncio.timeout(25):
            async with AsyncConnection(
                **_connection_options(live_config, 'configured', native=True)
            ) as connection:
                result = await connection.dry_run('SELECT 1 AS result_number')
                assert isinstance(result, str)
            assert connection.cleanup_error is None
    asyncio.run(run())


def test_async_cursor_discovery_and_connection_reopen(live_config):
    async def run():
        async with asyncio.timeout(45):
            connection = AsyncConnection(**_connection_options(live_config, 'configured', native=True))
            try:
                await connection.open()
                async with connection.cursor(db_name=live_config.schema_name) as cursor:
                    schemas = await cursor.get_schema_names()
                    assert isinstance(schemas, list)
                    schema = live_config.schema_name or connection.database
                    if schema:
                        if live_config.schema_name:
                            assert schema in schemas
                        tables = await cursor.get_tables()
                        assert isinstance(tables, list)
                        if tables:
                            # Metadata only for one discovered table; never query table data.
                            columns = await cursor.get_columns(tables[0])
                            assert columns
                            assert all(isinstance(column['fieldName'], str) and
                                       isinstance(column['fieldType'], str) for column in columns)
                assert cursor.cleanup_error is None
                await connection.reopen()
                async with connection.cursor() as cursor:
                    await cursor.execute('SELECT 7 AS result_number')
                    assert await cursor.fetchall() == [[7]]
                    await cursor.clear()
                assert cursor.cleanup_error is None
            finally:
                await connection.close()
            assert connection.cleanup_error is None
    asyncio.run(run())
