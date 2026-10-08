# Result prefetch and parallel decode validation

Historical snapshot for commit `359cb49`. The September 23
[continuous-download follow-up](2026-09-23-continuous-result-download.md)
changes the one-envelope fetch limit and requires separate measurements.

Ticket: PLT-10376. Local implementation and validation complete. Customer
qualification and package publication remain deferred.

## Behavior

The existing `enable_result_batch_v2=True` flag enables prefetch and eligible
parallel decoding for sync and async connections. The default remains false.
Each cursor can hold one pending envelope; the process allows four pending
prefetches and shares two spawned decoder workers. Parallel decoding admits one
envelope at a time. Saturation and unsupported Decimal settings use sequential
decoding.

Rows and original chunk order are preserved. An envelope is published only after
all its chunks decode successfully. Cancellation and cleanup keep old work from
publishing into a reused cursor. RPC exceptions reach the caller unchanged;
only V2 `UNIMPLEMENTED` falls back to V1. Consuming RPCs are not replayed.

Opt-in requires ordinary GIL-enabled CPython 3.11-3.13 and an import-safe,
guarded main entry point. Sync V2 now defaults to a finite 64 MiB receive limit;
explicit finite positive limits are supported. See the [connection
documentation](../../../README.md) for the activation contract.

## Verification

The complete offline suite ran in Linux containers against the final source:

| Environment | Passed | Skipped | Expected failure | Statement and branch coverage |
|---|---:|---:|---:|---:|
| Python 3.11, minimum dependencies | 2,242 | 37 | 1 | 90.62% |
| Python 3.11, current dependencies | 2,242 | 37 | 1 | 90.62% |
| Python 3.12, current dependencies | 2,242 | 37 | 1 | 90.59% |
| Python 3.13, current dependencies | 2,242 | 37 | 1 | 90.61% |

All lanes passed the 80.01% gate with no failures. The 37 skips need live
integration configuration. The expected failure is an existing legacy
no-cache suspend/resume case. Added executable statement coverage is
958/1043 (91.85%). This does not mean every existing source file exceeds 80%.

Earlier coverage runs produced unreadable worker SQLite sidecars. Those files
were retained, and affected lanes were rerun with fresh container-local SQLite.
The final reports have no coverage warnings; the earlier cause is not proven.

Independent review closed all confirmed code findings. Reviewers separately ran
180 sync/shared/runtime checks and two async sets of 11 and 12 checks. The local
merge verdict is GO; customer activation still needs target qualification.

A local wheel was installed and exercised outside the source tree. All 39
packaged Python files match the final source. Real workers preserved exact
values, types and order across 6 rows and 15 columns. Both sync and async
connector constructors were rejected inside workers. Both workers exited, with
no named semaphore growth. This wheel was built for validation only and was not
published.

## Fixed-data performance comparison

Both versions used the same frozen synthetic Thrift files and final harness in
Linux ARM64, Python 3.12.14, with a two-CPU quota and 2 GiB memory limit. The
baseline is commit `a93e23c`. Each pipeline trial drained 524,288 rows in 64
original chunks through 8 V2 RPCs. Medians use three trials.

| Profile | Simulated delay per RPC | Before | After | Change |
|---|---:|---:|---:|---:|
| Mixed | 0 ms | 2.423 s | 2.111 s | 12.9% faster |
| Mixed | 100 ms | 3.365 s | 2.200 s | 34.6% faster |
| Wide strings | 0 ms | 1.982 s | 2.061 s | 4.0% slower |
| Wide strings | 100 ms | 2.887 s | 2.138 s | 25.9% faster |

Drain time includes ordered, type-preserving row-digest checks, which overlap
prefetch. The added delay is synthetic loopback latency, not customer network
latency or bandwidth. Worker startup is excluded from these steady-state
medians and reported separately in the raw results.

Isolated decoding uses 65,536 rows in 8 chunks and seven warm samples. Parallel
times include process communication:

| Profile | Serial median | Parallel median | Change |
|---|---:|---:|---:|
| Numeric | 37.45 ms | 29.16 ms | 22.1% faster |
| Mixed | 157.65 ms | 127.04 ms | 19.4% faster |
| Wide strings | 48.39 ms | 60.59 ms | 25.2% slower |

All 14 final reports passed fixture, harness and source identity checks, exact
row counts, ordered typed digests and worker cleanup checks. Pipeline RPC counts
and terminal behavior also matched.

Two workers add about 0.45-0.47 seconds of startup, CPU use and memory. Sampled
parent-plus-worker memory reached about 507 MiB in the wide-string pipeline.
Sampling can miss short peaks. The receive limit does not bound total Python
memory. Wide-string decoding and the no-delay wide-string pipeline regressed;
there is no universal speedup claim.

## Reproduce and inspect evidence

Run the full offline suite in Linux with the repository test dependencies:

```bash
python -m pytest --cov=e6data_python_connector --cov-branch --cov-fail-under=80.01
```

Use [the performance guide](../../../test/performance/README.md) for fixture
generation, serial/parallel decode and pipeline commands. Generate once and
reuse the exact fixtures for comparisons, with the same runtime and resource
limits. Keep tests and other measurements out of timed runs.

Raw local evidence is under
`artifacts/prefetch-implementation` in the original project checkout. It includes
`VALIDATION.md`, `ADVERSARIAL_REVIEW.md`, `PERFORMANCE.md`, matrix reports,
installed-wheel verification and all final measurement JSON files. Frozen inputs
are under `artifacts/local-decode-baseline`. These artifacts are not packaged or
committed. The tested source fingerprint is
`c16ae979f93ee363778164f23b016f83099fb1f3799eb295ad10c5602683a6f1`.

No customer query ran for this validation. Deployed planner compatibility,
customer CPU/memory limits and completion within the 900-second timeout remain
unverified. Rollback uses new connections with `enable_result_batch_v2=False`
after closing old cursors/connections and confirming background work retires.
Never automatically replay a partially consumed query.
