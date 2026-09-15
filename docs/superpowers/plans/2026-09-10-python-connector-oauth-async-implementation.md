# Python connector OAuth and async implementation plan

> For agentic workers: use superpowers:subagent-driven-development or superpowers:executing-plans to execute the reviewed tasks in order. Keep all implementation changes inside this connector repository. Checkboxes track future work, not completed implementation.

**Goal:** fix connector-owned OAuth lifecycle gaps and deliver native async counterparts for every implemented public connector operation, including pooling and SQLAlchemy integration.

**Architecture:** preserve the synchronous API and add the explicit `e6data_python_connector.aio` surface. Reuse existing protobuf messages/stubs with grpc.aio. Sync/async share pure validation and decoding helpers, while each owns its transport, authentication coordination and query state.

**Tech stack:** Python; grpcio current floor 1.65.1; asyncio with proposed Python 3.11-3.13 support; optional HTTPX `>=0.28.1,<1`; optional SQLAlchemy `>=2.0,<2.1`; unittest.IsolatedAsyncioTestCase, pytest and coverage tooling.

**Spec:** [connector-only design and complete function map](../specs/2026-09-10-python-connector-oauth-async-design.md).

**Baseline:** candidate HEAD `48d324ad3d36387caa534d42fa8f579317e9faa6`, PR 85 OPEN at planning time. Refresh and freeze the integrated target before implementation. No code, tests, deployment or Jira changes were executed for this plan. The earlier cross-component plan is superseded for implementation scope.

## Global constraints

- Only this repository changes, including tests and CI. No backend/protocol/generated-code edits or deployment/configuration changes.
- Preserve sync imports, credential-mode selection, return shapes and legacy behavior except the explicitly tested OAuth safety corrections.
- Native async network I/O; no wrapping entire sync methods in threads and no internal asyncio.run.
- No invalid-bearer fallback, new machine sessions, refresh-token grant, automatic ambiguous query replay or server revocation promises.
- No network operations in constructors or async properties. Pure helper/setter functions stay synchronous.
- Per-cursor ordinary-operation exclusivity, task-owned pool leases, loop/process ownership, pinned query routing and bounded cancellation/cleanup.
- Tests before each fix or feature. Complete declared unit and integration suites, greater than 80% overall package and new/changed-functionality coverage, baseline coverage not reduced. Existing coverage gaps must be measured and closed without omitting modules. All skips/errors remain visible.
- No new mock/fake services without explicit authorization. Use pure-input/state tests and configured real-service integrations with fault injection. Existing synthetic loopback tests remain labeled and do not establish product compatibility.
- Four exchange/work slots and a 64 MiB async received-message limit are proposed bounded library defaults to validate, not observed production limits. The spec fixes their ownership, admission rules and all proposed API defaults/version ranges.

## File ownership

All paths in task sections are relative to `/Users/vishalanand/Downloads/Projects/e6data-python-connector`.

