# Recover downloaded envelopes after decode worker failure

User request: fix `decode_failed` as well as the message-size limits. The customer
exception chain is not available. This change fixes a reproducible local failure
mode; it does not claim that worker failure caused the customer incident.

## Evidence and scope

The existing real-process crash test shows that killing a worker fails an otherwise
valid envelope. Both cursors retain the serialized response until the entire
decoded envelope is accepted. Sequential decoding of those bytes is already the
fallback when the shared pool is busy or unavailable.

The runtime also stores a traceback-bearing exception after failure, and cleanup
leaves queued jobs and late results referenced. Regression tests will demonstrate
and guard release of these references while the connection/lease remains alive.
Both cursor failure caches also store and repeatedly raise the same exception.
Keep an unraised metadata-only template there and create a fresh raised exception
for each caller. The first caller must retain its original chained cause; the
cursor must not retain that caller's traceback or its result payloads.

This amends the earlier contract that every worker exit fails the envelope.
It changes only local decoding and its diagnostics. Consuming RPCs are never
retried, replayed or suppressed. The ongoing unlimited-message-size edits stay.

## Recovery contract

1. Classify actual worker exit and pipe I/O failures with a distinct internal
   ResultDecodeError subclass. Include only safe metadata: stage, worker index,
   PID, exit code when available, and transport exception type. Worker-reported
   decoding errors and malformed protocol replies remain fatal and distinct.
2. Snapshot decimal sticky flags before starting parallel work. On infrastructure
   failure, quarantine the runtime and wait for its existing cleanup to finish,
   using the original operation deadline. Do not restart workers or overlap the
   retry with live failed workers/I/O threads.
3. Clear partial parallel output and, after I/O threads stop, release slot results
   and queued jobs. Store a detached safe failure summary in runtime state, never
   the original traceback-bearing exception. The original caller error remains
   available when failure is propagated.
4. Recheck the lease, active-owner cancellation and remaining deadline. Restore
   the caller's pre-envelope decimal flags, then decode the same complete envelope
   once through the unchanged sequential decoder. Keep the active owner registered
   through cleanup/recovery so cancellation can prevent publication.
5. Recheck cancellation and the original deadline before returning. Existing cursor
   generation checks and atomic envelope acceptance remain the final publication
   boundary. Later calls use the existing unavailable-runtime sequential mode.
6. Do not recover TimeoutError, cancellation, closed/wrong-owner leases, system
   interruption, malformed worker replies, or worker-reported decoding failures,
   including MemoryError. If recovery decoding itself fails, propagate that error
   through the existing decode_failed cause chain, with no second attempt.

Cancellation must remain observable even when worker failure was recorded first.
Use an explicit cancellation latch for the active envelope, rather than relying
only on the runtime's first stored error. Sequential work remains non-preemptible,
as it is today, but its output must not be published after cancellation/deadline.

## Continuous downloading

The sync and async producers must keep downloading serialized batches without a queue cap while decoder workers run, fail, stop, or recover locally. Recovery must not hold cursor locks, retire the producer, add backpressure, or make another consuming RPC. Sync and async tests must stop real decoder workers, prove later envelopes finish downloading before decoding is released, then kill a worker and verify complete ordered rows with the same consuming RPC count.

## Diagnostics

Log recovery start/completion with safe worker metadata, chunk count and elapsed
time. Keep current query-ID-bearing outer exceptions and debug queue counters.
Do not log result values, SQL, credentials or arbitrary child exception text.
Unrecoverable worker data errors retain the child exception type. This is not a
promise that every possible decode_failed condition can be recovered.

## Tests and validation

- RED then GREEN with real spawned processes, actual pipe failure and serialized
  Thrift fixtures. Recover exact rows, values and order once after worker death.
- Verify no duplicate rows and no additional consuming RPCs in sync/async local
  transport coverage using existing fixtures.
- Malformed first/middle/last payloads and worker protocol errors still fail the
  complete envelope. Preserve the original sequential recovery exception.
- Cancellation during cleanup/recovery and expired budgets publish nothing and
  never create a fresh deadline. No replacement workers.
- Match sequential decimal values, flags and traps after partial parallel work.
- Weak-reference/ownership tests show a failed runtime releases envelope and
  result/job references after its threads stop, even while leases remain open.
- Failed cursor caches retain reason/query ID without a traceback or cause.
  Repeated failed fetches raise fresh errors without retaining response locals.
- Run full offline Linux suite and coverage. macOS currently cannot allocate its
  existing multiprocessing semaphore. Do not run a customer query or benchmark.
- Independent design review before runtime edits and implementation review after
  validation. No release or publish action is part of this change.

## Limits

An unbounded download backlog can still exhaust parent memory. Recovery does not
guarantee success after an OOM and does not add disk spooling or backpressure.
Real malformed data, unsupported data types and expired deadlines need their own
evidence-based corrections. This patch does not remove timeouts or hide errors.
