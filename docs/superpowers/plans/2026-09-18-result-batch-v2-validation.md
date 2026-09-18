# PLT-10376 Result Batch V2 validation

Scope: the opt-in Python connector implementation on
`vishal/plt-10376-result-batch-v2`, based on connector
`df85f81868aab047043b18a0eedf373fb2aae680`. The reviewed engine contract is
PR #1171 at `222f9794c2b77e4ccc1e759af7352e9c2ec81857`.

The user explicitly deferred live qualification. This report separates the
offline implementation gate from production activation and the real
20-million-row, 900-second acceptance test.

## 1. Requirement coverage matrix

| Requirement | Implementation and offline evidence | Qualification |
|---|---|---|
| Additive V2 wire contract | `e6x_engine.proto`; `test_result_batch_v2_wire_contract`; generated service and both protobuf runtime tests | Offline |
| Default-off boolean setting | Sync and async constructors; strict direct-value and SQLAlchemy URL tests | Offline |
| Preserve V1 defaults and fetch shapes | Existing scalar, lifecycle, OAuth, pool and dialect suites; sync default URL regression fixed | Offline |
| Decode independent chunks atomically and in order | `result_batch.py`; real Thrift tests, including corrupt later chunks and valid empty chunks | Offline |
| Deliver terminal-response rows before EOF | Sync and async mixed-fetch and buffered-iteration tests | Offline |
| Distinguish empty nonterminal from EOF | Buffer and cursor ingestion tests; bounded continuation implemented in each transport loop | Successful transport continuation remains live-gated |
| Query-local V1 fallback on UNIMPLEMENTED | Real generated base-servicer tests; query-state reset tests | Successful fallback stream remains live-gated |
| No replay after ambiguous consumption | Real unavailable socket and generated-service failures; terminal-state tests | Midstream live fault injection deferred |
| Session and route ownership | Query-local session tests, OAuth session exclusion, existing pinned-route machinery | Renewal and mixed engine deployments deferred |
| Finite operation deadline | Sync option validation, expired deadline tests, async admission/cancellation tests | Real empty-response loop and slow engine deferred |
| Cleanup and reuse | Clear failure, close failure, cancellation, reset, stale decode and expired pool lease tests | Remote cleanup success deferred |
| Preserve receive limits | Existing sync defaults and async 64 MiB option retained; configuration tests | Oversized V2 response qualification deferred |
| No prefetch | Fetching remains caller-driven and sequential; one envelope uses the existing async work reservation | Implemented scope |
| Diagnostic measurements | Per-attempt status, protocol, bytes, chunks, RPC and decode timing; metrics aggregation tests | Offline |
| Live matrix and streaming benchmark tooling | Integration tests, separate benchmark configuration, bounded subprocess runner and incremental digest tests | Tooling only; no live run |
| Activation documentation | Root README and `test/README.md` | Documents deferred gates and rollback setting |

All implementation requirements have code and offline evidence. Successful
V2 server transport, live failure scenarios and performance remain unqualified.
No new service mocks or fakes were introduced.

## 2. Regression risk analysis

The complete final offline matrix passed in isolated Linux containers after
the R1 review fix:

| Python / dependencies | Passed | Live skips | Existing xfail | Combined statement/branch coverage |
|---|---:|---:|---:|---:|
| 3.11.16 / minimum | 2,017 | 37 | 1 | 89.86% |
| 3.11.16 / current | 2,017 | 37 | 1 | 89.86% |
| 3.12.14 / current | 2,017 | 37 | 1 | 89.85% |
| 3.13.15 / current | 2,017 | 37 | 1 | 89.85% |

Each lane passed the wheel build and clean base, async and async-SQLAlchemy
installation/import/registry checks. The final vector contract test also passed
separately in all current lanes: 259 tests each. The existing expected failure
is the legacy no-cache blue/green resume case. The 37 skips require explicit
live-service configuration and were deferred by the user.

Reproduction follows `.github/workflows/connector-tests.yml`, using
`--cov=e6data_python_connector --cov-branch --cov-fail-under=80.01`.
Authoritative logs, versions, wheel artifacts and complete coverage reports
are in `/tmp/plt-10376-validation/post-review-py*`. The final source manifest is
`/tmp/plt-10376-validation/post-review-source-sha256.json`.
Earlier failed environment attempts
are retained separately and are not counted as passing gates.

Whole changed runtime files have 79.64-79.69% combined statement/branch coverage;
added executable lines have 449/552 covered (81.34%, including regenerated
bindings). This differs from the full-package gate. On the Python 3.12 lane,
`result_batch.py` is 100%, `async_cursor.py` is 81.28%, and `e6data_grpc.py` is
68.15%. The latter includes substantial existing code and successful network
branches still awaiting live qualification. No coverage denominator was removed.

| Area | Preservation evidence | Residual risk |
|---|---|---|
| Default V1 API and SQLAlchemy | Complete existing suite and repaired default argument-map regression | Live engine interoperability remains untested |
| Authentication and sessions | Existing OAuth/legacy contracts, query-local V2 session tests | Actual renewal requires live qualification |
| Routing, cleanup and pooling | Existing contracts plus cancellation/reset/expired-lease tests | Remote success and deployment transitions are live-gated |
| Packaging and supported dependency floors | Four CI lanes and twelve clean wheel environments | Host macOS full rerun unavailable after semaphore exhaustion |