| File | Responsibility |
| --- | --- |
| `e6data_python_connector/oauth_common.py` - new | Pure token configuration/response validation, expiry arithmetic, safe error categories; no transport/cache/lock. |
| `e6data_python_connector/oauth.py` - modify | Sync HTTP safety, monotonic cache, total token budget and bounded blocking exchange count. |
| `e6data_python_connector/e6data_grpc.py` - modify | Sync OAuth result failure state and bounded explicit/best-effort cleanup. |
| `e6data_python_connector/exceptions.py` - modify | Add narrowly scoped OperationalError subclasses for incomplete result and ambiguous submission; retain existing exception classes. |
| `e6data_python_connector/aio.py` - new | Public async imports/factory and runtime/extra checks; does not alter sync root imports. |
| `e6data_python_connector/async_oauth.py` - new | Native async token provider, one refresh task, waiter ownership and HTTP client lifecycle. |
| `e6data_python_connector/async_connection.py` - new | AsyncConnection, aio channel lifecycle, local routing, auth/session access and common RPC budget handling. |
| `e6data_python_connector/async_cursor.py` - new | Complete AsyncCursor API, result state, iteration and cancellation. |
| `e6data_python_connector/async_cluster_manager.py` - new | Native protected status/resume/readiness using the existing cluster protocol. |
| `e6data_python_connector/async_connection_pool.py` - new | Exclusive leases, capacity reservations, shared same-credential provider, release and shutdown. |
| `e6data_python_connector/async_work.py` - new | Small bounded offload runner for local decode/certificate reads; no generic task scheduler or credential storage. |
| `e6data_python_connector/async_dialect.py` - new | Separate SQLAlchemy 2.0 async DBAPI adapter and dialect registration. |
| `setup.py`, `requirements-test.txt`, `pytest.ini`, `test/conftest.py`, `test/collection_manifest.json` | Optional extras, consistent test constraints, import-safe explicit suite collection. |
| `test/unit/`, `test/integration/`, `.github/workflows/connector-tests.yml` - new | Pure regression/parity tests, opt-in real-service/fault tests, repeatable offline and integration gates. |
| `README.md`, `docs/ASYNC_API.md`, `docs/OAUTH_LIFECYCLE.md`, `examples/async_query.py` | Supported API, actual row shapes, security settings, examples, qualification and migration. |

## Test fixture contract

Task 1 creates a documented, opt-in `--integration-config` argument whose file contains target/package identifiers and references to credentials supplied outside the repository. It supplies `live_config.connection_kwargs`, `live_config.read_only_sql`, expected result rows, and a forwarding fault-proxy configuration. These are test harness interfaces, not existing production environment variables or invented endpoints. The fixture validates missing values before any connection and never logs credentials. Real-service tests below use that fixture through the test support loader. Without the argument, they are explicitly not executed and release qualification is incomplete.

No test example below was run. Examples describe tests to write; pure string token values are non-usable test inputs, not minted credentials. Each task follows the same red/green loop: write the named failures, run and record the expected failure, implement only the stated change, run the whole owning test file/suite, then commit that task once checks pass. Do not commit a knowingly failing step.

## Task 1 - Safe baseline, packaging and API contract tests

**Files:** modify `setup.py`, `requirements-test.txt`; create `pytest.ini`, `test/conftest.py`, `test/collection_manifest.json`, `test/unit/test_public_contract.py`, `test/unit/test_test_collection.py`, `test/integration/support.py`; update unsafe existing test module initialization only as required for safe collection.

**Produces:** a complete inventory of every old/new test module classified as unit, existing synthetic loopback, opt-in real integration or utility script; no import-time network activity. Canonical async method names are the spec tables. IsolatedAsyncioTestCase avoids adding another async test-runner dependency.

- [ ] Record branch/SHA/dirty state; isolate implementation without reverting existing work. Refresh PR/base and capture exact candidate dependency versions.
- [ ] Add tests proving default collection is inert with no credentials and excludes utility scripts. Preserve every existing test in the inventory; do not make failures disappear through silent exclusion.
- [ ] Add extras exactly as specified; keep sync imports independent of HTTPX/SQLAlchemy async extras. Generate exact test constraints from supported package metadata instead of the contradictory legacy requirements file.
- [ ] Add an import/API inventory check: all public functions in the spec have a planned async method, local disposition or explicit unsupported disposition. Confirm the current sync nested fetchone shape and existing aliases.
- [ ] Validate minimum/current grpcio, async Python 3.11/3.12/3.13 and sync import/build compatibility separately. Unsupported old sync combinations are baseline findings, not quietly removed support claims.

Example contract assertion:

```python
def test_async_extra_does_not_change_sync_exports():
    import e6data_python_connector as connector
    assert connector.__all__ == ["Connection", "Cursor", "ConnectionPool"]
```

Run: `python -m pytest test/unit/test_public_contract.py test/unit/test_test_collection.py -q` and the complete baseline collection/run report. Exit gate: all existing tests accounted for and no credential/network side effects during default collection.

