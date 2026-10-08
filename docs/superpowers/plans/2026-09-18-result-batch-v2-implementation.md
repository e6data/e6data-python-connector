# Result Batch V2 Implementation Plan

> For agentic workers: use `superpowers:subagent-driven-development` or `superpowers:executing-plans` for task execution after the user authorizes implementation. Follow the feature implementation, TDD and mandatory validation skills. Do not implement from a draft review state.

**Goal:** Support engine PR #1171's multi-chunk result API in sync and async fetching without lost, repeated or reordered rows.

**Architecture:** Add a default-off connection option, a small shared codec/buffer, and integrate it with the existing cursor lifecycle. Decode one whole V2 envelope at a time, return existing chunk/row shapes, and fetch again only after pending results are drained.

**Tech stack:** Python, existing gRPC/protobuf and Thrift libraries, pytest, existing asyncio work admission and SQLAlchemy adapters. No new runtime dependency.

**Spec:** [Result Batch V2 design](../specs/2026-09-18-result-batch-v2-design.md).

**Status:** Ready For Development after independent design review on 2026-09-18. The two review findings are closed; see the [review record](2026-09-18-result-batch-v2-review.md). This is a planning deliverable, not an implementation or rollout approval.

## Global constraints

- User explicitly deferred prefetching, including download/deserialization overlap. Do not introduce a producer, background fetch, task/thread, prefetch setting or parallel fetch RPC.
- Follow RED, GREEN, REFACTOR for each behavior: write the meaningful test, observe the intended failure, implement the smallest change, and rerun that test before broadening.
- Default `enable_result_batch_v2=False`; preserve V1 public behavior and existing timeout/receive-limit defaults. Do not silently raise a caller's configured limit.
- Preserve sync API/dependency compatibility. Async still requires Python 3.11+. Do not add optional async imports to the shared/sync import path.
- Maintain complete-suite combined statement/branch coverage above 80%, retain existing coverage, and inspect new/changed behavior coverage.
- New mocks/fakes require explicit user authorization. Use real wire objects, pure state tests, the existing real generated-servicer fixture and configured live engines. Do not manufacture success with a custom fake engine.
- Keep existing untracked `index.scip`, `python.scip`, `t3.py`, `t4.py` and unrelated files unchanged. Create an isolated implementation worktree/`vishal/` branch only at implementation time.
- No publishing, merge, release, engine configuration change or deployment is authorized by this plan.

## Task 1: Add and verify the additive wire contract

**Modify:** `e6x_engine.proto`, `e6data_python_connector/server/e6x_engine_pb2.py`, `e6data_python_connector/server/e6x_engine_pb2_grpc.py`, `test/unit/test_protobuf_wire_contract.py`.

**Interface:** Existing `GetNextResultBatchRequest`; new `GetNextResultBatchV2Response` fields and `QueryEngineService.getNextResultBatchV2` exactly as pinned in the spec. No V1 field-number, method, package or service rename.

- [ ] Recheck connector HEAD and PR head. Compare only the relevant additive proto definitions; do not copy the entire engine proto over the connector's potentially different baseline.
- [ ] Add a failing descriptor/wire test before regeneration:

```python
def test_result_batch_v2_wire_contract():
    from e6data_python_connector.server import e6x_engine_pb2 as pb
    service = pb.DESCRIPTOR.services_by_name['QueryEngineService']
    method = service.methods_by_name['getNextResultBatchV2']
    assert method.input_type.full_name == pb.GetNextResultBatchRequest.DESCRIPTOR.full_name
    message = pb.GetNextResultBatchV2Response(
        resultBatches=[b'first', b'second'], endOfStream=True)
    restored = type(message).FromString(message.SerializeToString())
    assert list(restored.resultBatches) == [b'first', b'second']
    assert restored.endOfStream
    assert message.DESCRIPTOR.fields_by_name['resultBatches'].number == 1
    assert message.DESCRIPTOR.fields_by_name['sessionId'].number == 2
    assert message.DESCRIPTOR.fields_by_name['new_strategy'].number == 3
    assert message.DESCRIPTOR.fields_by_name['endOfStream'].number == 4
    assert pb.GetNextResultBatchResponse.DESCRIPTOR.fields_by_name['resultBatch'].number == 2
```

