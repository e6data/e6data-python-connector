# Local synthetic decode baseline

This harness measures the existing `decode_result_batches` function using local,
serialized Thrift chunks. It makes no engine requests and uses no customer data.
It does not add prefetch, worker pools, or connector behavior.

Generate the files once, save them with the result, and reuse those exact files
when comparing a later decoder change. `run` never generates missing data.

## Fixed input

The default seed is `20260922`. Each profile has 8 chunks of 8,192 rows, for
65,536 rows. Each run decodes all 8 chunks as one complete envelope.

| Profile | Columns | Values |
| --- | --- | --- |
| `numeric` | 4 | LONG row index, DOUBLE score, INTEGER count, BOOLEAN flag |
| `mixed` | 6 | LONG row index, DOUBLE score, nullable STRING, DATE, DECIMAL128, constant STRING |
| `wide_strings` | 5 | LONG row index and four 64-byte ASCII strings |

For row index `i`, score is `(i % 1000) + 0.25`, count is `i % 10000`, and
flag is true for even rows. The mixed label is `row-` plus the eight-digit index;
every seventeenth label is null, including row zero. Its payload still contains
one string per row. Date is `1970-01-01` plus `i % 365` days. Decimal is
`Decimal(i % 20000 - 10000) + Decimal('0.37')`, serialized as a signed 16-byte
integer with scale 2. The constant string is `constant`, using a constant vector.
Each wide string is the hex SHA-256 of `seed:i:column`, with column indexes 0 to 3.
The seed affects the wide strings; the other profiles use the row formulas.

These are bounded synthetic inputs. Their column counts and type mix do not
represent a customer query. The wide profile targets about 17-20 MiB of serialized
input; each result records the actual byte count.

`manifest.json` records the schema and recipe versions, seed, columns and types,
generation settings, per-file SHA-256 and size, row count, and expected ordered
row digest. The expected digest is computed from the logical recipe without
calling the decoder. It preserves nulls and Python types, including Decimal text
and its trailing zeros. The loader checks the manifest hash, profile schema,
chunk paths, file hashes, sizes, and count metadata before decoding. The adjacent
manifest hash detects accidental edits; it is not a signature.

## Run inside Linux

Use the prepared, network-disabled `e6-local-decode-baseline` container. It mounts
the clean connector source at `/work`, this directory at `/harness`, and saved
results at `/artifacts`. Run Python only in the container. Set `PYTHONPATH` to
`/work:/harness` when preparing another environment. Keep the CPU and memory
limits and package versions the same for a later comparison.

Generate once:

```bash
docker exec e6-local-decode-baseline /home/runner/venv/bin/python \
  /harness/local_decode_baseline.py generate --output /artifacts/fixtures
```

Run each profile in a fresh process, using a new report path each time:

```bash
docker exec e6-local-decode-baseline /home/runner/venv/bin/python \
  /harness/local_decode_baseline.py run --dataset /artifacts/fixtures \
  --profile numeric --repeats 7 --output /artifacts/numeric.json
docker exec e6-local-decode-baseline /home/runner/venv/bin/python \
  /harness/local_decode_baseline.py run --dataset /artifacts/fixtures \
  --profile mixed --repeats 7 --output /artifacts/mixed.json
docker exec e6-local-decode-baseline /home/runner/venv/bin/python \
  /harness/local_decode_baseline.py run --dataset /artifacts/fixtures \
  --profile wide_strings --repeats 7 --output /artifacts/wide_strings.json
```

Generation and report output refuse to overwrite existing paths. For small test
inputs, generation accepts `--rows-per-chunk`, `--chunks`, and `--seed`. A measured
run requires at least 3 repeats and at least 1 warmup; defaults are 7 and 1.

## What the result means

Input files are checked and loaded into memory before timing. The report keeps
the first decode, warmup decodes, and measured decodes separate. "Cold" means the
first decode in that process, not a cleared OS cache or a fresh container.

Each sample uses `perf_counter` for wall time and `process_time` for process CPU
time. Both timers cover only the complete decoder call, including Thrift reading,
value conversion, and row construction. Row hashing and count checks happen
after the timers stop. Each decoded result is released before the next sample.
Every cold, warmup, and measured result must pass the same digest and count check.
Validation also requires the decoder's eager lists at the envelope, chunk, and
row levels, with the original chunk boundaries and row/column counts. Lazy
iterators are rejected without consuming them, so deferred decoding cannot run
after the timer and appear as a faster result.

