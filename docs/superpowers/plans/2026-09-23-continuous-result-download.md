# Continuous result download alongside decoding

Ticket: PLT-10376. User-authorized scope update on September 23, 2026.

Status: locally implemented, tested and independently reviewed. See the
[validation and measurements](2026-09-23-continuous-result-download-validation.md).
Customer qualification and publication remain separate.

## Requirement and selected design

The final user instruction is to download all serialized batches while
deserialization runs concurrently. Downloading must not wait for decoder or
application progress. Use the existing `enable_result_batch_v2=True` flag,
with an uncapped in-memory queue of raw Protobuf responses. Remove the current
one-envelope and four-process-wide-prefetch limits. Keep one consuming RPC
active per query to preserve the engine cursor and rotated-session sequence.
The default-off path and per-RPC receive-size limits remain unchanged.

Start the continuous producer after the first successful nonterminal V2
response, before decoding it. Sync uses one thread per active query; async uses
one producer task per active query. Each producer repeatedly requests the next
response, records its latest session, queues it, and immediately requests the
next until EOF, failure or explicit retirement. It never decodes rows. Existing
foreground/worker decoding consumes the queue in order and still publishes an
entire decoded envelope atomically. No new public option or disk spool.

Memory use is intentionally not bounded by queue size. This is the user's
accepted requirement, not an unimplemented safety gate. Record queued bytes
and envelopes for diagnosis without imposing admission or a queue cap.

## State and ownership

Use a small shared `ContinuousResultStream` record in `result_prefetch.py`.
It owns a thread-safe deque, producer completion handle, current transport,
latest cleanup session, retired/finished flags, queue counts and last-consumed
RPC duration. It does not own a cursor or connection. Sync waits on its
condition; async waits on a producer-notified event without holding an async
work reservation merely to download. Producer transport and decode work have
separate cancellation ownership.

The record API includes `set_handle`, `set_transport`, `clear_transport`,
`push(response, rpc_seconds)`, `fail(error, rpc_seconds)`, `finish`, `take`,
`wait(timeout)`, `retire`, and `ready`, `settled`, `retired`, `session_id`,
`elapsed` properties. `take` returns the oldest response or raises the original
queued exception. `settled` means producer and actual transport ended, not that
the consumer emptied the queue. Retirement drops queued payloads and wakes
consumers, cancels active transport/producer, and retains latest cleanup identity
until settlement. Late completion may update only this old record.

Queue entries preserve original response/chunk order. Only the consumer changes
public row buffers, strategy, row counters and protocol. The producer freezes
query route/generation/lease, builds requests from its own latest session, and
refreshes auth metadata using existing helpers with internal ownership checks.
Check retirement and identity again after metadata preparation. Sync holds the
cursor lifecycle lock across the final check, nonblocking `.future()` creation
and transport registration, so retirement cannot slip between them. Async has
no await between the final check, task creation and transport registration.
Never hold a lifecycle lock during auth, transport waiting or decoding.

Register the producer completion handle before launching it. The sync Future
is marked running before handoff; its lifetime includes metadata, dispatch and
final transport settlement. Retirement cannot report settlement while that
producer is running. A transport registered after retirement is immediately
canceled and retained until its actual completion/session capture.
The raw async RPC has its own retained task. Capture its returned session in a
completion hook (and synchronously when inspecting an already-completed task)
before declaring the producer settled, even if cancellation interrupts queue
publication. Late callbacks from an older transport must not regress a newer
transport's captured session.

A decoded older queued response must not roll back the newest download session.
Cleanup always uses the latest session captured by the producer record. Stale
producers cannot submit into a new query or borrower after cancellation/reuse.

## Deadlines, errors and cleanup

Each background RPC gets the configured finite RPC/operation budget at its own
dispatch. Its deadline never extends once started. This replaces tying every
future background request to the initiating fetch's deadline. Public operation
deadlines still bound foreground waiting and decoding; an expired or canceled
active operation retires the producer. A successfully queued response does not
expire while the application is idle. Preserve async whole-fetchall deadlines.

Empty nonterminal responses use bounded exponential backoff and a finite
no-progress deadline; reset the no-progress window only on a nonempty response.
An EOF response may contain rows and must be queued before stopping. No request
after EOF. No consuming-RPC replay. A failure stops the producer and queues the
original exception after earlier successful responses, which remain consumable.
Only UNIMPLEMENTED switches future requests to the existing V1 fallback once
the consumer reaches that error; it cannot skip previously queued V2 responses.
Decode failure takes priority for that envelope and retires remaining download.

Close, clear, cancel, reexecute, connection disposal and pool return retire all
queued/in-flight work. Preserve existing bounded cleanup, late-session recovery,
failed-retirement ownership, PID checks and worker retirement. Sync must not join
its own producer thread from a completion path. Async cancellation/event-loop
shutdown must not erase a late completed response before session capture.

## TDD, measurements and delivery

Write failing tests first for more than four responses arriving while first
decode is blocked, strict RPC sequencing with session rotation, EOF-with-data,
empty-response backoff/deadline, errors after queued successes, UNIMPLEMENTED,
consumer pauses, active fetch timeout, cancellation at metadata/dispatch/receipt,
close/pool reuse, late sessions and raw payload release. Include real loopback
gRPC and existing flag-off/DB-API/SQLAlchemy regressions. Do not change public
fetch return shapes or the parallel decoder in this follow-up.

Keep the frozen fixtures. Compare against committed one-envelope prefetch
359cb49 and older sequential V2 a93e23c. Record engine drain time separately
from decoding/consumer drain, plus first-use time and memory. These are synthetic
results, not customer proof. Prior benchmark numbers remain historical.

Run the full offline suite and dependency matrix, coverage above 80%, installed
wheel lifecycle checks and independent final review. Local implementation only;
no customer query, deployment, push or package publication. Live engine
qualification remains deferred.