- [ ] Run `python -m pytest test/unit/test_protobuf_wire_contract.py -q`; the added test must fail because the V2 method/message is missing.
- [ ] Add only the new response/RPC and regenerate in an isolated environment using the existing minimum `grpcio-tools==1.65.1` toolchain. Preserve the declared protobuf runtime floor and package-qualified generated import.

```sh
python -m grpc_tools.protoc -I. --python_out=e6data_python_connector/server --grpc_python_out=e6data_python_connector/server e6x_engine.proto
```

- [ ] Update the explicit real message count from 88 to 89 after confirming the descriptor inventory. Keep the runtime wire comparison and dynamic real `UNIMPLEMENTED` tests intact.
- [ ] Rerun wire tests under minimum/current dependency constraints. Inspect generated diffs for unrelated version churn or minimum-version increases.

## Task 2: Build the pure V2 codec and ordered buffer

**Create:** `e6data_python_connector/result_batch.py`, `test/unit/test_result_batch_v2.py`.

**Interfaces:** `decode_result_batches(columns, payloads)` and `ResultBatchBuffer.accept/pop/clear/needs_fetch/finished`, exactly as specified in design section 5.

- [ ] Add real-serialization tests before adding the production helper. Use the existing Thrift types and `encode_chunk` pattern, without a fake decoder:

```python
def test_decodes_independent_chunks_in_order():
    from e6data_python_connector.e6x_vector import ttypes as wire
    from e6data_python_connector.result_batch import decode_result_batches
    from test.unit.test_binary_decoder_contract import encode_chunk
    def payload(values):
        vector = wire.Vector(len(values), wire.VectorType.STRING,
                             [False] * len(values),
                             wire.Data(varcharData=wire.VarcharData(values)))
        return encode_chunk(wire.Chunk(len(values), [vector]))
    assert decode_result_batches(['value'], [payload(['a', 'b']), payload(['c'])]) == [
        [['a'], ['b']], [['c']]]

def test_terminal_marker_does_not_discard_pending_chunks():
    from e6data_python_connector.result_batch import ResultBatchBuffer
    buffer = ResultBatchBuffer()
    buffer.accept([[[1]], [[2]]], end_of_stream=True)
    assert not buffer.finished
    assert buffer.pop() == [[1]]
    assert not buffer.finished
    assert buffer.pop() == [[2]]
    assert buffer.finished
    assert not buffer.needs_fetch
```

- [ ] Add cases for empty nonterminal envelope, empty terminal envelope, valid zero-row serialized chunks, malformed empty byte strings, corrupt later chunks, double acceptance while rows remain, and clear/reset. Test that a corrupt later chunk returns no partial decoded envelope.
- [ ] Run `python -m pytest test/unit/test_result_batch_v2.py -q`; confirm missing implementation causes RED.
- [ ] Implement only the small pure helper, with strict existing decoding and standard `deque` storage. Add no network, auth, worker or async dependency.
- [ ] Rerun the new file and `test/unit/test_binary_decoder_contract.py`. Check no raw-byte concatenation and no change to the existing decoder's V1 behavior.

## Task 3: Add configuration and synchronous cursor support

**Modify:** `e6data_python_connector/e6data_grpc.py`, `e6data_python_connector/dialect.py`, `test/unit/test_result_lifecycle.py`, `test/unit/test_sync_scalar_state_contract.py`.

**Create:** `test/unit/test_sync_result_batch_v2.py`.