## Task 2 - Secure, bounded synchronous OAuth renewal

**Files:** create `oauth_common.py`, `test/unit/test_oauth_contract.py`, `test/integration/test_token_transport.py`; modify `oauth.py`, existing `test/test_oauth_authentication.py` and related existing renewal cases.

**Interfaces:** `validate_token_response(payload, *, started_at, now, leeway) -> (token, reusable_until)` and `validate_token_endpoint(url)` are pure helpers. They validate strict positive lifetime/response shape and a finite conservative monotonic deadline; a valid token inside its early-renewal interval is returned once without reusable caching.

- [ ] Write invalid lifetime/type/URL tests, slow-response/backward-clock/rejected-token race tests and deadline exhaustion tests before changing provider behavior.
- [ ] Reject redirects before following them, enforce HTTPS, cap bytes, validate response type/lifetime and sanitize errors. Retain Basic/form authentication modes.
- [ ] Use one total token deadline for capacity admission, provider lock and exchange; preserve one publisher and late-result discard. Add a process-wide four-slot admission limiter with no queued background submissions. Retain stuck slots until the exchange actually terminates.
- [ ] Test real TLS certificate failure, cross-origin redirect zero-follow-up, withheld/slow response and repeated connection churn through the forwarding proxy. Bound caller latency and active workers separately; do not claim worker cancellation.
- [ ] Run full existing OAuth suites plus new pure/real transport cases. Update secure configuration/lifetime-error migration notes.

```python
def test_bool_lifetime_is_not_an_expiry_duration():
    import pytest
    from e6data_python_connector.oauth_common import validate_token_response
    from e6data_python_connector.exceptions import OAuthError
    with pytest.raises(OAuthError):
        validate_token_response(
            {"access_token": "unit-input", "token_type": "Bearer", "expires_in": True},
            started_at=100.0, now=101.0, leeway=60.0,
        )
```

Run: `python -m pytest test/unit/test_oauth_contract.py test/test_oauth_authentication.py -q`; real transport: `python -m pytest test/integration/test_token_transport.py --integration-config "$CONNECTOR_TEST_CONFIG" -q`. `$CONNECTOR_TEST_CONFIG` is a proposed local path variable populated by the operator, not a credential value.

## Task 3 - Synchronous OAuth result integrity and cleanup deadlines

**Files:** modify `e6data_grpc.py`, `exceptions.py`; create `test/unit/test_result_lifecycle.py`, `test/integration/test_sync_oauth_lifecycle.py`; extend `test/test_oauth_auto_resume.py`.

**Interfaces:** new `IncompleteResultError(OperationalError)` and `AmbiguousSubmissionError(OperationalError)` carry a known query ID when available and a bounded reason category, never credentials. State transitions are shared as a small pure helper only if both implementations use the same rules; do not refactor the entire sync cursor.

- [ ] Reproduce metadata failure after a received batch, aggregate failure after a successful batch, fetchmany-then-fetchall buffer handling, and caller retry after ambiguous delivery.
- [ ] For OAuth only, avoid post-consumption metadata work where possible; mark consumption ambiguous/incomplete when needed. Preserve the handle and stored failure; reject further fetches without another network call. Do not resubmit execute.
- [ ] Add one cleanup deadline covering metadata/token selection plus clear RPC timeout in Connection.clear, Cursor.clear and close. Explicit failure preserves its handle; best-effort close has bounded waiting and does not claim remote success.
- [ ] Keep legacy retry/session/return behavior unchanged; characterize rather than bundle unrelated arraysize/rowcount bugs.
- [ ] Verify actual server request counts, row sequence and retained handles through the real test stack/proxy; run all sync connector tests and record coverage.

Pure state example to implement with the new result-state helper or equivalent public behavior test:

```python
def test_ambiguous_first_batch_is_terminal():
    from e6data_python_connector.exceptions import IncompleteResultError
    error = IncompleteResultError("ambiguous_result", query_id="unit-query")
    assert error.query_id == "unit-query"
    assert "ambiguous_result" in str(error)
```

This exception test is supplementary; the required meaningful regression is the real dropped-batch response followed by a second fetch attempt sending zero further fetch requests. Run `python -m pytest test/unit/test_result_lifecycle.py test/test_oauth_auto_resume.py -q`, then the opt-in lifecycle module.

## Task 4 - Async connection transport and full connection API

**Files:** create `aio.py`, `async_connection.py`, `test/unit/test_async_connection_contract.py`, `test/integration/test_async_connection.py`; modify no generated bindings.

**Interfaces:** AsyncConnection accepts existing target/auth options plus the explicit async timeout defaults and max_receive_message_bytes in the spec. `await aio.connect(...) -> AsyncConnection`; `await open()/close()/reopen()`; all connection metadata/dry-run/clear/cancel/session operations have exact signatures and returns from the spec. `cursor()` and local cached checks are synchronous. QueryRoute is an immutable local record of target, query_id, engine_ip and strategy.

- [ ] Test that constructors are local-only, runtime/extra errors are clear, sync imports work without extras, and cross-loop/process use fails before dispatch.
- [ ] Bind existing stubs to grpc.aio channels, implement TLS certificate loading off the event loop, enforce finite received-message size and propagate remaining deadlines to every protected RPC. Reject every insecure async OAuth channel before dispatch, including standalone cluster-manager use in Task 8.
- [ ] Implement all connection operations and a single-flight legacy authentication path. Initially static OAuth token injection is enough for native transport tests; Task 5 supplies client-credentials renewal.
- [ ] Keep local route state owned by target/connection. No sync global routing dictionary, blocking lock, time.sleep or synchronous channel may appear in the async network path.
- [ ] Test real v1/v2 query metadata/dry-run, legacy session behavior, static OAuth, close/reopen restrictions and channel readiness at grpcio minimum/current versions.

```python
import inspect

def test_async_connection_network_methods_are_explicit():
    from e6data_python_connector.aio import AsyncConnection
    for name in ("open", "close", "reopen", "get_session_id", "clear",
                 "query_cancel", "dry_run", "get_tables", "get_columns", "get_schema_names"):
        assert inspect.iscoroutinefunction(getattr(AsyncConnection, name)), name
    assert not inspect.iscoroutinefunction(AsyncConnection.cursor)
```

Run: `python -m pytest test/unit/test_async_connection_contract.py -q`, plus complete connection real-service cases. Shape inspection complements, not replaces, real awaited transport validation.

## Task 5 - Native async OAuth renewal and bounded work ownership

**Files:** create `async_oauth.py`, `async_work.py`, `test/unit/test_async_oauth_state.py`, `test/integration/test_async_token_lifecycle.py`; connect provider into `async_connection.py`.

**Interfaces:** `AsyncClientCredentialsTokenProvider.get_token(force_refresh=False, deadline=None, rejected_token=None)` and `invalidate()/close()` are awaited. A standalone connection owns its provider; a pool supplies one shared same-credential provider without transferring close ownership. AsyncClient is private to that owner. The process-wide work runner has four occupied slots until actual worker completion and never accepts queued submissions without a slot. It supports reserving a slot before a batch RPC and transferring the same reservation to decoding without reacquisition.

