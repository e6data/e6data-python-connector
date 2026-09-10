# Shared OAuth credentials and expiry continuation

This is a Python-connector-only addition requested by the user after live qualification: a token must be shared between pools and threads. The original native async transport, caller deadlines, query ownership and no-ambiguous-replay contracts remain in force.

## Observed gap

Synchronous connections each construct a separate provider, including connections in one pool. An async pool shares a provider internally, but separate pools and standalone connections do not. The async provider owns an event loop, thread and HTTP client and cannot itself be shared across threads. Current live renewal tests invalidate a local cache; they do not establish natural server expiry.

## Required behavior

- Automatically share client-credentials token state among matching providers in one process, including sync connections, different pools, async tasks and different event-loop threads. No new connection arguments are required.
- Match the exact issuer endpoint, client identity, secret identity, scope, authentication method and provider policy (timeout and refresh leeway). A secret rotation, scope change or distinct policy cannot reuse old state. Store only an opaque keyed digest as the registry key; never print credentials, keys or bearer values.
- Do not share static tokens, legacy sessions, query routes, connection objects, asyncio tasks or HTTP clients. Async HTTP remains native HTTPX on its owning loop; sync HTTP remains the existing bounded blocking transport.
- Refresh once for concurrent callers with matching settings, including callers from different pools/threads and mixed sync/async callers. Select credentials for every protected request. Ordinary expiration does not recreate the gRPC channel or replay accepted work.
- Keep proactive refresh leeway and rejected-token comparison. An old rejection must not invalidate a newer published token. Permission denial must not trigger renewal. Failed refresh must not revive the rejected token.
- Each caller has its own wait deadline. One timeout or cancellation must not cancel renewal needed by another caller. A refresh has a fixed phase deadline including admission and HTTP work; no unbounded retry after owner failure.
- Closing one provider or pool must not invalidate shared credentials or another provider's refresh. Explicit invalidate intentionally invalidates the matching shared credential generation. Cached state has provider-object lifetime: weak registry entries disappear when the last provider reference and any active flight are collected. Existing synchronous connections retain their provider object after close, so closing a referenced sync connection does not promise immediate cache eviction or credential erasure. No new synchronous provider close API is introduced.
- Forked children construct fresh providers and cache state. An inherited provider must fail before acquiring inherited locks or returning inherited credentials. No cross-process cache or persistence is introduced.

## Ownership and coordination

Introduce one internal module for a weak, process-local state registry, a short registry lock, and thread-safe credential/flight state. The registry has opaque keys and no network work under its lock. Providers strongly hold their state while alive. Active refresh work retains its state until terminal completion.

A shared state contains the token, monotonic reusable-until deadline, invalidation generation and at most one registered refresh flight. A flight contains a threading.Event, terminal result, removable completion subscriptions, immutable phase deadline, generation and waiter ownership registrations. Joining/starting/selecting a cached token is atomic under a short state lock. Network I/O never runs under that lock. Completion snapshots and clears its callbacks under the lock, then invokes them outside it. Do not use concurrent.futures.Future callbacks because they cannot be detached.

The winning provider performs the actual exchange using its existing transport. Sync callers wait on the shared completion within their remaining budget; async callers use an event-loop-local future notified through a thread-safe completion callback. Async cancellation must detach only that waiter, not cancel the shared completion object. Completion/cancellation callbacks tolerate a loop closing and remove registrations so closed loops are not retained indefinitely.

Publication checks the flight identity, generation and deadline. A stale or invalidated result cannot publish. Final departure cancels an async-owned exchange on its owning loop; the flight stays registered until the transport actually terminates. A timed-out sync HTTP worker retains its exchange slot and registration until it exits, as before. A caller arriving during retirement waits within its own deadline before starting replacement work.

Provider close prevents new local callers, releases that provider's waits and disposes only its owned HTTP resources. An async provider owning a refresh still needed by other providers allows that bounded refresh to finish before HTTP disposal. Its close deadline may return a cleanup timeout while the registered disposal task continues; it must not strand the shared flight or invalidate peers. Last-waiter cancellation and explicit invalidation keep their distinct meanings.