**Interfaces:** Append `enable_result_batch_v2=False` to sync `Connection`; query-local protocol and legacy result-session state; a `ResultBatchBuffer` on each cursor; private `_next_result_chunk()` for internal aggregation that never drains `_data`. Preserve all existing public fetch signatures and shapes.

- [ ] Write failing constructor/dialect tests: default false, true accepted, non-booleans rejected, option reaches the connection rather than `grpc_options`, default and explicit receive settings unchanged. Extend only the new URL-option parsing and relevant known-key exclusion.
- [ ] Add opted-in deadline-validation tests for infinity, NaN, zero, negative values, booleans and nonnumeric input. Validate the supplied `grpc_prepare_timeout` before defaulting; only an absent option selects the existing default. Keep default-off behavior unchanged.
- [ ] Add no-network tests using real lazy connections/local cursor state, based on `test_result_lifecycle.py`: pending V2 chunks across mixed fetch methods, terminal-data delivery, failure across every fetch method, foreign `query_id` rejection, and reset/reuse. Use production ingestion/buffer methods, not patched successful transports.
- [ ] Include an explicit leftover-buffer regression: seed distinguishable chunks containing rows 1-3, 4-6 and 7-9 with terminal state; call `fetchone`, `fetchmany(3)`, `fetch_batch`, then buffered iteration. Assert delivery is exactly rows 1 through 9 in order, using each existing API shape, without another network call or a repeated leftover. This exercises `fetchmany` requesting more than its current leftovers.
- [ ] Add a configured live test in Task 5 for actual dispatch and safe fallback; observe its baseline RED where a real target is available. Do not substitute an invented service when credentials/target are missing.
- [ ] Run `python -m pytest test/unit/test_sync_result_batch_v2.py test/unit/test_result_lifecycle.py test/unit/test_sync_scalar_state_contract.py -q` and record intended failures.
- [ ] Integrate V2 after metadata availability checks. Keep the default-off V1 path untouched; factor only the minimum private transport code needed for explicit V1 fallback. Carry one logical deadline through V2, fallback and empty-response continuation.
- [ ] Decode/publish the entire envelope atomically, then serve existing API shapes from it. Public opted-in `fetch_batch` drains `_data` first; `fetchmany`/`fetchall` use `_next_result_chunk` for internal aggregation to avoid draining their own leftovers. Capture query identity, apply returned nonempty legacy session to the query fetch context, and apply strategy through existing deferred handling.
- [ ] Pin `UNIMPLEMENTED` fallback to this query only. Every other dispatched failure uses existing terminal incomplete-result semantics and retains the query handle. Cover pre-dispatch failures separately; do not falsely claim rows were consumed.
- [ ] Extend terminal guards and bounded cleanup to opted-in legacy sync queries. Successful clear/reset removes all V2 state. A new sync execute cleans an active opted-in query before replacing it; failed cleanup forbids replacement. Preserve default-off behavior.
- [ ] Rerun targeted tests and all existing synchronous/OAuth/strategy suites through normal collection. Inspect buffer handoffs for exactly-once delivery and unchanged legacy `fetchone()` shape.

## Task 4: Add asynchronous cursor support and option propagation

**Modify:** `e6data_python_connector/async_connection.py`, `e6data_python_connector/async_cursor.py`, `e6data_python_connector/async_dialect.py`, `test/unit/test_async_connection_contract.py`, `test/unit/test_async_cursor_contract.py`, `test/unit/test_async_cursor_failures.py`, `test/unit/test_async_dialect_contract.py`, `test/unit/test_async_pool_state.py`.

**Create:** `test/unit/test_async_result_batch_v2.py`.

**Interfaces:** Keyword-only immutable `enable_result_batch_v2=False`; same shared codec/buffer; no new public async method, worker pool or background task. Existing pool and `aio.connect` keyword propagation is reused.