- [ ] Write tests for expiry arithmetic shared with sync, one refresh task, many waiters, cancellation of one versus all waiters, rejected old token after replacement, invalidation/close during refresh and late response discard.
- [ ] Implement one owned HTTPX client with TLS verification, no redirects/environment proxies, byte cap, finite HTTP connection/pool/read/write timeouts, and a shared-task-owned oauth_timeout deadline including admission. No sync urllib calls in this provider.
- [ ] Enforce four-slot per-loop network-exchange capacity. Shield only the shared task from individual waiter cancellation, count its waiters, and dispose terminal work before releasing its slot or starting replacement.
- [ ] Write asymmetric waiter-budget tests for token acquisition and legacy authentication: short first/long second and long first/short second. Shared deadlines derive only from phase creation and owner configuration, never the first caller's remaining budget; each caller timeout only detaches that waiter. Test admission expiry under the same ownership rule.
- [ ] Implement bounded decode/certificate work admission. Thread cancellation cannot release capacity early; no credentials/channels enter the worker. Prove four running workers and, in Task 7, four received/decoding batches remain the process-wide bounds during cancellation, cross-loop use and connection churn.
- [ ] Run heartbeat, real issuer outage/recovery, TLS/redirect and pool-owned-client-close tests. Keep transport-helper DNS lifetime an observed limitation rather than a forced-cancellation claim.

Real integration test skeleton, implemented as an IsolatedAsyncioTestCase using the explicit config loader:

```python
async def test_parallel_calls_keep_one_token_exchange(self):
    import asyncio
    provider = self.live.new_async_provider()
    try:
        tokens = await asyncio.gather(*(provider.get_token() for _ in range(20)))
        self.assertTrue(all(token == tokens[0] for token in tokens))
        self.assertEqual(self.live.token_proxy.completed_exchange_count, 1)
    finally:
        await provider.close()
```

The proxy forwards to the real configured token issuer and counts exchanges without storing bearer bodies. Run the complete async state and token integration modules.

## Task 6 - Complete AsyncCursor execution, metadata and control API

**Files:** create `async_cursor.py`, `test/unit/test_async_cursor_contract.py`, `test/integration/test_async_queries.py`; connect AsyncConnection.cursor.

**Interfaces:** every execute/executemany/status/explain/explain_analyse/metadata/discovery/cancel/clear/close method and local property listed in the spec. `execute` returns query ID; `get_rowcount/get_description/refresh_metadata` explicitly perform I/O. get_rpc_metadata is an explicit compatibility method, never a logging hook.

- [ ] Write function-map coverage tests and real v1/v2 parameterized execution tests; capture handle before execute/metadata awaits.
- [ ] Implement one ordinary-operation gate per cursor, with internal helpers avoiding recursive locking. Different cursors may progress concurrently; same-cursor overlap raises ProgrammingError.
- [ ] Implement cancel/close as control operations that can interrupt a blocked call; track its active call so late completion cannot mutate closed/failed state.
- [ ] Implement sequential executemany, intermediate cleanup, failing index/handle reporting and total deadline. Preserve final-result-only and nontransactional semantics.
- [ ] Implement cached properties and explicit refresh. Preserve nested fetchone contract when Task 7 adds results. Initialize new async local properties correctly without rewriting sync properties.
- [ ] Add explicit unsupported behavior for placeholders and rollback; no server feature implementation or success stubs.

```python
async def test_execute_retains_handle_after_metadata_failure(self):
    from e6data_python_connector.aio import connect
    from e6data_python_connector.exceptions import OperationalError
    async with await connect(**self.live.connection_kwargs) as conn:
        async with conn.cursor() as cursor:
            with self.live.rpc_proxy.drop_next_metadata_response():
                with self.assertRaises(OperationalError):
                    await cursor.execute(self.live.read_only_sql, timeout=1.0)
            self.assertIsNotNone(cursor.query_id)
            self.assertEqual(self.live.rpc_proxy.execute_count, 1)
            await cursor.clear()
```

The public read-only query_id property is produced here for diagnostics/cleanup in addition to the execute return value. The classifier preserves the original gRPC status as its cause and propagates cancellation unchanged. Run all connection/cursor contract and query integration tests.

## Task 7 - Every async fetch form, result integrity and cancellation

**Files:** extend `async_cursor.py`, `async_work.py`; create `test/unit/test_async_result_state.py`, `test/integration/test_async_results.py`.

