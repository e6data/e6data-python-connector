"""Pure benchmark configuration and streaming verification, with no services."""
import hashlib
import importlib
import json
import logging
from pathlib import Path
import subprocess
import sys
from decimal import Decimal

import pytest

from test.integration.support import IntegrationConfigError


def test_verification_distinguishes_typed_values_from_similar_json_objects():
    decimal = support().RowVerifier("ordered_sha256")
    mapping = support().RowVerifier("ordered_sha256")
    decimal.add([[Decimal("1.25")]])
    mapping.add([[{"$decimal": "1.25"}]])
    assert decimal.digest != mapping.digest


def test_benchmark_rejects_verbose_connection_logging(tmp_path):
    path = write_benchmark(tmp_path, connection_kwargs={"host": "localhost", "port": 1, "debug": True})
    with pytest.raises(IntegrationConfigError, match="debug"):
        support().load_benchmark_config(path, environ={})


def test_expired_benchmark_budget_starts_no_worker():
    benchmark = importlib.import_module("test.integration.benchmark_result_batch_v2")
    result = benchmark._bounded_trial(None, "sync", True, deadline=0)
    assert result["error_type"] == "BenchmarkDeadlineExceeded"
    assert result["worker_started"] is False


def test_shared_receive_limit_is_applied_to_async_option_without_mutating_config():
    original = {"grpc_options": {"max_receive_message_length": 123456}}
    options = support().connection_options(original, "async", True)
    assert options["max_receive_message_bytes"] == 123456
    assert options["enable_result_batch_v2"] is True
    assert "max_receive_message_bytes" not in original
    assert "max_receive_message_bytes" not in support().connection_options(original, "sync", False)


def support():
    return importlib.import_module("test.integration.result_batch_benchmark_support")


def write_benchmark(tmp_path, **updates):
    # Explicit unit-test inputs only. No test opens this reserved local target.
    data = {
        "target_id": "unit-target", "package_id": "unit-package",
        "connection_kwargs": {"host": "localhost", "port": 1},
        "read_only_sql": "SELECT 1", "expected_row_count": 3,
        "verification": {"mode": "ordered_sha256", "stable_dataset": True},
        "planner_version": "unit-planner", "executor_version": "unit-executor",
        "engine_flags": {"ENABLE_GET_NEXT_RESULT_BATCH_V2": True,
                         "ENABLE_GET_NEXT_CHUNK_V2": False},
        "planner_timeout_seconds": 900, "max_runtime_seconds": 30,
    }
    data.update(updates)
    path = tmp_path / "benchmark.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_benchmark_uses_explicit_workload_without_materialized_expected_rows(tmp_path):
    config = support().load_benchmark_config(write_benchmark(tmp_path), environ={})
    assert config.read_only_sql == "SELECT 1"
    assert config.expected_row_count == 3
    assert config.planner_timeout_seconds == 900
    assert config.engine_flags["ENABLE_GET_NEXT_CHUNK_V2"] is False
    assert "connection_kwargs" not in repr(config)


@pytest.mark.parametrize("missing", ["read_only_sql", "expected_row_count", "verification",
                                    "planner_version", "executor_version", "engine_flags",
                                    "planner_timeout_seconds", "max_runtime_seconds"])
def test_benchmark_never_infers_missing_workload_or_runtime_evidence(tmp_path, missing):
    path = write_benchmark(tmp_path)
    data = json.loads(path.read_text())
    del data[missing]
    path.write_text(json.dumps(data))
    with pytest.raises(IntegrationConfigError, match="missing"):
        support().load_benchmark_config(path, environ={})


@pytest.mark.parametrize("key,value", [("expected_row_count", True), ("expected_row_count", -1),
                                      ("max_runtime_seconds", 0), ("planner_timeout_seconds", float("inf")),
                                      ("read_only_sql", "DELETE FROM unit_table")])
def test_benchmark_rejects_invalid_workload_or_unbounded_budget(tmp_path, key, value):
    with pytest.raises(IntegrationConfigError):
        support().load_benchmark_config(write_benchmark(tmp_path, **{key: value}), environ={})


