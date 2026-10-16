# Optional OAuth tracing

Install the `tracing` extra and use your application's existing OpenTelemetry
SDK and exporter configuration:

```text
pip install 'e6data-python-connector[tracing]'
```

Pass `tracing=True` to `Connection`, `AsyncConnection`, `ConnectionPool`, or
`AsyncConnectionPool`. Direct synchronous and asynchronous client-credentials
token providers accept the same option. Async applications also need the `async`
extra. The default is `False`.

The connector does not install a tracer provider, exporter, sampling policy, or
background exporter worker. Without an installed OpenTelemetry API or an
application-configured SDK, tracing has no effect on OAuth behavior.

Each actual token exchange produces one `oauth.token.acquire` client span.
Cached tokens and callers waiting for a shared renewal create no additional
exchange spans. The span ends when the exchange finishes, fails, or is cancelled.
Token and connection lifetimes do not hold spans open.

The connector carries standard `traceparent` context on token HTTP requests and
existing query gRPC calls. Shared providers and reused connections obtain the
current caller's context for each operation. Background result fetches preserve
the context of the operation that started their worker.

OAuth attributes contain only operation, grant type, transport, reported source,
outcome, and bounded failure reason. Credentials, token values, user identity,
session IDs, SQL, exception details, baggage, and arbitrary trace state are not
exported by this instrumentation. Trace context is diagnostic and does not change
authentication, authorization, retry, renewal, or query replay behavior.