**Interfaces:** `fetchone/fetchmany/fetchall/fetch_batch`, async `fetchall_buffer`, async iterator, `IncompleteResultError`, cached leftovers and rownumber exactly as the spec states.

- [ ] Write exact-row/order/shape cases for all public fetch entry points, mixed buffered calls, empty results and terminal EOF.
- [ ] Ensure metadata is available before consuming a batch where supported; reserve fetch/decode capacity before dispatch, commit bytes/handle before later awaits, then decode under the same reservation. Release only after transport and decode actually terminate. No background result prefetch.
- [ ] Add RESULT_FAILED transition for ambiguous transport even with no observed rows, decoding failure and aggregation failure after earlier results. No later fetch RPC from any public entry point and no partial aggregate labeled complete.
- [ ] Propagate cancellation while preserving ambiguity/handle; do not call execute or cursor-advancing fetch again automatically. A new token alone does not restore an uncertain batch.
- [ ] Test async iterator/generator close, early break, enclosing cursor cleanup, buffered rows and loop responsiveness under large decoding and parallel metadata calls. Assert finite message-size enforcement, outstanding received/decoding batch count and retained bytes during cancellation/churn; count decoded/buffered/application aggregation separately rather than claiming a total memory ceiling.

```python
async def test_fetchone_then_fetchall_keeps_remaining_rows(self):
    cursor = await self.live.executed_async_cursor()
    try:
        first = await cursor.fetchone()
        rest = await cursor.fetchall()
        self.assertEqual(first + rest, self.live.expected_rows)
    finally:
        await cursor.close()
```

Also repeat after dropped first/later batch responses and assert every subsequent fetch raises IncompleteResultError with unchanged receiver fetch count. Run the complete async result modules and sync lifecycle regression modules.

## Task 8 - Native async cluster resume and routing continuity

**Files:** create `async_cluster_manager.py`, `test/unit/test_async_routing.py`, `test/integration/test_async_resume.py`; integrate with connection/cursor prepare path.

**Interfaces:** `await AsyncClusterManager.resume() -> bool`, existing exact resume/status requests, last_successful_strategy and async metadata provider. Each shared resume phase owns an immutable start-plus-auto_resume_timeout deadline; individual callers only bound their own waits. No implementation of the suspend placeholder.

- [ ] Write isolated target/query routing tests, no global-map use, same-pool concurrent resume single-flight, and owner isolation across credentials/loops.
- [ ] Port the existing supported suspension signal and safe strategy correction explicitly; do not generalize from arbitrary UNAVAILABLE/UNKNOWN/error text. Golden contract tests pin these existing special cases until a server-owned structured contract exists.
- [ ] Await status, at most one resume mutation, then bounded readiness with asyncio.sleep and current token per call. Persist target/auth-scoped pending mutation state outside the waiter/flight object, distinguishing acknowledged from outcome-unknown. After a reply or last-waiter departure, replacement flights inspect status and never repeat an unresolved resume; ready resolves pending state, suspended alone does not.
- [ ] Allow one safe preparation retry after readiness. Never retry possibly submitted execute or a fetch. Keep total async public-operation deadline even while entering resume, capped additionally by auto_resume_timeout.
- [ ] Test token expiry during polling, denied credentials, timeout, cancellation of one/all waiters, route change while old query retains strategy, and no-password fallback. Cover short-first/long-second and reverse waiter budgets; surviving waiters keep the shared phase deadline. Cover last-waiter cancellation followed immediately by a new waiter and assert no duplicate mutation. Reject insecure OAuth construction of a standalone manager with zero RPC dispatch.

```python
def test_route_identity_includes_target():
    from e6data_python_connector.async_connection import QueryRoute
    a = QueryRoute(target=("unit-a", 443), query_id="same-id", engine_ip="unit-plan-a", strategy="blue")
    b = QueryRoute(target=("unit-b", 443), query_id="same-id", engine_ip="unit-plan-b", strategy="green")
    assert a != b
```