- [ ] Write failing local constructor/owner tests, strict dialect boolean routing tests and real-state mixed-fetch/terminal tests. Verify pool connection parameters retain the option without adding duplicate pool configuration state.
- [ ] Write tests for one reservation per envelope, whole-envelope decode failure, cancellation/late revision rejection and buffer cleanup using actual local serialization/decoding work and events. Do not replace the engine with a successful-response test double.
- [ ] Run `python -m pytest test/unit/test_async_result_batch_v2.py test/unit/test_async_connection_contract.py test/unit/test_async_cursor_contract.py test/unit/test_async_cursor_failures.py test/unit/test_async_work.py -q` and record the intended RED failures.
- [ ] Implement dispatch inside the existing caller-owned `_operation`/`_call` flow. Reserve existing capacity before the RPC and invoke one synchronous envelope decoder in that reservation. Keep `safe_retry=False` for consuming result calls.
- [ ] Check revision before publishing decoded chunks. Do not retain a reservation across caller yields and do not acquire another reservation inside the decoder. Honor whole-call `fetchall` deadlines, per-fetch buffered deadlines and the existing 64-MiB configurable receive limit.
- [ ] Drain buffered rows/chunks before another RPC; do not mark `EXHAUSTED` while pending chunks remain. Apply the same empty-nonterminal/backoff and one-time compatibility fallback rules as sync.
- [ ] Extend clear/cancel/close and pool-return verification so no chunk/session/protocol state survives query reset or an expired lease. Do not weaken public task ownership or reset the result failure merely to continue fetching.
- [ ] Rerun targeted async tests and SQLAlchemy/pool contracts. These tests do not replace real V2 engine qualification.

## Task 5: Qualify the actual server contract and compatibility matrix

**Modify:** `test/integration/support.py`, `test/unit/test_integration_config.py`, existing collection metadata only where classification is required.

**Create:** `test/integration/test_result_batch_v2.py`.

**Configuration:** Add `enable_result_batch_v2` to the existing connection-setting allowlist. Keep secrets as environment references. Live runs require explicit real target/build/configuration; successful V2 and V1 fallback cannot be proven by the unmodified generated base servicer.

- [ ] Write pure parser tests first, then permit the new flag. Do not loosen validation for unknown options or secret literals.
- [ ] Add parameterized real-engine tests for sync/async and legacy/OAuth using existing configured auth-matrix conventions. Compare complete results with the supplied baseline, preserving ordering only where the SQL defines it.
- [ ] Qualify new connector/V1-only server, V2-disabled server, V2-enabled server, default-off connector, partial/full responses, zero results, final data, and reused connections. Assert actual method/response counts with instrumentation that forwards real RPCs unchanged.
- [ ] Cover ordered mixed `fetchone`/`fetchmany`/buffered consumption, SQLAlchemy buffered/streaming modes, pools, routing, and session refresh without logging credentials or result content.
- [ ] Use explicitly configured real fault injection for timeout, cancelled read, connection loss and receive-limit failures. Assert no replay, no alternate-route fetch, retained cleanup handle and terminal failure. Missing configured fault cases are reported as unqualified, not silently passed.
- [ ] Require engine EOF tests on in-memory/cached/spilled/fallback stores, including the unconfirmed spill-terminal race. Require fallback-engine parity or a documented activation restriction; no connector workaround that reruns a partially consumed query.
- [ ] Run `python -m pytest test/integration --integration-config "$INTEGRATION_CONFIG" --tb=no --junitxml=live-results.xml` using an actually supplied path. Reject an empty suite, failures, errors or unexpected skips. Run the declared legacy live suite with its required configuration as a separate gate.

## Task 6: Measure the large result and document activation

**Create:** `test/integration/benchmark_result_batch_v2.py`, `test/integration/result_batch_benchmark_support.py`, `test/unit/test_result_batch_benchmark_config.py`.

**Modify:** root `conftest.py` for an explicit benchmark-config option, `test/README.md`, `README.md`, and `test/collection_manifest.json` if necessary for the standalone opt-in benchmark classification.

