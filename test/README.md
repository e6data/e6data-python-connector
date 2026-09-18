# Test Directory

This directory contains all test files for the e6data-python-connector project.

## Test Files

### Core Tests
- **`tests.py`** - Main test suite with comprehensive e6data connector tests
- **`tests_grpc.py`** - gRPC-specific tests including query execution, caching, and explain functionality

### DECIMAL128 Tests
- **`test_decimal128_parsing.py`** - Comprehensive test suite for DECIMAL128 data type parsing
- **`validate_decimal128.py`** - Validation script to verify DECIMAL128 implementation
- **`verify_decimal_fix.py`** - Verification script for the DECIMAL128 fix
- **`test_fix.py`** - Simple test for invalid binary data handling fix

### Utility Tests
- **`check_decimal_errors.py`** - Utility script to check Decimal module exceptions

## Running Tests

### Prerequisites
Set the following environment variables:
- `ENGINE_IP`: IP address of the e6data engine
- `DB_NAME`: Database name
- `EMAIL`: Your e6data email
- `PASSWORD`: Access token from e6data console
- `CATALOG`: Catalog name
- `PORT`: Port number (default: 80)

### Running Individual Tests

```bash
# Run main test suite
python -m unittest test.tests

# Run gRPC tests
python -m unittest test.tests_grpc

# Run DECIMAL128 tests
python test/test_decimal128_parsing.py

# Run validation
python test/validate_decimal128.py

# Run verification
python test/verify_decimal_fix.py
```

### Running All Tests

```bash
# Run all unittest-based tests
python -m unittest test.tests test.tests_grpc

# Run all standalone tests
python test/test_decimal128_parsing.py
python test/validate_decimal128.py
python test/verify_decimal_fix.py
```

## Result batch V2 qualification

The V2 tests are in `integration/test_result_batch_v2.py`. They require an
explicit real-engine configuration passed with `--integration-config`.
Configuration requires `target_id`, `package_id`, `connection_kwargs`,
`read_only_sql`, and `expected_rows`. Keep credentials outside JSON: credential
values use an environment reference such as `{"env": "E6DATA_PASSWORD"}`.

Add a `result_batch_v2` object to that configuration with:

| Field | Required value |
|-------|----------------|
| `expected_protocol` | `"v2"` on an enabled V2 planner, or `"v1"` on the intentional compatibility-fallback target |
| `ordered_results` | An explicit boolean stating whether the supplied workload has stable row order |

Run once against an enabled V2 target and again against a target that returns
`UNIMPLEMENTED` before consuming a V2 request. The tests compare V1 and opted-in
results for sync and async mixed fetches, `fetchmany`, `fetchall_buffer`, and
SQLAlchemy buffered and streamed reads. Protocol diagnostics prove the selected
DB-API fetch path was exercised. Missing V2 expectations produce a visible skip,
which does not count as qualification.

```bash
python -m pytest test/integration/test_result_batch_v2.py \
  --integration-config "$E6DATA_INTEGRATION_CONFIG" --tb=no
```

### Large-result benchmark

`integration/benchmark_result_batch_v2.py` is a standalone benchmark, excluded
from default test collection by its filename. It has its own required
configuration option; running it without that option fails. It does not infer a
workload, credentials, expected data, engine flags, versions, or runtime budget.

```bash
python -m pytest test/integration/benchmark_result_batch_v2.py \
  --result-batch-benchmark-config "$RESULT_BATCH_BENCHMARK_CONFIG" \
  --tb=no -s --junitxml=result-batch-benchmark.xml
```

Supply the following JSON fields from the deployment and workload being tested:

| Field | Meaning |
|-------|---------|
| `target_id`, `package_id` | Nonsecret identifiers for the actual target and installed connector artifact |
| `connection_kwargs` | Existing connection settings, with environment references for credentials and `debug` disabled |
| `read_only_sql` | Authorized read-only workload, with deterministic ordering if using the ordered digest |
| `expected_row_count` | Independently established result count, greater than 20,000,000 for this acceptance test |
| `verification.mode` | `ordered_sha256` or `unordered_sha256_sum` |
| `verification.stable_dataset` | Explicit boolean asserting that all trials read the same data snapshot |
| `verification.expected_digest` | Optional independent 64-character lowercase hexadecimal digest; required when the dataset is not stable |
| `planner_version`, `executor_version` | Versions actually running on the target |
| `engine_flags` | Explicit boolean values for `ENABLE_GET_NEXT_RESULT_BATCH_V2` and `ENABLE_GET_NEXT_CHUNK_V2` |
| `planner_timeout_seconds` | Observed unchanged planner budget; this acceptance test requires 900 |
| `max_runtime_seconds` | Positive overall wall-clock cap for all four trials, including worker startup |

Use `connection_kwargs.grpc_options.max_receive_message_length` to supply a
measured finite receive limit. The harness applies that same limit through
`max_receive_message_bytes` for async trials. If omitted, each API uses its
existing default; that does not establish a measured sync receive limit.
Record the tested receive limit alongside the report. Avoid gRPC trace
environment variables during runs because transport tracing can expose data.

The four trials run sequentially: sync V1, sync V2, async V1, async V2. Each runs
in a fresh process for independent peak RSS. The overall deadline stops later
trials and terminates a worker that exceeds the remaining budget. Termination
can take up to two additional seconds and cannot confirm server-side query
cleanup. Preserve the report even when a lane fails; it records incomplete
qualification. Set a sufficient overall cap to allow a slow V1 baseline and
both V2 trials to finish.

Rows are consumed with `fetchall_buffer()` and verified incrementally. With a
stable dataset and no independent digest, the first successful V1 result is the
baseline, and all four lanes must succeed. Only an explicitly supplied
independent digest permits a failed V1 lane. Both V2 lanes must still produce
the exact expected count and digest, exercise the V2 protocol, and finish in
less than 900 seconds. This cannot prove the planner's configured budget or
data snapshot: those inputs must be established separately.

`ordered_sha256` hashes compact UTF-8 JSON rows, each followed by a newline.
`unordered_sha256_sum` sums each row's SHA-256 integer modulo 2^256, preserving
duplicate counts while ignoring order. Neither mode stores the entire result.
The serializer uses tags for Decimal, date, datetime, time, and bytes values;
maps use sorted string keys under a separate `$map` tag. Non-finite floats and
unsupported value types fail verification. Produce independent digests using
the same serializer in `integration/result_batch_benchmark_support.py`. These
digests detect discrepancies probabilistically, not through an exact row diff.

The JSON report and JUnit property record protocol attempts, status counts,
fallbacks, chunks per successful response, serialized protobuf bytes, RPC and
decode time, query execution, first-row, drain, total and consumer-verification
time, peak RSS, and the Python allocation peak. Protobuf bytes are not HTTP/2 or
TLS wire bytes. Total timings include streaming verification; allocation
tracking also adds overhead. Reports exclude SQL, credentials, result rows, and
raw exception messages. Use nonsecret target and version labels.

### Qualification limits

Live parity and the greater-than-20-million-row benchmark have not been run for
this change. Local configuration tests and collection checks do not establish
real-engine compatibility, performance, memory safety, or deployment readiness.
Before activation, separately qualify empty/nonterminal envelopes and terminal
data on every result-store path; server byte limits and oversized chunks;
authentication/session renewal and query routing; pool reuse and cancellation;
and externally induced disconnect, timeout, malformed-data, and message-size
failures. This harness does not create a fault-injection service or change the
planner timeout. Broader activation also needs a bounded server response-byte
contract, because limiting chunk counts alone does not bound response bytes.

## Test Coverage

The test suite covers:
- Connection management and authentication
- Query execution (simple, parameterized, complex)
- Data fetching (fetchall, fetchone, fetchmany)
- Schema information retrieval
- Database catalog operations
- CSV export functionality
- Multiple cursor support
- Query cancellation
- DECIMAL128 data type parsing
- Error handling and edge cases
- gRPC communication
- Caching mechanisms
- Query explanation and analysis

## Notes

- Tests require network access to e6data clusters
- Port 80 must be open for inbound connections
- Tests require a running e6data cluster with valid credentials
- DECIMAL128 tests use mock data and don't require cluster access
