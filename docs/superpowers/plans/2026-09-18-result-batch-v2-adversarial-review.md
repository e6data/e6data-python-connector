# PLT-10376 independent production readiness review

Decision: **Merge GO with the feature default-off. Rollout NO-GO.**
Confidence: **85/100**.

An independent production-readiness reviewer inspected the implementation and
new files against `df85f81868aab047043b18a0eedf373fb2aae680`, after the mandatory
offline validation. The review found R1; it was fixed, retested and re-reviewed.
Successful real-engine V2 transport, session rotation, failure injection,
result-store completion and the 900-second workload remain unqualified.

## A. Attack the system

| Scenario | Traced behavior and assessment |
|---|---|
| Old server, disabled V2, mixed versions | Only UNIMPLEMENTED changes this query to V1. Subsequent queries may attempt V2. No connection-wide capability cache. Acceptable if the server rejects before consumption. `e6data_grpc.py:1988`, `async_cursor.py:370`. |
| Corrupt later chunk, empty payload, terminal data | The decoder completes the envelope before publishing chunks. Malformed chunks terminate consumption; terminal rows drain before EOF. Acceptable. `result_batch.py:8`, `result_batch.py:27`. |
| Empty nonterminal responses | Bounded backoff remains within the existing deadline; absent terminal evidence is not reported as completion. Acceptable. `e6data_grpc.py:1988`, `async_cursor.py:370`. |
| Disconnect, timeout, message-size failure, rejected credentials | Dispatched failures terminate consumption without retry, protocol downgrade or execution replay. Predispatch authentication failures do not imply consumption. Acceptable. `e6data_grpc.py:95`, `e6data_grpc.py:1988`, `async_connection.py:307`. |
| Concurrent operations and late decode | Async ownership and revision checks reject stale publication. Cancellation discards pending rows. Acceptable under existing cursor ownership rules. `async_cursor.py:128`, `async_cursor.py:356`. |
| Refreshed session followed by cleanup or decode failure | Originally defective; corrected by R1. Query-owned requests retain the current legacy session even after malformed or expired decoding; OAuth remains empty-session. |
| Stale route or deployment strategy | Fetches retain the query route. Corrected sync cancellation uses the query strategy. Response strategy changes remain deferred. Acceptable. `e6data_grpc.py:1655`, `async_connection.py:307`. |
| Misconfiguration, large responses and diagnostics | Non-booleans are rejected. Receive limits remain intact. Diagnostics exclude SQL, rows, tokens and sessions. Expanded decoded memory still requires qualification. `e6data_grpc.py:482`, `async_connection.py:79`, `async_cursor.py:21`. |

There is no database migration or new data-write path. Existing client
authentication metadata is retained. This review does not establish engine
authorization for the new RPC.

## B. Future engineer misuse

R1 exposed a split abstraction: fetching knew the refreshed query session, while
control requests reconstructed identity from the connection. The correction
establishes common query-request builders at `e6data_grpc.py:1950` and
`async_cursor.py:179`. Future query-owned operations should use these builders.

Regression tests cover distinct sessions, default-off behavior, OAuth, owned
cleanup, stale revisions, corrupted responses and actual cancellation request
construction. No other confirmed misuse defect remains.

## C. Rollout review

| Connector setting | Server response | Behavior |
|---|---|---|
| Disabled | V2 present or absent | Existing V1 path |
| Enabled | V2 available | Ordered V2 envelope consumption |
| Enabled | UNIMPLEMENTED | One query-local transition to V1 |
| Enabled | Other failure | Terminal incomplete result without replay |

The protobuf change is additive. There is no destructive schema transition,
credential migration or persistent capability cache to reverse. Stale clients
keep their V1 behavior. Existing token refresh and request admission remain in
the established connection paths; dependency outages after consuming dispatch
remain terminal.

Activation requires successful real V2 and fallback streams, session renewal
and cleanup, all result-store EOF paths, response byte limits and decoded
memory measurements, fallback-engine parity or an explicit workload
restriction, and complete verified results within the unchanged 900-second
budget. These gates are deferred at the user's request, not satisfied by the
offline tests.

## D. Findings register

| ID | Finding | Classification and status | Risk profile |
|---|---|---|---|
| R1 | Refreshed query session was lost for cleanup/cancellation and after failed decoding | Rollout blocker, **resolved** | Single query/connection; occasional during rotation; degraded service and retained server resources; authenticated use; manual recovery; difficult to detect without cleanup diagnostics |
| R2 | Real-engine and large-workload qualification deferred | Rollout blocker, **open** | Enabled workloads; likelihood unknown; possible incomplete results or resource pressure; authenticated use; cleanup/manual rollback; detection depends on workload verification and instrumentation |
| K1 | Atomic envelope decoding increases first-row latency and peak heap | Known tradeoff | Client process; workload-dependent; degradation or memory exhaustion; authenticated use; process recovery if exhausted; memory measurements required |

R1's supported scenario is a response rotating S0 to S1, followed by cleanup
using S0, or corrupted decoding losing S1 before cleanup. The corrected paths
retain current-query cleanup identity before decoding and use it consistently:

- Sync: `e6data_grpc.py:1655`, `:1950`, `:1959`.
- Async: `async_cursor.py:179`, `:356`, `:603`.

For K1, the approved design considered incremental decoding. Atomic decoding
avoids partially exposing a malformed envelope and retaining raw transport
buffers across consumer pauses. Revisit if measured memory or first-row latency
is unacceptable. A finite serialized receive limit does not bound Python heap
after decoding.

## Independent test evidence

The reviewer independently ran:

- Pre-correction full Linux suite: 1,975 passed, 37 skipped, 1 existing xfail.
- Corrected sync and async V2 regressions: 115 passed.
- Corrected full suite with package-root statement/branch coverage and the
  80.01% threshold: 2,017 passed, 37 skipped, 1 existing xfail; 88.51% combined
  coverage; exit 0.
- `git diff --check`: passed.

The runtime in the independent copy differed from the frozen host by one blank
line, verified with diff. Environment-only failed attempts were not counted as
passes: a root run defeated the unreadable-file assertion, and a tar copy
contained tracked AppleDouble metadata. The successful run used a nonroot
runner and removed metadata artifacts only from the private review snapshot.
No host source was changed by the reviewer.

The separate CI runner passed all four final matrix lanes and every wheel gate
against the final runtime/test hashes. Those results and their 89.85-89.86%
full-package coverage are recorded in the
[validation report](2026-09-18-result-batch-v2-validation.md). The independent
reviewer did not claim to have rerun those four lanes or any live qualification.

## E. Final decision and rollback

- Merge: **GO, default-off**.
- Rollout: **NO-GO until R2 is satisfied**.
- Confirmed open connector code defects: **none after R1 correction**.
- Untracked follow-up promises: none; deferred qualification remains with
  [PLT-10376](https://e6data.atlassian.net/browse/PLT-10376).

Rollback sets `enable_result_batch_v2=False` for new queries/connections.
Explicitly clear or dispose existing cursors, retaining handles if cleanup is
unconfirmed. Do not replay partially consumed queries. No schema migration
needs reversal.
