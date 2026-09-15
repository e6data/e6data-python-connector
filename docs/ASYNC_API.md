# Native asyncio API

This branch implements an optional native asyncio connector. Release qualification is incomplete: local tests do not establish successful operation against a deployed engine. See the implementation reports for measured results and remaining gates.

## Installation and lifecycle

The async API requires Python 3.11 or newer. The qualification matrix targets 3.11, 3.12 and 3.13; a matrix entry is not a claim that it has passed. Existing synchronous imports remain available.

```sh
python -m pip install 'e6data-python-connector[async]'
# For SQLAlchemy AsyncEngine integration:
python -m pip install 'e6data-python-connector[async-sqlalchemy]'
```

These install names describe the extras built by this branch, not confirmation of a published release. The async extra requires HTTPX >=0.28.1,<1. The SQLAlchemy extra also requires SQLAlchemy[asyncio] >=2.0,<2.1. The declared gRPC floor remains 1.65.1.

Construction validates local configuration. Await `open()` or use `async with` to allocate native channels. `open()` alone does not prove server authentication or readiness. `aio.connect(**config)` constructs and opens a connection. Configuration is read-only after construction. Connections belong to one process, thread and event loop.

```python
from contextlib import aclosing
from e6data_python_connector.aio import AsyncConnection

async def consume(config, sql, consume_batch):
    async with AsyncConnection(**config) as connection:
        async with connection.cursor() as cursor:
            query_id = await cursor.execute(sql)
            async with aclosing(cursor.fetchall_buffer()) as batches:
                async for batch in batches:
                    consume_batch(query_id, batch)
```

`config`, `sql` and `consume_batch` are application inputs. A generator's `aclose()` ends iteration; the enclosing cursor context owns query cleanup, including early exit. `consume_batch` should be short and local, or the caller should explicitly offload slow work.

## Authentication and bounded work

Supply exactly one complete method: legacy `username`/`password`, client credentials (`client_id`, `client_secret`, `token_url`, optional `oauth_scope`), or an externally managed `access_token`. OAuth requires `secure=True` and certificate verification. Use `ssl_cert` for a PEM certificate or certificate-file path when an application CA is required. Client-credentials authentication supports `client_auth_method='basic'` or `'post'`. The token endpoint requires HTTPS. Do not put credentials in SQLAlchemy URLs or diagnostic output.

Defaults are `operation_timeout=600`, `oauth_timeout=10`, `cleanup_timeout=10`, `auto_resume_timeout=300` seconds and `max_receive_message_bytes=67108864`. Optional per-call `timeout` narrows the operation budget. Preparation, execution, metadata, decoding and fetch phases share the operation deadline rather than each receiving a new full budget. Each separate fetch call has its own deadline. `fetchall_buffer(timeout=...)` applies that timeout to each batch fetch.

Client-credentials token state is shared automatically with matching sync and async connections, including different pools and event-loop threads in one process. The issuer endpoint, client ID, secret, scope, authentication method and provider timing policy must all match. Transports and connection ownership remain local. Closing one pool does not invalidate another pool's credentials. See [OAuth lifecycle](OAUTH_LIFECYCLE.md) for refresh, cancellation, capacity and fork behavior.

`grpc_options` is separate from these connector settings. An unlimited receive size and TLS authority overrides are rejected. Cancellation stops waiting and attempts bounded cleanup. It does not establish that the server stopped processing.

## Public API map

| Object | Local operations and cached properties | Awaited operations |
| --- | --- | --- |
| Connection | constructor, `cursor(catalog_name=None, db_name=None)`, `check_connection()`, `check_strategy_change()`, configuration, `target`, `strategy`, `client`, `cleanup_error` | `open()`, `close()`, `reopen()`, async context enter/exit |
| Session | no network session property | `get_session_id()`, `get_re_authenticate_session_id()` |
| Connection discovery | none | `get_tables(catalog, database)`, `get_columns(catalog, database, table)`, `get_schema_names(catalog)`, `dry_run(query)` |
| Connection query controls | none | `clear(query_id, engine_ip=None)`, `query_cancel(engine_ip, query_id)` |
| Cursor execution | `query_id`, `rowcount`, `description`, `rownumber`, `lastrowid`, `arraysize`, `cleanup_error` | `execute(operation, parameters=None)`, `executemany(operation, seq_of_parameters)` |
| Cursor results | no hidden network properties | `fetchone()`, `fetchmany(size=None)`, `fetch_batch()`, `fetchall()`, async iteration and `fetchall_buffer(query_id=None)` async generator |
| Cursor metadata | cached `rowcount`/`description` | `update_mete_data()` (also `refresh_metadata()`), `get_rowcount()`, `get_description()`, `get_rpc_metadata()` |
| Cursor discovery | none | `get_tables()`, `get_columns(table)`, `get_schema_names()` |
| Cursor query controls | `query_id` | `status(query_id=None)`, `explain()`, `explain_analyse()`, `cancel(query_id=None)`, `clear(query_id=None)`, `close()` |
| Compatibility | `setinputsizes`, `setoutputsize` are no-ops | `commit()` is a no-op; `rollback()`, `poll()` and `fetch_logs()` raise `NotSupportedError` |

The native `fetchone()` and native async iterator preserve the synchronous connector's outer-list shape: `[[value1, value2]]`, or `None` when exhausted. `fetchmany()`/`fetchall()` return lists of rows; `fetch_batch()` returns a batch or `None`. `fetchall_buffer()` yields batches. SQLAlchemy removes that outer list at its DBAPI boundary.

