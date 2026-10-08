"""Explicit benchmark configuration, bounded verification and safe diagnostics."""
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re

from test.integration.support import (
    IntegrationConfigError, _connection_kwargs, _nonempty_string, _READ_ONLY_SQL,
)


@dataclass(frozen=True, repr=False)
class ResultBatchBenchmarkConfig:
    connection_kwargs: dict
    read_only_sql: str
    expected_row_count: int
    verification: dict
    target_id: str
    package_id: str
    planner_version: str
    executor_version: str
    engine_flags: dict
    planner_timeout_seconds: float
    max_runtime_seconds: float

    def __repr__(self):
        return "ResultBatchBenchmarkConfig(<redacted>)"


def connection_options(connection_kwargs, api, enabled):
    """Use the same supplied receive limit through each API's public option."""
    options = dict(connection_kwargs, enable_result_batch_v2=enabled)
    if api == "async":
        limit = options.get("grpc_options", {}).get("max_receive_message_length")
        if limit is not None:
            options["max_receive_message_bytes"] = limit
    return options


def _positive_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise IntegrationConfigError(name + " must be a positive finite number")
    return float(value)


def load_benchmark_config(path, environ=None):
    if not path:
        raise IntegrationConfigError("--result-batch-benchmark-config is required")
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise IntegrationConfigError("Cannot read benchmark configuration JSON") from error
    required = ("connection_kwargs", "read_only_sql", "expected_row_count", "verification",
                "target_id", "package_id", "planner_version", "executor_version", "engine_flags",
                "planner_timeout_seconds", "max_runtime_seconds")
    if not isinstance(raw, dict):
        raise IntegrationConfigError("Benchmark configuration must be a JSON object")
    for name in required:
        if name not in raw:
            raise IntegrationConfigError("Benchmark configuration missing " + name)
    query = _nonempty_string(raw["read_only_sql"], "read_only_sql")
    if not _READ_ONLY_SQL.match(query):
        raise IntegrationConfigError("read_only_sql must be an explicit read-only workload")
    count = raw["expected_row_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise IntegrationConfigError("expected_row_count must be a nonnegative integer")
    verification = raw["verification"]
    if not isinstance(verification, dict) or verification.get("mode") not in ("ordered_sha256", "unordered_sha256_sum"):
        raise IntegrationConfigError("verification.mode must select ordered_sha256 or unordered_sha256_sum")
    if not isinstance(verification.get("stable_dataset"), bool):
        raise IntegrationConfigError("verification.stable_dataset must be an explicit boolean")
    digest = verification.get("expected_digest")
    if digest is not None and (not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None):
        raise IntegrationConfigError("verification.expected_digest must be a lowercase SHA-256-sized hexadecimal value")
    if not verification["stable_dataset"] and digest is None:
        raise IntegrationConfigError("An unstable workload requires an independent expected_digest")
    flags = raw["engine_flags"]
    if not isinstance(flags, dict) or any(not isinstance(flags.get(name), bool) for name in (
        "ENABLE_GET_NEXT_RESULT_BATCH_V2", "ENABLE_GET_NEXT_CHUNK_V2",
    )):
        raise IntegrationConfigError("engine_flags must explicitly record both boolean batching flags")
    connection_kwargs = _connection_kwargs(raw["connection_kwargs"], os.environ if environ is None else environ)
    if connection_kwargs.get("debug", False):
        raise IntegrationConfigError("Benchmark connection debug logging must be disabled")
    return ResultBatchBenchmarkConfig(
        connection_kwargs=connection_kwargs,
        read_only_sql=query, expected_row_count=count, verification=dict(verification),
        target_id=_nonempty_string(raw["target_id"], "target_id"),
        package_id=_nonempty_string(raw["package_id"], "package_id"),
        planner_version=_nonempty_string(raw["planner_version"], "planner_version"),
        executor_version=_nonempty_string(raw["executor_version"], "executor_version"),
        engine_flags=dict(flags),
        planner_timeout_seconds=_positive_number(raw["planner_timeout_seconds"], "planner_timeout_seconds"),
        max_runtime_seconds=_positive_number(raw["max_runtime_seconds"], "max_runtime_seconds"),
    )


def _json_value(value):
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("Verification requires string map keys")
        return {"$map": [[key, _json_value(value[key])] for key in sorted(value)]}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, (datetime, date, time)):
        return {"$" + type(value).__name__: value.isoformat()}
    if isinstance(value, bytes):
        return {"$bytes": value.hex()}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError("Unsupported result value for explicit benchmark verification")


class RowVerifier:
    """Incremental ordered digest or count-sensitive unordered digest sum."""
    def __init__(self, mode):
        if mode not in ("ordered_sha256", "unordered_sha256_sum"):
            raise ValueError("Unsupported row verification mode")
        self.mode = mode
        self.count = 0
        self._ordered = hashlib.sha256()
        self._sum = 0

    def add(self, rows):
        for row in rows:
            encoded = (json.dumps(_json_value(list(row)), ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
            if self.mode == "ordered_sha256":
                self._ordered.update(encoded)
            else:
                self._sum = (self._sum + int.from_bytes(hashlib.sha256(encoded).digest(), "big")) % (1 << 256)
            self.count += 1

    @property
    def digest(self):
        return self._ordered.hexdigest() if self.mode == "ordered_sha256" else format(self._sum, "064x")


class FetchMetrics(logging.Handler):
    """Observe numeric diagnostics from real calls without storing log messages."""
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.rpc_count = self.serialized_bytes = self.chunk_count = self.fallback_count = 0
        self.rpc_seconds = self.decode_seconds = 0.0
        self.successful_protocols = set()
        self.statuses = Counter()
        self.chunks_per_response = Counter()
        self._saved_loggers = []

    def emit(self, record):
        if getattr(record, "result_batch_fallback", False):
            self.fallback_count += 1
            return
        status = getattr(record, "result_batch_status", None)
        if status not in ("ok", "unimplemented", "error"):
            return
        self.rpc_count += 1
        self.statuses[status] += 1
        self.rpc_seconds += record.result_batch_rpc_seconds
        self.decode_seconds += record.result_batch_decode_seconds
        self.serialized_bytes += record.result_batch_serialized_bytes
        self.chunk_count += record.result_batch_chunk_count
        if status == "ok":
            self.successful_protocols.add(record.result_batch_protocol)
            self.chunks_per_response[record.result_batch_chunk_count] += 1

    def __enter__(self):
        for name in ("e6data_python_connector.e6data_grpc", "e6data_python_connector.async_cursor"):
            logger = logging.getLogger(name)
            self._saved_loggers.append((logger, logger.level, logger.handlers, logger.propagate))
            logger.setLevel(logging.DEBUG)
            logger.handlers = [self]
            logger.propagate = False
        return self

    def __exit__(self, *exc):
        for logger, level, handlers, propagate in self._saved_loggers:
            logger.setLevel(level)
            logger.handlers, logger.propagate = handlers, propagate
        self._saved_loggers.clear()

    def summary(self):
        return dict(rpc_count=self.rpc_count, serialized_bytes=self.serialized_bytes,
                    chunk_count=self.chunk_count, chunks_per_response=dict(self.chunks_per_response),
                    rpc_seconds=self.rpc_seconds, decode_seconds=self.decode_seconds,
                    fallback_count=self.fallback_count, statuses=dict(self.statuses),
                    successful_protocols=sorted(self.successful_protocols))
