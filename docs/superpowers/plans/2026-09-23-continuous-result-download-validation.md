# Continuous result download validation

PLT-10376. Local implementation, validation and independent review are complete.
Customer qualification and publication remain separate.

## Result

With `enable_result_batch_v2=True`, a sync download thread or async download task
keeps fetching raw batches until EOF while deserialization runs concurrently.
The serialized queue has no size limit, and the previous four-downloader limit
does not apply. The producer does not wait for decoding or application reads.
One result RPC runs at a time per query; rows and original chunks remain ordered.
The default-off path and per-RPC receive limits are unchanged.

Each background request gets its configured finite timeout at dispatch. Public
fetch deadlines still cover waiting and decoding. Original RPC errors follow
earlier queued responses. Only UNIMPLEMENTED permits V1 fallback. Fallback now
settles the old V2 producer and transport before V1 can advance the session, so
later cleanup cannot restore an older session. Cancellation and pool return
release queued payloads and retain unfinished transport ownership.

## Verification

All four complete offline test environments passed with the same final code:

| Environment | Passed | Skipped | Expected failure | Statement and branch coverage |
|---|---:|---:|---:|---:|
| Python 3.11, minimum dependencies | 2,269 | 37 | 1 | 90.76% |
| Python 3.11, current dependencies | 2,269 | 37 | 1 | 90.76% |
| Python 3.12, current dependencies | 2,269 | 37 | 1 | 90.76% |
| Python 3.13, current dependencies | 2,269 | 37 | 1 | 90.76% |

No failures or coverage warnings remain. The 37 skips require live integration
configuration. The expected failure is the existing legacy no-cache
suspend/resume case. Added executable statement coverage is 389/414 (93.96%).
Whole-file combined coverage is 85.95% for `async_cursor.py`, 77.48% for
`e6data_grpc.py`, and 95.65% for `result_prefetch.py`.

Real loopback tests prove that eight responses reach the client while the first
decode is blocked, six simultaneous sync cursors can download without the old
cap, and queued results preserve order, EOF and original errors. Tests cover
fresh RPC deadlines, bounded empty-response backoff, cancellation, raw-buffer
release, late sessions, V1 fallback, clear and pool return. New behavior and the
fallback-session correction have recorded failing tests before their fixes.

Independent reviews found and closed the fallback-session bug in both APIs.
Shared/sync review ran 196 focused tests and 100 delayed-callback schedules;
the final shared diagnostics checks also passed. Async review ran 51 targeted
tests, then independently passed five fallback/cancellation regressions across
both APIs. The final benchmark instrumentation passed separate source review.
No confirmed code blocker remains.

A local wheel was installed outside the source tree. All 39 packaged Python
files exactly match the final source. Real workers preserved exact values,
types and order across 6 rows and 15 columns; both connector constructors were
rejected inside workers. Both workers exited, with zero named-semaphore growth.
The validation wheel was not published.

## Download completion measurements

Both controls and the candidate used the same frozen data and final harness in
Linux ARM64, Python 3.12.14, with a two-CPU quota and 2 GiB memory limit. Controls
are sequential V2 at `a93e23c` and one-envelope prefetch at `359cb49`.

Each trial repeats a 65,536-row envelope eight times: 524,288 rows in 64 original
chunks through 8 V2 RPCs. Serialized Thrift payload totals are 34.10 MB for mixed
types and 149.44 MB for wide strings. These are synthetic repeated records.

The table shows the median of three trials, from first result RPC dispatch to
receipt and Protobuf parsing of the final response. Row decoding and consumption
can continue afterward. Older versions include their gaps between requests in
this span. Simulated delay is loopback server latency, not customer bandwidth.

| Data | Delay per RPC | Sequential V2 | One ahead | Continuous |
|---|---:|---:|---:|---:|
| Mixed | 0 ms | 2.090 s | 1.579 s | 0.026 s |
| Mixed | 100 ms | 2.991 s | 1.829 s | 0.987 s |
| Wide strings | 0 ms | 1.731 s | 1.505 s | 0.111 s |
| Wide strings | 100 ms | 2.602 s | 1.745 s | 1.184 s |

With 100 ms delay, download time fell by 67.0% for mixed data and 54.5% for wide
strings versus sequential V2. Versus one-ahead prefetch, reductions were 46.0%
and 32.1%. These are download-span reductions, not network throughput claims.

## Total processing and costs

Steady-state total fetch/decode time includes ordered row-digest checks and
excludes worker startup. The activities overlap, so their durations cannot be
added together.

| Data | Delay per RPC | Sequential V2 | One ahead | Continuous |
|---|---:|---:|---:|---:|
| Mixed | 0 ms | 2.384 s | 2.127 s | 2.068 s |
| Mixed | 100 ms | 3.293 s | 2.240 s | 2.170 s |
| Wide strings | 0 ms | 1.960 s | 1.982 s | 1.976 s |
| Wide strings | 100 ms | 2.846 s | 2.091 s | 2.181 s |

The wide-string/100 ms case took 4.3% more total processing time than one-ahead
prefetch, despite receiving the final batch 32.1% sooner. Three-trial medians
are descriptive; small differences do not establish statistical significance.

Continuous-mode worker startup was 0.45-0.54 seconds in these runs. Sampled
parent-plus-worker RSS reached about 604 MiB. Sampling can miss short peaks and
excludes the resource tracker. The uncapped queue is intentional; these
observations are not limits. No decoder optimization was added in this follow-up.

## Reproduce and remaining work

Run the complete offline suite in Linux:

```bash
python -m pytest --cov=e6data_python_connector --cov-branch --cov-fail-under=80.01
```

Use [the performance guide](../../../test/performance/README.md) and the same
frozen fixtures for comparisons. All 12 final reports passed source, harness
and fixture hashes, ordered typed digests, row/chunk counts, sequential RPC
counts, terminal behavior and worker cleanup checks.

Raw evidence is under `artifacts/continuous-download` in the original checkout:
`PERFORMANCE.md`, `performance-summary.json`, `pipeline-*.json`, full matrix
reports, installed-wheel verification and independent review records. Earlier
prefetch reports remain historical evidence for `359cb49`.

No customer query ran. Deployed planner compatibility and completion within the
actual 900-second budget remain unverified. Nothing was pushed or published by
this task. Rollback uses new connections with `enable_result_batch_v2=False`
after existing work is closed and retired; do not replay partially read queries.
