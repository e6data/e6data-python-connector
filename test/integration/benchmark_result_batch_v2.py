"""Explicit real-workload benchmark, outside the default filename pattern."""
import asyncio
import json
import multiprocessing
import resource
import sys
import time
import tracemalloc

import pytest

from test.integration.result_batch_benchmark_support import FetchMetrics, RowVerifier, connection_options, load_benchmark_config
from test.integration.support import IntegrationConfigError


def _trial(config, api, enabled):
    options = connection_options(config.connection_kwargs, api, enabled)
    verifier = RowVerifier(config.verification["mode"])
    timings = {"first_row_seconds": None, "consumer_seconds": 0.0}

    def consume(batch, started):
        if batch and timings["first_row_seconds"] is None:
            timings["first_row_seconds"] = time.perf_counter() - started
        before = time.perf_counter()
        verifier.add(batch)
        timings["consumer_seconds"] += time.perf_counter() - before

    def sync_query():
        from e6data_python_connector import Connection
        with Connection(**options) as connection:
            with connection.cursor() as cursor:
                started = time.perf_counter()
                cursor.execute(config.read_only_sql)
                timings["execution_seconds"] = time.perf_counter() - started
                for batch in cursor.fetchall_buffer():
                    consume(batch, started)
                timings["total_seconds"] = time.perf_counter() - started
            if cursor._cleanup_error is not None:
                raise RuntimeError("Query cleanup unconfirmed")

    async def async_query():
        from e6data_python_connector.aio import AsyncConnection
        async with AsyncConnection(**options) as connection:
            async with connection.cursor() as cursor:
                started = time.perf_counter()
                await cursor.execute(config.read_only_sql)
                timings["execution_seconds"] = time.perf_counter() - started
                async for batch in cursor.fetchall_buffer():
                    consume(batch, started)
                timings["total_seconds"] = time.perf_counter() - started
            if cursor.cleanup_error is not None:
                raise RuntimeError("Query cleanup unconfirmed")

    tracemalloc.start()
    with FetchMetrics() as metrics:
        try:
            sync_query() if api == "sync" else asyncio.run(async_query())
            outcome = {"status": "ok"}
        except Exception as error:
            outcome = {"status": "error", "error_type": type(error).__name__}
    _, peak_heap = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != "darwin":
        peak_rss *= 1024
    if "total_seconds" in timings:
        timings["drain_seconds"] = timings["total_seconds"] - timings["execution_seconds"]
    return dict(outcome, api=api, requested_protocol="v2" if enabled else "v1",
                row_count=verifier.count, digest=verifier.digest, peak_python_heap_bytes=peak_heap,
                peak_resident_bytes=peak_rss, **timings, **metrics.summary())


def _trial_process(sender, config, api, enabled):
    try:
        sender.send(_trial(config, api, enabled))
    except BaseException as error:
        sender.send({"status": "error", "error_type": type(error).__name__,
                     "api": api, "requested_protocol": "v2" if enabled else "v1"})
    finally:
        sender.close()


def _bounded_trial(config, api, enabled, deadline):
    if time.monotonic() >= deadline:
        return {"status": "error", "error_type": "BenchmarkDeadlineExceeded",
                "api": api, "requested_protocol": "v2" if enabled else "v1",
                "worker_started": False, "cleanup_confirmed": False}
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_trial_process, args=(sender, config, api, enabled))
    process.start()
    sender.close()
    try:
        if not receiver.poll(max(0.0, deadline - time.monotonic())):
            return {"status": "error", "error_type": "BenchmarkDeadlineExceeded",
                    "api": api, "requested_protocol": "v2" if enabled else "v1",
                    "cleanup_confirmed": False}
        try:
            return receiver.recv()
        except EOFError:
            return {"status": "error", "error_type": "BenchmarkWorkerExited",
                    "api": api, "requested_protocol": "v2" if enabled else "v1"}
    finally:
        receiver.close()
        process.join(timeout=max(0.0, min(1.0, deadline - time.monotonic())))
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)
        process.close()


def test_large_result_v1_v2_benchmark(pytestconfig, record_property):
    try:
        config = load_benchmark_config(pytestconfig.getoption("--result-batch-benchmark-config"))
    except IntegrationConfigError as error:
        pytest.fail(str(error), pytrace=False)
    if config.expected_row_count <= 20_000_000 or config.planner_timeout_seconds != 900:
        pytest.fail("Qualification requires more than 20 million rows and the observed 900-second planner budget",
                    pytrace=False)
    if not config.engine_flags["ENABLE_GET_NEXT_RESULT_BATCH_V2"]:
        pytest.fail("V2 benchmark requires the externally verified planner V2 flag", pytrace=False)
    deadline = time.monotonic() + config.max_runtime_seconds
    results = []
    for api in ("sync", "async"):
        for enabled in (False, True):
            results.append(_bounded_trial(config, api, enabled, deadline))
    report = dict(target_id=config.target_id, package_id=config.package_id,
                  planner_version=config.planner_version, executor_version=config.executor_version,
                  engine_flags=config.engine_flags, planner_timeout_seconds=config.planner_timeout_seconds,
                  verification_mode=config.verification["mode"], trials=results)
    record_property("result_batch_benchmark", json.dumps(report, sort_keys=True))
    print(json.dumps(report, sort_keys=True))
    baseline = config.verification.get("expected_digest")
    for result in results:
        if (result["requested_protocol"] == "v1" and result["status"] != "ok"
                and config.verification.get("expected_digest") is not None):
            continue
        assert result["status"] == "ok", "A benchmark lane failed; inspect the payload-free report"
        assert result["row_count"] == config.expected_row_count, "Unexpected result row count"
        if baseline is None:
            baseline = result["digest"]
        assert result["digest"] == baseline, "Result verification failed"
        assert result["rpc_count"] > 0, "Real fetch diagnostics are unavailable"
        assert result["successful_protocols"] == [result["requested_protocol"]], "Requested protocol was not exercised"
        if result["requested_protocol"] == "v2":
            assert result["total_seconds"] < 900, "V2 did not finish within the unchanged planner budget"
