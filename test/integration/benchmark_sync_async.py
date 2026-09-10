"""Explicit real-service benchmark; invoke this file by path with -s.

Requires E6_RUN_BENCHMARK=1 and the normal integration configuration. Three
interleaved trials of 12 configured read-only queries per mode. No token values are output.
The external runner must cap the process at 270 seconds; RPCs default to 5s.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import hashlib
import math
import os
import random
import statistics
import threading
import time

import pytest

from e6data_python_connector import Connection
from e6data_python_connector.aio import AsyncConnection


def _summary(latencies, elapsed, startup):
    ordered = sorted(latencies)
    return dict(queries=len(ordered), wall_seconds=elapsed,
                throughput_queries_per_second=len(ordered) / elapsed,
                latency_mean_seconds=statistics.mean(ordered),
                latency_p50_seconds=statistics.median(ordered),
                latency_p95_seconds=ordered[max(0, math.ceil(.95 * len(ordered)) - 1)],
                connection_startup_seconds=startup)


def _options(config):
    options = dict(config.connection_kwargs)
    options['auto_resume'] = False
    grpc_options = dict(options.get('grpc_options') or {})
    grpc_options['grpc_prepare_timeout'] = 5
    grpc_options['grpc.service_config'] = json.dumps({
        'methodConfig': [{'name': [{}], 'timeout': '5s'}]})
    options['grpc_options'] = grpc_options
    return options


def _fingerprint(rows):
    payload = json.dumps(rows, default=str, ensure_ascii=True, separators=(",", ":"))
    return len(rows), hashlib.sha256(payload.encode()).hexdigest()


def _sync_trial(options, workers, deadline, sql, expected):
    ready = threading.Barrier(workers + 1, timeout=15)
    start = threading.Event()
    stop = threading.Event()
    def worker():
        before = time.perf_counter()
        with Connection(**options) as connection:
            startup = time.perf_counter() - before
            def query():
                with connection.cursor() as cursor:
                    try:
                        cursor.execute(sql)
                        assert _fingerprint(cursor.fetchall()) == expected
                        cursor.clear(timeout=5)
                    finally:
                        cursor.close(timeout=5)
                assert cursor._cleanup_error is None
            try:
                query()  # Warm connection, authentication, and query path.
                ready.wait()
                if not start.wait(15):
                    raise TimeoutError('Benchmark start deadline exceeded')
                latencies = []
                for _ in range(12 // workers):
                    if stop.is_set() or time.monotonic() >= deadline:
                        raise TimeoutError('Benchmark time budget exceeded')
                    before = time.perf_counter()
                    query()
                    latencies.append(time.perf_counter() - before)
                return latencies, startup, time.perf_counter()
            except BaseException:
                stop.set()
                ready.abort()
                raise
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(worker) for _ in range(workers)]
        try:
            ready.wait()
            before = time.perf_counter()
            start.set()
            results = [future.result(timeout=max(.01, deadline - time.monotonic())) for future in futures]
            elapsed = max(finished for _, _, finished in results) - before
        finally:
            stop.set()
            start.set()
            for future in futures:
                future.cancel()
    return _summary([latency for rows, _, _ in results for latency in rows], elapsed,
                    [startup for _, startup, _ in results])


async def _async_trial(options, workers, deadline, sql, expected):
    options = dict(options, operation_timeout=5, oauth_timeout=5, cleanup_timeout=5)
    connections = []
    startup = []
    async def query(connection):
        async with connection.cursor() as cursor:
            await cursor.execute(sql)
            assert _fingerprint(await cursor.fetchall()) == expected
            await cursor.clear()
        assert cursor.cleanup_error is None
    try:
        for _ in range(workers):
            before = time.perf_counter()
            connection = await AsyncConnection(**options).open()
            startup.append(time.perf_counter() - before)
            connections.append(connection)
        await asyncio.gather(*(query(connection) for connection in connections))
        async def worker(connection):
            latencies = []
            for _ in range(12 // workers):
                if time.monotonic() >= deadline:
                    raise TimeoutError('Benchmark time budget exceeded')
                before = time.perf_counter()
                await query(connection)
                latencies.append(time.perf_counter() - before)
            return latencies
        before = time.perf_counter()
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(worker(connection)) for connection in connections]
        elapsed = time.perf_counter() - before
        return _summary([latency for task in tasks for latency in task.result()], elapsed, startup)
    finally:
        await asyncio.gather(*(connection.close() for connection in connections))
        assert all(connection.cleanup_error is None for connection in connections)


def test_benchmark_sync_async(live_config):
    if os.environ.get('E6_RUN_BENCHMARK') != '1':
        pytest.skip('Requires explicit E6_RUN_BENCHMARK=1')
    options = _options(live_config)
    deadline = time.monotonic() + 240
    sql = os.environ.get('E6_BENCHMARK_SQL', 'SELECT 1 AS benchmark_value')
    if not sql.lstrip().lower().startswith('select ') or ';' in sql:
        raise ValueError('Benchmark SQL must be a single SELECT statement')
    # Establish actual expected content before trials without exposing row data.
    with Connection(**options) as connection:
        with connection.cursor() as cursor:
            try:
                cursor.execute(sql)
                expected = _fingerprint(cursor.fetchall())
                cursor.clear(timeout=5)
            finally:
                cursor.close(timeout=5)
        assert cursor._cleanup_error is None
    rng = random.Random(1729)
    results = []
    for trial in range(3):
        modes = [('sync_serial', False, 1), ('async_serial', True, 1),
                 ('sync_threads_4', False, 4), ('async_tasks_4', True, 4)]
        rng.shuffle(modes)
        for order, (mode, native, workers) in enumerate(modes):
            if time.monotonic() >= deadline:
                raise TimeoutError('Benchmark time budget exceeded')
            if native:
                async def run():
                    async with asyncio.timeout(max(.01, deadline - time.monotonic())):
                        return await _async_trial(options, workers, deadline, sql, expected)
                result = asyncio.run(run())
            else:
                result = _sync_trial(options, workers, deadline, sql, expected)
            results.append(dict(trial=trial + 1, order=order + 1, mode=mode, **result))
    assert len(results) == 12
    print(json.dumps({'benchmark': 'select_fetchall_clear', 'sql': sql,
                      'rows_per_query': expected[0], 'result_sha256': expected[1],
                      'seed': 1729,
                      'warmups_per_worker_per_trial': 1,
                      'startup_excluded': True, 'trials': results}, sort_keys=True))
