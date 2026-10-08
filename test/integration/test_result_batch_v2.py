"""Explicit real-engine V1/V2 fetch parity. No synthetic successful server."""
import asyncio
import json
from pathlib import Path

import pytest

from test.integration.result_batch_benchmark_support import FetchMetrics, RowVerifier, connection_options


@pytest.fixture
def result_batch_expectations(pytestconfig):
    raw = json.loads(Path(pytestconfig.getoption("--integration-config")).read_text(encoding="utf-8"))
    expectations = raw.get("result_batch_v2")
    if expectations is None:
        pytest.skip("Result Batch V2 qualification requires explicit protocol and ordering evidence")
    if (not isinstance(expectations, dict) or expectations.get("expected_protocol") not in ("v1", "v2")
            or not isinstance(expectations.get("ordered_results"), bool)):
        pytest.fail("result_batch_v2 requires expected_protocol v1/v2 and boolean ordered_results", pytrace=False)
    return expectations


def _assert_results(rows, expected, ordered):
    mode = "ordered_sha256" if ordered else "unordered_sha256_sum"
    actual, baseline = RowVerifier(mode), RowVerifier(mode)
    actual.add(rows)
    baseline.add(expected)
    assert actual.count == baseline.count, "Result row count changed"
    assert actual.digest == baseline.digest, "Result contents or required order changed"


def _assert_protocol(metrics, enabled, expectations):
    expected = expectations["expected_protocol"] if enabled else "v1"
    assert metrics.rpc_count > 0, "Real fetch diagnostics are unavailable"
    assert metrics.successful_protocols == {expected}, "Configured protocol was not exercised"
    if enabled and expected == "v1":
        assert metrics.statuses["unimplemented"] == 1
        assert metrics.fallback_count == 1


@pytest.mark.parametrize("api", ["sync", "async"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("form", ["mixed", "fetchmany", "fetchall_buffer"])
def test_real_result_batch_fetch_parity(live_config, result_batch_expectations, api, enabled, form):
    options = connection_options(live_config.connection_kwargs, api, enabled)

    async def async_fetch():
        from e6data_python_connector.aio import AsyncConnection
        async with AsyncConnection(**options) as connection:
            async with connection.cursor() as cursor:
                await cursor.execute(live_config.read_only_sql)
                rows = []
                if form == "mixed":
                    rows.extend(await cursor.fetchone() or [])
                    rows.extend(await cursor.fetchmany(3))
                    rows.extend(await cursor.fetchall())
                elif form == "fetchall_buffer":
                    async for batch in cursor.fetchall_buffer():
                        rows.extend(batch)
                else:
                    while batch := await cursor.fetchmany(3):
                        rows.extend(batch)
                assert await cursor.fetch_batch() is None
                await cursor.clear()
                assert cursor.query_id is None
                return rows

    with FetchMetrics() as metrics:
        if api == "async":
            rows = asyncio.run(async_fetch())
        else:
            from e6data_python_connector import Connection
            with Connection(**options) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(live_config.read_only_sql)
                    rows = []
                    if form == "mixed":
                        rows.extend(cursor.fetchone() or [])
                        rows.extend(cursor.fetchmany(3))
                        rows.extend(cursor.fetchall())
                    elif form == "fetchall_buffer":
                        for batch in cursor.fetchall_buffer():
                            rows.extend(batch)
                    else:
                        while batch := cursor.fetchmany(3):
                            rows.extend(batch)
                    assert cursor.fetch_batch() is None
                    cursor.clear()
    _assert_results(rows, live_config.expected_rows, result_batch_expectations["ordered_results"])
    _assert_protocol(metrics, enabled, result_batch_expectations)


@pytest.mark.parametrize("enabled", [False, True])
def test_real_result_batch_sqlalchemy(live_config, result_batch_expectations, enabled):
    from sqlalchemy import create_engine, text
    from sqlalchemy.ext.asyncio import create_async_engine
    options = dict(live_config.connection_kwargs, enable_result_batch_v2=enabled)
    ordered = result_batch_expectations["ordered_results"]
    engine = create_engine("e6data://", connect_args=options)
    try:
        with engine.connect() as connection:
            for stream in (False, True):
                with connection.execution_options(stream_results=stream).execute(text(live_config.read_only_sql)) as result:
                    _assert_results(result, live_config.expected_rows, ordered)
    finally:
        engine.dispose()

    async def run():
        engine = create_async_engine("e6data+asyncio://", connect_args=connection_options(
            live_config.connection_kwargs, "async", enabled))
        try:
            async with engine.connect() as connection:
                result = await connection.execute(text(live_config.read_only_sql))
                _assert_results(result, live_config.expected_rows, ordered)
                async with connection.stream(text(live_config.read_only_sql)) as result:
                    rows = [list(row) async for row in result]
                    _assert_results(rows, live_config.expected_rows, ordered)
        finally:
            await engine.dispose()
    asyncio.run(run())