If the owning event loop shuts down before that exchange finishes, the refresh task must terminalize its matching flight in a finally path with a sanitized OAuthError for foreign waiters. It must not propagate the owner's CancelledError into an uncancelled caller on another loop. That failure ends the current get_token call; no hidden retry extends its budget. A subsequent explicit get_token/request can start a replacement once the old transport is terminal. A caller's own cancellation still propagates CancelledError. Tests must close an owner loop while another loop waits and prove bounded failure, no stale publication and later successful acquisition.

Task creation must immediately register a done callback that idempotently terminalizes the matching flight even if cancellation occurs before the coroutine first executes; in that case its finally block never runs. Synchronous task-creation failure terminalizes the flight immediately. Add a pre-start task-cancellation regression. The done callback must not clear or overwrite a newer flight.

The concrete shared interface is get_state(settings), state.select(caller_deadline, force_refresh, rejected_token), state.detach(waiter), state.install_cancel(flight, callback), state.finish(flight, token, reusable_until, error), state.invalidate(), and flight.result/subscribe/done. select distinguishes cached value, leader, follower and retiring flight. A refresh deadline is computed from matching provider timeout at flight creation, never from the first caller's shorter wait deadline. Compatibility state views are locked and PID-guarded. Every cancellation callback and completion subscriber executes outside shared locks.

Each flight records whether its transport is async and its owning thread. A synchronous caller must fail promptly with OAuthError before joining a pending async-owned flight on that same thread, because blocking that thread would stop the flight's event loop. A cached token remains usable without waiting. This guard does not prohibit legitimate sync callers on separate worker threads.

Completion stores a sanitized error category/message rather than a live exception with credential-bearing traceback frames. result() raises a fresh OAuthError or TimeoutError per caller; unexpected owner failures become a generic OAuthError without storing their original cause. Local caller cancellation remains local. Fork handling recreates the registry map, lock and digest key in the child; providers record construction PID, including async providers that have not yet bound to a loop, and reject inherited use before any shared lock/cache access.

Synchronous overload policy: cache hits and matching-flight joins happen before exchange-capacity admission. A new sync leader attempts the existing four-slot semaphore without blocking; if all slots are occupied by distinct flights, it terminalizes its flight with TimeoutError immediately. No worker or admission queue is created, and there is no hidden retry. This deliberately replaces the previous synchronous admission wait so a short first caller cannot own a shared phase's admission lifetime. Reserved capacity is released if worker startup fails, while an already running worker retains its slot until actual termination. Async admission remains a native, bounded semaphore wait within its fixed phase deadline. Test saturated cache hits, matching-flight joins, fifth-identity rejection and later recovery.

Use thin compatibility views for the existing provider token/deadline fields where the current regression suite observes them. Avoid changing query RPC selection, retry policy, pool lease bookkeeping or transport ownership as part of this addition.

## Implementation ownership

1. Shared state/flight module and synchronous provider integration, with focused thread and identity-isolation regressions.
2. Async provider integration against the same state/flight interface, with native loop/thread ownership, cancellation, shutdown and cross-provider regressions. Pool code should need no change because all provider construction automatically joins matching shared state.
3. Live validation and documentation: root owns credential handling and target runtime. Test same-identity pools/threads and actual expiration where the existing issuer lifetime permits it, preserving query IDs and channels. No issuer policy change, fabricated token, legacy fallback or backend source change is part of this plan.

## Validation and acceptance

Write failing tests first for same-key reuse across distinct providers, two sync pools, two async pools, multiple threads/loops, mixed sync/async waiters, concurrent expiry/rejection, distinct secret/scope/endpoint isolation, close-one-owner survival, last-waiter departure, phase/caller deadlines, invalidation races, garbage collection and fork rejection. Reuse existing approved transport fixtures or actual native transports; do not invent a successful fake backend.

Run the complete offline suite and enforce coverage strictly above 80% for the full package and entire changed functions. Re-run the supported dependency matrix, package checks and independent production review after the shared state changes.

Live expiry evidence must distinguish: local cache invalidation, local monotonic expiry, the issuer-declared token lifetime, and actual rejection of the old bearer by the receiver. A successful continuation test retains the existing query handle and channel, refreshes credentials, retrieves the expected result, executes a subsequent query and clears both handles. Do not claim natural expiry from a forced-refresh test. If the real token lifetime exceeds a practical bounded window, record that limitation and retain an explicit opt-in natural-expiry test rather than changing the issuer or mislabeling local tests.