**Configuration contract:** Reuse the existing explicit connection loader with its credential/environment-reference rules. A separate `--result-batch-benchmark-config` JSON supplies the actual read-only SQL, expected row count, baseline verification method, externally verified planner/executor versions and flags, observed planner timeout, and an explicit maximum benchmark runtime. Do not put millions of expected rows into `expected_rows`. Do not invent a fallback query, endpoint, table, timeout or expected digest. Missing benchmark settings must fail when the benchmark is explicitly requested.

- [ ] Write pure config-validation tests before the loader: absent workload rejected, credential literals rejected by the existing loader, expected row count required, no inferred timeout/build/flags, no default benchmark SQL, and explicit ordering/verification strategy.
- [ ] Add a streaming benchmark using `fetchall_buffer`; consume and verify rows incrementally. Use the same supplied stable workload for V1 and V2 with only the connector protocol flag changed. If repeated runs cannot observe a stable dataset, require an independently supplied expected verification baseline rather than claiming equality.
- [ ] Require evidence of zero missing/duplicate rows appropriate to the workload: a supplied expected count plus an ordered streaming digest when ordering is defined, or an independently supplied unordered verification strategy. A row count alone is insufficient proof of completeness.
- [ ] Record actual RPC count, chunks per response, wire bytes, execution/first-row/drain/total time, decode time, consumer-loop time and peak resident memory. Instrument real calls without replacing results. Suppress SQL, row values, secrets and raw exception dumps.
- [ ] Run the actual >20-million-row workload with the actual 900-second planner budget preserved. If it cannot finish or correctness differs, report the result as failed qualification. Do not increase timeouts or reduce data to label the original problem solved.
- [ ] Document opt-in examples for sync/async and SQLAlchemy, explicit receive-limit configuration, default-off fallback, unchanged chunk-yield shapes, atomic-decode memory cost, activation prerequisites and rollback on new queries. State that prefetching is deferred.

## Task 7: Full validation and independent implementation review

- [ ] Run the complete offline suite, not only the new test files:

```sh
python -m pip install -c test/constraints/current.txt -e '.[async-sqlalchemy]' -r requirements-test.txt build
python -m pytest --cov=e6data_python_connector --cov-branch --cov-report=xml --cov-report=term-missing --cov-fail-under=80.01
python -m build --wheel
```

- [ ] Match the existing CI matrix: Python 3.11 minimum/current dependencies, Python 3.12/3.13 current. Verify generated imports and real `upb`/pure-Python protobuf compatibility.
- [ ] Install the wheel into clean base, async and async-SQLAlchemy environments and run the existing package/import/dialect smoke checks. Do not raise dependency floors accidentally.
- [ ] Execute the configured complete live suite and the applicable declared legacy tests (`python -m unittest test.tests test.tests_grpc`) with real configuration. Explicitly report unavailable configuration, skips and exclusions; offline green does not satisfy these gates.
- [ ] Inspect changed-path coverage and unresolved errors, verify every spec requirement maps to a passing test or an explicitly blocked live gate, and confirm default V1 behavior was preserved.
- [ ] Run mandatory post-implementation validation and an independent production-readiness review. Resolve code blockers and rerun the affected gates. Report code/test status separately from engine readiness and the 900-second workload qualification.
- [ ] Prepare a default-off release candidate only after validation. Publishing, merging, rollout and planner configuration changes require their own authorization.

## Sequence and exit criteria

Wire contract -> pure codec/buffer -> sync and async integrations -> real compatibility qualification -> streaming workload benchmark -> full validation and independent code review. Sync and async work may run in parallel after Task 2, with separate file ownership and a shared stable helper contract. Integration config, documentation and benchmark work must coordinate shared files.

The development deliverable is complete only when the scoped implementation, complete required tests, coverage, package checks and reviews pass. Production activation additionally requires the engine-side conditions and real large-result evidence in the spec. No planned step is a claim that it has already passed.