The first run exposed a sync SQLAlchemy argument-map regression: an omitted
flag unnecessarily added a keyword to the existing mapping. The dialect now
forwards the flag only when it is present. The existing failing regression and
new V2 cases passed together: 78 focused sync tests. The blank-value test was
also corrected to preserve the empty query value through SQLAlchemy URL
construction, allowing the existing strict parser to be exercised.

The minimum Linux lane also reproduced an existing Thrift 0.20 native Binary
decoder error on truncated input. The prior test recognized the same error only
for Compact. The portability assertion now covers both accelerated protocols,
still requiring an actual native decoder, exactly Thrift 0.20.0 and the exact
`PY_SSIZE_T_CLEAN` error text. The connector runtime is unchanged by this fix.

The independent review found R1: cleanup and some query-owned requests could
use the connection's old legacy session after a result response returned a new
one. A corrupt or expired decode could also discard that new cleanup identity.
Both APIs now retain a valid current-query session before decoding and select
it for query-owned requests and cleanup. Stale async revisions and OAuth
response sessions remain excluded. Sync cancellation also keeps its query's
route and a finite cleanup budget. Default-off session behavior is preserved.
The sync regression ran RED (24 failures) then GREEN (110 focused tests); async
ran RED (15 session cases and 3 decode edges) then GREEN (154 focused tests).
The complete final matrix and package gates passed with these changes. The
independent reviewer reran all 115 V2 cases (72 sync and 43 async), passed them,
and closed R1 after reviewing the actual implementation.

## 3. Edge case findings

- Mixed row/chunk fetching preserves order and does not reinsert leftovers.
- A corrupt later chunk exposes none of its envelope; fetching becomes terminal.
- Terminal data drains before EOF; valid zero-row chunks are not implicit EOF.
- Async cancellation or stale decode cannot publish late rows or sessions.
- Cancellation discards undelivered rows even if remote cancellation fails.
- Clear/close failures retain the known handle for explicit cleanup.
- A new query resets its protocol, session and envelope state.

Evidence: `test_result_batch_v2.py`, `test_sync_result_batch_v2.py` and
`test_async_result_batch_v2.py`.

## 4. Failure scenario findings

UNIMPLEMENTED permits one V2-to-V1 transition for that query. Other dispatched
failures remain terminal; neither the fetch nor the SQL query is replayed.
Admission/authentication failures before dispatch remain distinguishable from
ambiguous consuming failures. These boundaries use actual local gRPC failures
and the unmodified generated base servicer in offline tests.

Live malformed-response, oversize-response, session-renewal, disconnect,
result-store EOF and partial-deployment scenarios are still activation gates.
There is no database migration or new write path in this change.

## 5. Security findings

V2 uses the existing query metadata and session/bearer mechanisms. The pure
decoder has no authentication or network capability. The new structured
diagnostics contain no SQL, row data, credentials, session identifiers or hosts.
Benchmark configuration reuses credential environment references, rejects
verbose connection logging and emits nonsecret measurements rather than SQL
or payloads. Existing authentication tests are included in the full suite.
This is not a live tenant-isolation or engine authorization qualification.

## 6. Observability findings

Both protocols emit one diagnostic per dispatched result attempt, including
errors, plus a separate fallback marker. The benchmark aggregates these records
and measures first-row, drain, verification and total time, count/digest and
memory. Server build, flag and timeout evidence must be supplied explicitly;
the client does not infer or attest the deployment configuration.

## 7. Missing test coverage

Live tests and the standalone benchmark are present but not executed. A real
engine must establish successful V2 and fallback streams, partial responses,
all result-store EOF paths, receive limits, real cancellation/cleanup and the
actual large workload. Local response ingestion is codec/state evidence, not
an end-to-end successful V2 RPC. Prefetch is outside the requested scope.

## 8. Remaining risks

- Whole-envelope decoding can increase peak memory and first-chunk latency.
  Keep a finite receive limit and measure the actual workload before activation.
- Chunk count does not bound serialized bytes. Server byte limits, oversize
  single-chunk behavior and fallback-engine parity need live qualification.
- The original 900-second timeout is unchanged and has not been shown resolved.
- A local coverage attempt with dotted module selectors recursively started
  Python resource trackers and exhausted the Mac's named semaphore capacity.
  The process tree was stopped; final validation uses isolated Linux containers
  and package-root coverage. No global IPC limits or unrelated processes were
  changed. Restoring the Mac's semaphore namespace may require a host restart.

## 9. Confidence level

High for default-off compatibility and the tested codec/state/lifecycle
behavior, supported by the full matrix and package checks. Confidence in
successful live V2 transport and production performance remains limited until
the deferred qualification is completed. Independent review completed with
85/100 confidence: default-off merge GO, rollout NO-GO pending live evidence.
See [the independent review](2026-09-18-result-batch-v2-adversarial-review.md).

## 10. Final production readiness assessment

PASS for the authorized offline implementation scope after the complete final
matrix, package checks and independent R1 recheck. No confirmed connector code
finding remains open. Production activation, engine qualification and the
actual large-result acceptance measurement remain pending under PLT-10376.
