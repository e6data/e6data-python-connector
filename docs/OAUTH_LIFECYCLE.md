# OAuth lifecycle and uncertainty

These are connector implementation contracts, not proof of deployed engine acceptance, scope enforcement or auto-resume readiness. Existing synchronous calls and the optional native async API share response validation. Their transport and cancellation mechanisms differ.

## Token acquisition

A client-credentials configuration supplies a real HTTPS `token_url`, `client_id`, `client_secret` and optional scope. HTTP Basic is the default client authentication method; explicit POST-body authentication is supported. Embedded endpoint credentials, fragments and redirects are rejected. TLS verification remains enabled. Token requests do not inherit environment proxy settings.

The provider validates a nonempty ASCII access token without whitespace/control characters, a case-insensitive Bearer token type and a positive integer `expires_in`. Responses are bounded to 64 KiB. Error handling reports fixed descriptions instead of response bodies or credentials.

Expiry uses monotonic time starting before the HTTP exchange, including time spent waiting for the response. The default renewal margin is 60 seconds. A token that is still valid but already inside that margin can serve the current acquisition; it is not cached as fresh. A token expired during exchange is rejected. Supplying an external `access_token` does not enable renewal; its lifecycle remains application-owned.

Providers automatically share cached credentials and one concurrent acquisition across connections, pools, threads and async event loops in the same process. Sharing requires identical token endpoint, client ID, secret, scope, authentication method, timeout and renewal margin. Registry keys are opaque keyed digests. Changing any matching setting creates separate state; static access tokens and legacy sessions are not shared by this mechanism.

Rejection-triggered refresh identifies the rejected token so a newer token already obtained by another caller is not unnecessarily replaced. Each caller has its own deadline; one timeout or cancellation does not cancel an acquisition still needed by others. A shared exchange has its own fixed deadline. Sync exchanges have four process-wide slots: cache hits and existing exchanges remain available at capacity, while a new distinct exchange fails promptly with `TimeoutError`. Async exchanges use bounded admission on their owning loop. Do not block an event loop with a synchronous call waiting for a refresh owned by that same thread; the provider rejects that deadlock with `OAuthError`.

Only credential state is shared. Connections, query handles, async tasks and HTTP clients retain their original ownership. Closing an async provider or pool detaches its callers and disposes its transport without invalidating peers; an owned exchange still needed by peers can finish within its original deadline. Explicit provider `invalidate()` invalidates matching shared credentials. The registry uses weak references, so cache lifetime follows retained providers and active work. A closed synchronous connection still retains its provider while the connection object remains referenced. Construct new providers after a fork; inherited providers reject use in the child process.

## RPC behavior

OAuth sends bearer metadata on native RPCs and uses the OAuth empty-session convention. A present rejected bearer does not fall back to legacy username/password authentication. The async API requires TLS for OAuth; a locally opened channel does not mean the engine accepts the token.

Renewal does not make all RPCs safe to retry. The implementation allows a bounded auth refresh/retry only for operations classified safe at their call site, such as preparation and discovery. Execution and consumptive result fetches are not blindly replayed. Requests for a known query use its recorded target, planner and strategy. A newly observed strategy is applied only when active routes allow the change.

A precise suspension denial may enter auto-resume coordination. Status polling, one mutation attempt and bounded readiness waiting share the configured budgets. Cancellation or an uncertain mutation reply does not authorize an additional resume mutation. Generic unavailable responses are not evidence that a cluster is suspended.

## Result integrity and cleanup

| Observation | Caller-visible meaning | Application action |
| --- | --- | --- |
| Submission reply lost after dispatch | `AmbiguousSubmissionError`, or cancellation with unresolved submission state | Preserve any known handle; investigate status; do not resubmit automatically |
| Execute/metadata fails after preparation | A known handle may still need cleanup | Use status/cancel/clear where available, then close |
| Consumptive fetch outcome or local aggregation is uncertain | `IncompleteResultError`; later fetches stay failed | Do not treat partial rows as a complete result or restart at the next batch |
| Caller cancels waiting | Server completion/cancellation is not established | Let bounded cleanup finish and inspect cleanup status |
| Local close completes with `cleanup_error` | Remote cleanup is unconfirmed | Retain operational context needed to investigate without logging credentials |

OAuth and async fetches use strict decoding: detected malformed vectors, invalid
non-null decimal payloads and inconsistent populated batch dimensions raise
`IncompleteResultError` while retaining the known query handle. Later fetches
remain failed. A serialized zero-row batch marks the result exhausted, so later
fetches do not advance the server cursor again. Ordinary string values are
preserved. Synchronous legacy-authentication calls retain their existing decoding
compatibility behavior.

Use cursor/connection or lease contexts. Closing a batch generator alone does not close the cursor. Explicit cancellation requests cancellation; clear releases the known query and resets the native cursor after a confirmed response. Shutdown bounds cleanup and releases local resources even when remote cleanup cannot be confirmed. SQLAlchemy pool reset is the documented nontransactional no-op; it is not transaction rollback support.

## Verification boundary

The offline tests exercise validation, local state and existing isolated tests. Real issuer acquisition does not prove query RPC acceptance. Query success does not establish governance, suspended-to-ready behavior or all renewal boundaries. Qualify against the explicitly configured real service with expected rows, runtime identity and any operator-provided fault facilities. A skipped live test leaves the relevant behavior unqualified.

Never commit tokens, client secrets, credential-bearing URLs, RPC authorization metadata or response bodies. Test configuration resolves credential fields from operator-provided environment-variable references, as described in [Async API](ASYNC_API.md). No deploy flags, server auth settings or credentials are created by these changes.