The JSON contains every wall and CPU sample, min/median/max values, rows per
second, and serialized input MiB per second (`1 MiB = 1,048,576 bytes`). It does
not report a p95 from seven samples. Linux `ru_maxrss` is recorded in KiB and
converted to bytes. This is the process lifetime peak, including imports, input,
warmup, and validation. It is not per-decode allocation or a child-process total.

The report also records Python and dependency versions, platform, CPU affinity,
cgroup CPU/memory limits, Thrift native decoder availability, source file hashes,
harness hash, fixture hashes, and invocation settings. Host CPU activity and
container scheduling can affect timings. This baseline does not measure network,
engine time, streaming latency, or the effect of concurrency.

## Focused checks

```bash
docker exec -e TMPDIR=/artifacts/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -e COVERAGE_FILE=/artifacts/harness.coverage e6-local-decode-baseline \
  /home/runner/venv/bin/python -m pytest -q -p no:cacheprovider \
  --basetemp=/artifacts/harness-tmp --cov=/harness --cov-report=term-missing \
  /harness/test_local_decode_baseline.py
```

The focused tests use tiny real Thrift inputs, literal expected values, damaged
files and manifests, wrong row values/order/types/counts, invalid run settings,
and CLI round trips. They set no timing thresholds. Run the repository's complete
test suite separately before finalizing a change.

## Compare prefetch and parallel decoding

`parallel_decode_benchmark.py` reuses the frozen dataset and compares eager
serial decoding with two spawned workers. It records first decode, warm samples,
worker startup, parent-plus-worker CPU, sampled aggregate RSS, source hashes and
worker cleanup. File reading and ordered, type-preserving row checks are outside
each decode timer. Run in Linux with a guarded script entry point:

```bash
python -m test.performance.parallel_decode_benchmark \
  --dataset artifacts/local-decode-baseline/fixtures --profile mixed \
  --mode parallel --output artifacts/decode-mixed-parallel.json
```

Use `--mode serial` for the same measurement without process decoding. The
runtime chooses sequential decoding if admission is occupied or the caller's
Decimal settings differ from the worker settings. Run each mode in a fresh
process. RSS samples can miss short peaks and exclude the multiprocessing
resource-tracker process. CPU samples use Linux process clock ticks.

`local_result_pipeline.py` uses the real connector fetch path and generated gRPC
service on loopback. Its server is an explicit synthetic test double. It injects
an unissued query handle and session, so it measures result fetching rather than
authentication or query execution. Each response repeats a frozen envelope.
The candidate starts workers explicitly because this harness skips execute.

```bash
python -m test.performance.local_result_pipeline \
  --dataset artifacts/local-decode-baseline/fixtures --profile mixed \
  --envelopes 8 --repeats 3 --server-delay-seconds 0.1 \
  --output artifacts/pipeline-mixed.json
```

The delay is simulated server latency, not a bandwidth or customer model. Total
drain time includes row-digest checking, which can overlap prefetch. Fetch wait
is the accumulated time inside `next()` calls. Neither metric is a pure network
or deserialization measurement. Compare both alongside the isolated decoder.
Startup is separate from each drain; add it to the first drain for a cold-use
comparison. Aggregate run CPU includes startup, all trials, row checks, the local
server and worker cleanup. RSS includes those objects and is sampled every 10 ms.

For immutable source comparisons, run from a neutral directory and put the
selected source first in `PYTHONPATH`, followed by `test/performance`. Use
`python -m local_result_pipeline` in that case. Check the imported source path
and hashes in every report. Use the same harness, files, limits and delay for
both sources. Do not run other tests or benchmarks during timed runs. Retain
all raw samples and report regressions as well as gains.


### Continuous-download comparison

The pipeline report now separates `client_download_seconds` from
`end_to_end_seconds` and `decode_seconds` for each trial. Download time runs
from the first result RPC dispatch to receipt and Protobuf parsing of the final
response, before its Thrift/row decoding. A test-only transport wrapper records
this timestamp inside the gRPC response deserializer. It also checks that
consuming RPCs never overlap and records serialized Protobuf bytes per response.

Download, decode and row-validation work can overlap, so these durations must
not be added together. `decode_seconds` sums the connector's existing envelope
decode diagnostics, including its envelope acceptance work. Use the isolated
decoder harness when measuring only deserialization. End-to-end time still
includes row-digest checking.
Worker startup remains separate. The added measurement uses the same generated
wire serializers and the same frozen payloads for every compared source. It
measures loopback client receipt, not production engine execution or network
bandwidth. Use a new output path; retain the earlier one-envelope-prefetch
reports as historical evidence.