QueryRoute is a local immutable record produced by Task 4; these strings are pure test input, not production addresses. Live resume uses an externally prepared suspended test target and records the existing server outcome without modifying its configuration from this plan.

## Task 9 - Async pool and exclusive task leases

**Files:** create `async_connection_pool.py`, `test/unit/test_async_pool_state.py`, `test/integration/test_async_pool.py`; export via aio.

**Interfaces:** AsyncConnectionPool open/close_all/get_connection/return_connection/get_connection_context/get_statistics and pooled-wrapper cursor/close_cursor/context methods from the spec. Constructor defaults and max+overflow invariant are fixed there.

- [ ] Write a pure capacity/lease state model covering reserve, publish, cancel, return, retire, close and double-return. Every failure restores exactly one reserved slot.
- [ ] Implement async condition/queue bookkeeping with no lock held during I/O. Reserve before creating; no thread-ID cache or cached shared cursor. A cancelled acquire cannot leak its slot. Give each checkout a fresh lease revision and wrapper; enforce task, active lease and revision checks on every high-level operation and response publication.
- [ ] Give one provider to a same-credential pool and ownership-aware references to its connections. Leased connection disposal does not close the shared provider; pool close does.
- [ ] On release, invalidate the lease revision before cancelling/cleaning owned operations; use an internal lease-bound cleanup capability. Bound all cursor cleanup and health checks, dispose uncertain connections, retire overflow, and wake waiting tasks. Cancelled release still finishes bounded bookkeeping and re-raises cancellation.
- [ ] Stop new leases during shutdown, wake waiters, drain only within budget, and discard late returns. No required async destructor.
- [ ] Validate async-specific thread/loop/process misuse, parallel tasks on one thread, pool exhaustion/recycle/cancellation/churn and pre-ping denial against real service. Retain old wrapper/cursor references, return and reacquire on the same task, and prove all stale operations/close attempts fail before RPC without affecting the new lease.

```python
async def test_two_tasks_get_distinct_leases(self):
    import asyncio
    async def hold(pool, entered, release):
        async with pool.get_connection_context() as lease:
            entered.put_nowait(lease)
            await release.wait()
    async with self.live.new_async_pool(max_size=2, max_overflow=0) as pool:
        entered, release = asyncio.Queue(), asyncio.Event()
        tasks = [asyncio.create_task(hold(pool, entered, release)) for _ in range(2)]
        try:
            first, second = await entered.get(), await entered.get()
            self.assertIsNot(first, second)
        finally:
            release.set()
            await asyncio.gather(*tasks)
```

Run all pool state/integration cases and existing sync pool tests. Add cancellation at each reserve/create/publish/release await, not only happy-path parallelism.

## Task 10 - Async SQLAlchemy adapter and complete integration surface

**Files:** create `async_dialect.py`, `test/unit/test_async_dialect_contract.py`, `test/integration/test_async_sqlalchemy.py`; update setup entry points and async-sqlalchemy extra.

**Interfaces:** `e6data+asyncio` with SQLAlchemy 2.0 AsyncEngine. Adapter bridges normal DBAPI/dialect callbacks to native awaits; implements connection/cursor close, execute/executemany, row conversion, metadata, fetch/iteration, ping and rollback/reset. Reuse local types/compiler/reflection support declarations from the current dialect.

- [ ] Write failing registration and dependency-floor tests. Plain e6data dialect remains synchronous; no connection is created at import time.
- [ ] Implement the SQLAlchemy-owned adapter pattern against its pinned supported 2.0 source/API. No blocking loop runner or async def replacements for synchronous dialect hooks.
- [ ] Keep secrets in connect_args/creator, separate connector options from grpc_options and normalize row shape only at the adapter boundary.
- [ ] Cover all network reflection through `AsyncConnection.run_sync`, async buffered/streaming result consumption, cancellation, pre-ping, reset and disposal. Do not stack the custom pool under SQLAlchemy's pool.
- [ ] Test direct rollback unsupported while SQLAlchemy's nontransactional pool reset is the documented no-op; do not silently swallow arbitrary network/auth errors to make ping pass.

