# Python connector sync versus async benchmark

Measured on September 11, 2026 IST against the user-approved `atm1` test cluster and `vishal1.tpcds_1000_delta.date_dim`. Four async tasks delivered **3.06x sequential sync throughput**. At the same concurrency, async delivered **10.6% lower aggregate throughput than four sync threads** in this run. The trial variation does not establish a consistent async advantage over threads.

| Mode | Concurrent queries | Measured queries | Throughput, queries/s | Mean query latency | Total measured wall time |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sync, sequential | 1 | 36 | 0.578 | 1.730 s | 62.266 s |
| Async, sequential awaits | 1 | 36 | 0.513 | 1.949 s | 70.171 s |
| Sync, thread pool | 4 | 36 | 1.981 | 1.987 s | 18.175 s |
| Async, concurrent tasks | 4 | 36 | 1.770 | 2.217 s | 20.334 s |

Throughput is total measured queries divided by the sum of measured trial wall times. Mean latency includes the same work in every mode: execute, fetch all rows, verify the result hash, clear the query and close the cursor. Concurrent throughput and individual query latency measure different things: overlap increases completed queries per second without necessarily reducing each query's duration.

For this workload, sequential async calls did not improve speed. Both concurrent approaches improved throughput substantially: sync threads by 3.43x and async tasks by 3.06x versus sequential sync. This benchmark supports using concurrency when multiple independent queries are available. It does not show that converting one synchronous call into one awaited call makes that query faster, nor does it establish a general ranking across workloads.

## Actual workload and runtime

```sql
SELECT d_date_sk, d_year, d_moy, d_dom
FROM vishal1.tpcds_1000_delta.date_dim
ORDER BY d_date_sk
LIMIT 1000
```

Live metadata verified the four columns. The preflight returned exactly 1,000 rows; each benchmark query fetched the complete result and matched the real baseline's count, content and order hash. No table rows or credentials were written to reports. Result SHA-256: `9a2028772d832d68632c964854ac221192bfd61f75dbf86972bfd2565dc5d1ea`.

- Three trials per mode, 12 measured queries per trial, seed 1729 for shuffled mode order. Four-worker modes assign three queries to each exclusive connection; sequential modes reuse one connection for all 12.
- One warm-up per worker per trial. There were 144 measured queries, 30 warm-ups and one baseline query. All 175 completed successfully. The separate metadata/query preflight is not included in this count.
- Connections are created before timing and reused within each trial. Startup/open times are retained in raw JSON but are not directly equivalent handshake measurements: OAuth and transport setup can be lazy. Warm-up is excluded; both modes exclude connection teardown from throughput timing.
- Each measured query includes a client-side SHA-256 validation of its result. Hashing is inside the timing boundary for both modes. This is a validated end-to-end workload, not an isolated transport or server execution benchmark.
- Python 3.12.6, the same final connector source in every mode, no coverage instrumentation, maximum four concurrent queries. The functional suite and offline matrix had finished before benchmarking.
- One Planner, one Queue and one native Executor remained ready throughout, with zero container restarts observed before and after. External traffic, network variability and cache state were not independently controlled. Warm-up and repeated SQL mean these are not cold-cache results.
- Requested builds were verified: operator `gh-pr-1.0.3082-84b1929`, xDS `gh-pr-1.0.661-84b1929`, console `1.0.6565-84b1929`, Planner `gh-pr-2.0.4608-86af7cf`. Exact runtime digests are in [validation](PLT-9922-VALIDATION.md).
- The benchmark completed in 225.50 seconds, within its 240-second internal and 270-second external limits.

## Trial variation

| Mode | Trial 1 queries/s | Trial 2 queries/s | Trial 3 queries/s |
| --- | ---: | ---: | ---: |
| Sync, sequential | 0.553 | 0.596 | 0.587 |
| Async, sequential | 0.579 | 0.576 | 0.419 |
| Sync, 4 threads | 2.348 | 2.019 | 1.685 |
| Async, 4 tasks | 2.364 | 2.174 | 1.232 |

Async exceeded threaded sync throughput in the first two trials and fell behind in the third. The cause of the later slowdown is not established. These are three short observations on one remote cluster, not statistically reliable capacity or tail-latency estimates. Raw per-trial p50 and p95 values are preserved; with 12 samples per trial, nearest-rank p95 is simply that trial's maximum. No global p95 was inferred from those summaries.

## Reproduction and evidence

Use an already running authorized test cluster and the existing integration configuration mechanism. Credentials belong in the configuration's environment references, not command arguments or reports. Invoke the benchmark file explicitly; its filename keeps it outside normal test collection.

```sh
E6_RUN_BENCHMARK=1 \
E6_BENCHMARK_SQL='SELECT d_date_sk, d_year, d_moy, d_dom FROM vishal1.tpcds_1000_delta.date_dim ORDER BY d_date_sk LIMIT 1000' \
python -m pytest test/integration/benchmark_sync_async.py \
  --integration-config /absolute/path/to/operator-config.json -q -s --no-cov
```

Use the configuration format described in [Async API](ASYNC_API.md). The recorded run additionally used a local secure runner with a 270-second external deadline. That runner parsed the user-authorized credential file as data without executing it; the credential file and local runner are not distributed with the connector.

- [Benchmark code](../test/integration/benchmark_sync_async.py)
- local artifact `e2e-sync-async-table-benchmark.log`
- local artifact `e2e-benchmark-results.json`
- local artifact `e2e-benchmark-preflight.log`
- local artifact `e2e-benchmark-before.json` and local artifact `e2e-benchmark-after.json`

Independent review checked equal timing boundaries, exclusive connection ownership, cleanup, matched workload, result validation and statistical summary arithmetic before execution. Connector aggregate source SHA-256 remained `d7fa32d981aeb91a77ea34245c4da0acd4574dba530aa5048f01c0c587e448b2` from the final five-environment coverage/package matrix.

After benchmarking, `atm1` was restored to its original suspended state. Read-back at `19:04:40Z` showed zero compute replicas and no compute pods; final verification retained the requested build versions and managed OAuth configuration. local artifact `e2e-final-runtime-ledger.json`.