def test_unstable_workload_requires_independent_digest(tmp_path):
    path = write_benchmark(tmp_path, verification={"mode": "unordered_sha256_sum", "stable_dataset": False})
    with pytest.raises(IntegrationConfigError, match="expected_digest"):
        support().load_benchmark_config(path, environ={})


@pytest.mark.parametrize("verification", [
    {"mode": "count_only", "stable_dataset": True},
    {"mode": "ordered_sha256", "stable_dataset": "yes"},
    {"mode": "ordered_sha256", "stable_dataset": False, "expected_digest": "invalid"},
])
def test_benchmark_requires_explicit_supported_verification(tmp_path, verification):
    with pytest.raises(IntegrationConfigError):
        support().load_benchmark_config(write_benchmark(tmp_path, verification=verification), environ={})


def test_benchmark_reuses_credential_reference_guard(tmp_path):
    path = write_benchmark(tmp_path, connection_kwargs={"host": "localhost", "port": 1,
                                                       "password": "unit-literal-must-not-escape"})
    with pytest.raises(IntegrationConfigError) as caught:
        support().load_benchmark_config(path, environ={})
    assert "unit-literal-must-not-escape" not in str(caught.value)


def test_benchmark_resolves_external_credentials_without_exposing_them(tmp_path):
    path = write_benchmark(tmp_path, connection_kwargs={"host": "localhost", "port": 1,
                                                       "password": {"env": "UNIT_PASSWORD"}})
    config = support().load_benchmark_config(path, environ={"UNIT_PASSWORD": "unit-input"})
    assert config.connection_kwargs["password"] == "unit-input"
    assert "unit-input" not in repr(config)


def test_ordered_verification_is_independent_of_fetch_chunk_boundaries():
    first = support().RowVerifier("ordered_sha256")
    first.add([[1], [2]])
    first.add([[3]])
    assert first.count == 3
    assert first.digest == hashlib.sha256(b'[1]\n[2]\n[3]\n').hexdigest()
    second = support().RowVerifier("ordered_sha256")
    second.add([[1], [3], [2]])
    assert first.digest != second.digest


def test_unordered_verification_preserves_duplicates_but_not_order():
    values = []
    for rows in ([[1], [2], [1]], [[2], [1], [1]], [[1], [2], [2]]):
        verifier = support().RowVerifier("unordered_sha256_sum")
        verifier.add(rows)
        values.append((verifier.count, verifier.digest))
    assert values[0] == values[1]
    assert values[0] != values[2]


def test_verification_does_not_conflate_decimal_and_string():
    decimal = support().RowVerifier("ordered_sha256")
    string = support().RowVerifier("ordered_sha256")
    decimal.add([[Decimal("1.0")]])
    string.add([["1.0"]])
    assert decimal.digest != string.digest


def test_metrics_count_real_diagnostics_without_retaining_payloads():
    metrics = support().FetchMetrics()
    for status, protocol, size in [("unimplemented", "v2", 0), ("ok", "v1", 128)]:
        record = logging.LogRecord("unit", logging.DEBUG, __file__, 1, "no payload", (), None)
        record.result_batch_status = status
        record.result_batch_protocol = protocol
        record.result_batch_rpc_seconds = .1
        record.result_batch_decode_seconds = .2 if size else 0
        record.result_batch_chunk_count = 1 if size else 0
        record.result_batch_serialized_bytes = size
        metrics.emit(record)
    metrics.emit(logging.LogRecord("unit", logging.DEBUG, __file__, 1, "ignored", (), None))
    assert metrics.rpc_count == 2
    assert metrics.serialized_bytes == 128
    assert metrics.chunk_count == 1
    assert metrics.successful_protocols == {"v1"}
    assert metrics.rpc_seconds == pytest.approx(.2)


def test_benchmark_configuration_option_is_separate_from_live_suite_configuration():
    result = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q",
                             "test/unit/test_result_batch_benchmark_config.py",
                             "--result-batch-benchmark-config", "not-opened-during-collection.json"],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_explicit_benchmark_without_configuration_fails_instead_of_skipping():
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=no",
                             "test/integration/benchmark_result_batch_v2.py"],
                            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=30)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "skipped" not in result.stdout