```python
async def test_async_sqlalchemy_execute_and_reflection(self):
    from sqlalchemy import inspect, text
    engine = self.live.new_sqlalchemy_async_engine()
    try:
        async with engine.connect() as conn:
            rows = (await conn.execute(text(self.live.read_only_sql))).all()
            self.assertEqual([list(row) for row in rows], self.live.expected_rows)
            names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_schema_names())
            self.assertIn(self.live.schema_name, names)
    finally:
        await engine.dispose()
```

Run all async dialect tests at the selected minimum/current SQLAlchemy 2.0 versions and all existing synchronous dialect regressions.

## Task 11 - Complete suites, artifacts, examples and independent implementation review

**Files:** `.github/workflows/connector-tests.yml`, test constraint files, `README.md`, `docs/ASYNC_API.md`, `docs/OAUTH_LIFECYCLE.md`, `examples/async_query.py`; complete any remaining inventory coverage.

- [ ] Publish the full API map, local-versus-await distinctions, nested fetchone shape, cancellation uncertainty, context-managed generator/pool usage, security defaults and unsupported functions.
- [ ] Add unit/packaging CI for pull requests without live credentials. Protected/manual real integration job uses the explicit configuration; absence means skipped qualification, never a pass.
- [ ] Run `python -m pytest --cov=e6data_python_connector --cov-branch --cov-report=xml --cov-report=term-missing` over the complete configured offline suite, then the complete declared integration suite with `--integration-config`. Execute or explicitly account for documented `python -m unittest test.tests test.tests_grpc` and other legacy suites from the inventory.
- [ ] Measure overall package and changed-line/function coverage greater than 80%, baseline preservation, event-loop heartbeat under slow HTTP/RPC/decode, active task/thread/connection counts after cancellation and close, wheel install/import, sync/async parity and dependency floors. Close measured baseline coverage gaps and fix failures; do not substitute a focused subset or omit modules from the denominator.
- [ ] Build the wheel only after tests; install into clean environments for base, async and async-sqlalchemy extras. Recheck no optional import leaks and exact runtime constraints.
- [ ] Request independent post-implementation requirement/behavior validation and production-readiness review. Fix blockers and rerun affected checks before proposing publication. Publication and Jira updates are separate actions, not implied by this planning request.

Usage target, with application-supplied configuration and no embedded credentials:

```python
from e6data_python_connector.aio import AsyncConnection

async def consume(config, sql):
    async with AsyncConnection(**config) as connection:
        async with connection.cursor() as cursor:
            query_id = await cursor.execute(sql)
            async for batch in cursor.fetchall_buffer():
                consume_batch(query_id, batch)
```

`consume_batch` is the caller's local processing function, not a new connector API. For pooled use, replace the connection context with `async with pool.get_connection_context() as lease` and use its local cursor factory.

## Ordering, review gates and rollback

Task 1 precedes all code. Tasks 2-3 deliver sync corrections. Tasks 4-5 establish native transport/provider; Task 6 depends on both, Task 7 depends on Task 6, Task 8 integrates with Task 6, Task 9 follows Tasks 5-8, Task 10 follows native cursor/pool contracts, and Task 11 validates the complete delivery. Pure fixture/documentation work can run in parallel, but do not assign two workers overlapping production files. Each task has its own test/commit/review checkpoint.

No backend policy decision is required to write these connector changes. Live qualification still needs a real supported test stack and authorized fault/resume window. A server failure is recorded with its exact RPC/version, while connector-only work remains scoped here.

Rollback installs the prior connector wheel and uses the unchanged sync entry points after orderly resource closure. Do not migrate live async channels between loops/packages, discard unknown query outcomes or silently replay work. This plan does not authorize changing server flags, signing keys or client registrations. Completion means the connector acceptance matrix passed; it is not proof of server-wide expiry/revocation correctness.