Before result metadata arrives, `rowcount=-1` and `description=None`. Explicit refresh methods perform network I/O. `get_rpc_metadata()` returns current credential-bearing routing metadata and should not be logged. `check_connection()` reports local channel lifecycle only. A cursor permits one ordinary operation at a time; cancellation/clear can interrupt it. Clear the previous query before executing another on the same native cursor. `executemany` does this between its parameter sets and exposes `parameter_index` on a failure.

## Failure and routing contracts

A query handle is pinned to the target, planner and blue/green strategy that accepted preparation. A retained handle belongs to its connection. Discovery may observe a newer strategy without moving an active query to it.

If submission may have reached the engine without a definitive reply, `AmbiguousSubmissionError` preserves any known `query_id`. Do not automatically resubmit. Cancellation can likewise leave an unknown submission outcome even though the caller receives `CancelledError`. If a consumed result batch has an uncertain reply or cannot be decoded/assembled safely, the cursor raises `IncompleteResultError` and later fetches fail rather than replay or silently skip rows. The known handle remains available for status and explicit cleanup until closed.

`cancel()` requests cancellation and invalidates further result consumption. `clear()` clears the known query and resets the cursor after success. `close()` attempts bounded cleanup and releases local resources; inspect `cleanup_error` for unconfirmed cleanup. A successful local close does not prove remote deletion. Exact suspension denial may trigger coordinated resume and a bounded readiness wait. Generic unavailable errors do not authorize replay.

## Pool ownership

```python
from e6data_python_connector.aio import AsyncConnectionPool

async def query_with_pool(config, sql):
    async with AsyncConnectionPool(min_size=0, max_size=4,
                                   max_overflow=0, **config) as pool:
        async with pool.get_connection_context() as lease:
            async with lease.cursor() as cursor:
                await cursor.execute(sql)
                return await cursor.fetchall()
```

The pool exposes awaited `open()`, `get_connection(timeout=None)`, `return_connection(lease)` and `close_all()`, an async `get_connection_context()`, and local `get_statistics()`. Capacity includes idle, leased, creating and retiring connections and is bounded by `max_size + max_overflow`. Defaults are minimum 2, maximum 10, overflow 5, checkout timeout 30 seconds, recycle 3600 seconds and `pre_ping=True`. Leases belong to the acquiring task and become invalid on return. Do not retain a cursor or underlying connection for use after return, or hand the lease to another task. Closing a pool revokes its leases and performs bounded cleanup. The pool shares token acquisition and resume coordination for its configured target/auth identity.

A lease also exposes awaited `close_cursor()` and `close()`; context exit returns it to the pool. `AsyncClusterManager` exposes awaited `resume()` and `close()` for callers supplying their own real target/auth configuration; normal connections and pools manage it internally. The async token provider exposes awaited `get_token()`, `invalidate()` and `close()`; ordinary applications configure credentials on the connection.

## SQLAlchemy 2.0

```python
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

async def sqlalchemy_query(config, sql):
    engine = create_async_engine('e6data+asyncio://', connect_args=config,
                                 pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            rows = (await connection.execute(text(sql))).all()
            schemas = await connection.run_sync(
                lambda sync: inspect(sync).get_schema_names())
            async with connection.stream(text(sql)) as result:
                async for row in result:
                    pass  # application processing
            return rows, schemas
    finally:
        await engine.dispose()
```

Use `connect_args` or a configured creator for credentials. SQLAlchemy 2.0.16+ supports `async_creator`; earlier supported versions can use `connect_args`. Its pool owns native connections directly; do not supply a custom connector pool lease beneath it. Buffered execution awaits result collection and query cleanup before returning a synchronous Result. Streaming consumption stays awaited. Schema/table/column reflection uses `run_sync`. Other inherited reflection placeholders retain the synchronous dialect's limitations, including `has_table()` returning true without an existence check. Pool pre-ping performs authenticated schema discovery. SQLAlchemy rollback/reset remains a nontransactional no-op; direct native rollback is unsupported.

## Reproducible validation

Install with `python -m pip install -c test/constraints/current.txt -e '.[async-sqlalchemy]' -r requirements-test.txt`. Run the complete configured collection:

```sh
python -m pytest --cov=e6data_python_connector --cov-branch --cov-report=xml --cov-report=term-missing --cov-fail-under=80.01
python -m pytest test/integration --integration-config /absolute/path/to/operator-config.json --tb=no
```

The full coverage denominator includes the entire package, including generated and synchronous modules. The workflow enforces a threshold strictly above 80%; focused async passes alone do not satisfy it. Measured results and remaining live qualification are recorded in [implementation validation](PLT-9922-VALIDATION.md). Wheel build/import steps run only after the offline gate passes.

Real configuration uses JSON with `target_id`, `package_id`, `connection_kwargs`, `read_only_sql` and `expected_rows`; `schema_name`, target/package versions and operator fault configuration are optional. Supply actual identifiers and expected results. Credential fields `password`, `client_id`, `client_secret` and `access_token` must be environment references such as `{"env": "YOUR_APPLICATION_CLIENT_SECRET_VARIABLE"}`, not literal credential values. The operator provides those environment variables to the test process. No file or credentials are created by the workflow.

Offline collection skips real-service tests. A separate manual live job requires an explicitly chosen protected GitHub environment, trusted runner and existing absolute configuration path. It fails on empty or skipped qualification and does not upload live output artifacts. This workflow does not provision a runner, environment or secret. Historical integration modules and manual utilities are classified in `test/collection_manifest.json`. `python -m unittest test.tests test.tests_grpc` is a separate legacy runner that requires its documented environment and is not claimed by the new live suite. Do not run arbitrary historical scripts against a target merely to make collection green.
