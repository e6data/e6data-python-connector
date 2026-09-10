# PLT-9922 Python connector implementation validation

September 11 pre-push status: the connector now shares OAuth token state across matching sync/async connections, pools and threads in one process. Three new real-issuer sharing tests pass. The final Python 3.12 suite passes 1,844 tests, with 89.9243% full-package line-and-branch coverage and 83.5282% whole changed-function coverage. Natural server-expiry continuation remains unqualified. Section 14 records this latest addition; section 13 records the earlier successful resume, configured-catalog query tests and benchmark. Historical results below are retained and do not qualify later source changes. No connector release or ticket transition was performed.

Source base: `48d324ad3d36387caa534d42fa8f579317e9faa6`. Implementation was isolated on local branch `vishal/plt-9922-python-async`; the user requested publication to the existing `mcp/oauth2-client-credentials` branch. This builds on the existing OAuth candidate, not just main. Code changes are confined to this Python connector repository, including its tests, documentation and CI. Protocol bindings and backend source were not changed. A later explicit user instruction authorized the separate runtime configuration restoration described below.

Detailed runtime and test logs referenced by filename are retained locally under the ignored `.superpowers/sdd/2026-09-10-python-connector-oauth-async-implementation/` evidence directory. They are not bundled or published with the connector. The test code, reproduction commands and measured summaries are included here.

## 1. Requirement coverage matrix

| Requirement | Status | Evidence and remaining qualification |
| --- | --- | --- |
| Preserve sync imports and add optional async extras | Complete | `setup.py`, `aio.py`, `test/unit/test_packaging_collection.py`; base import does not load HTTPX. |
| Explicit safe test collection and baseline | Complete | `conftest.py`, `test/collection_manifest.json`, integration config validation tests; all 52 historical modules classified. |
| Strict secure OAuth token lifecycle | Partial | Real issuer acquisition and renewal during an open query pass with handle continuity. Natural expiry/rejection and multi-batch expiry remain unqualified. |
| Sync OAuth result continuity and cleanup | Partial | `e6data_grpc.py`, `test/unit/test_result_lifecycle.py`, `test/unit/test_sync_review_regressions.py`; real multi-batch/drop-response cases blocked. |
| Native async connection and complete public cursor map | Partial | Real configured-catalog query, fetch variants, parameters, executemany, explain, metadata, dry-run and reopen pass. Catalog-less v1 remains blocked by the server default catalog. |
| Ownership, cancellation, terminal results and no replay | Partial | Cursor, connection, work and pool regression suites; real cancellation after server admission and fault-proxy tests remain missing. |
| Bounded local decoding and response size | Partial | `async_work.py`, finite channel receive setting; real worker admission/cancellation/fork tests pass. Large received-batch memory/event-loop measurements pending. |
| Cluster recovery and pinned routing | Partial | Real authenticated Suspended-to-Running transition, ready endpoints, operator/Envoy ACK and successful SELECT verified. Concurrent registered routes pass. Expiry during resume and natural auto-suspension remain unqualified. |
| Exclusive async pool leases and bounded shutdown | Partial | Real parallel pooled queries and stale-lease rejection pass. Local uncertainty/retirement checks pass; real fault injection remains unqualified. |
| SQLAlchemy async buffered/streaming/reflection | Partial | Live buffered results, streaming, reflection, executemany and pre-ping pass after correcting the SQLAlchemy 2.0.52 soft-close hook. Real dropped-response qualification remains open. |
| API documentation, example and CI | Complete | `ASYNC_API.md`, `OAUTH_LIFECYCLE.md`, application-input example, pinned matrix workflow; workflow lint passed. |
| Version matrix and clean package installation | Complete locally | All five Python/dependency configurations passed 1,812 tests each and the strict coverage gate. Clean wheel installation/import evidence is recorded below. Live qualification remains separate. |
| Greater-than-80-percent full package and changed-function coverage | Complete locally | Full denominator retained. Final Python 3.12-current coverage 89.7161%; entire changed functions plus new modules 82.2485%; changed executable lines 84.3296%. Baseline was 19.15%. No package files or new exclusions removed from measurement. |

Completed locally: 5. Partial: 8. Partial is not a claim of release completion.

## 2. Existing behavior preservation

The existing sync manifest suite passed 229 tests with one documented pre-existing xfail. Stale test assertions were corrected using existing behavioral fixtures and real separate threads for pool exhaustion. The existing sync import surface, successful cursor reuse and nontransactional SQLAlchemy reset remain. The strict HTTPS/token-response behavior and terminal OAuth result failure are intentional documented safety changes. Existing generated Thrift/protobuf code is untouched.

The final complete Python 3.12 offline run passed 1,812 tests, skipped 10 opt-in live tests and retained the existing xfail. Sixteen warnings remain visible, including historical pytest return-value warnings, two datetime deprecations and the generated experimental gRPC wrapper warning. These results establish the tested local behavior, not every historical live integration.

Coverage work exposed and corrected negative-epoch floor arithmetic and removed `collections.Iterable` usage. It also exposed malformed-vector/decimal errors being converted into placeholder values. OAuth and async fetches now use strict decoding and retain terminal errors and known handles. Valid nulls, strings and serialized empty EOF remain supported; empty EOF prevents further fetch dispatch. Synchronous legacy decoding retains its previous compatibility behavior.

## 3. Edge case findings

Independent review reproduced and implementation corrected routing-lock deadline overrun, inherited fork capacity starvation, lost submission uncertainty during close, concurrent channel initialization leaks, post-close initialization, inherited shared-task cancellation, stale pool aliases and SQLAlchemy reuse after uncertain submission. Each has a regression using actual synchronization, native channels or actual AsyncEngine objects. Preparation routing metadata is now caller-owned; a concurrent cursor cannot overwrite another cursor's accepted strategy.

Final independent recheck found no confirmed implementation blocker remaining within its bounded scope. Its ship decision is DO NOT MERGE pending required qualification. The reviewer independently ran 137 async tests and 52 sync tests, all passing, and reported 90/100 confidence for the reviewed changes. The review is bound to source digests and recorded in local artifact `final-independent-review.md`. This does not satisfy coverage or live release gates.

The subsequent coverage/scalar/strict-decoder delta received an independent read-only review with no remaining blocker found in that scope. The reviewer independently exercised real corrupt/valid Thrift payloads and all six sync/async decode-phase state cases, verified minimum protobuf compatibility and checked denominator integrity. Frozen hashes and limits are recorded in local artifact `coverage-independent-review.md`.

## 4. Failure scenario findings

Actual supplied-target integration result: 8 failed, 1 passed, 1 skipped. Concurrent real token acquisition and invalidate/renew succeeded. Every query/discovery failure, through both sync and async paths including pooling and SQLAlchemy, carries gRPC `UNAVAILABLE` with `authentication unavailable`. That initial run did not establish the exact rejecting server component or deployed software version; later configuration findings do not retrospectively prove the rejecting hop. No fallback to legacy authentication or ambiguous query replay was introduced.

Bound non-listening local sockets exercise real gRPC failure/cancellation behavior. No new fake server responses are used to claim service compatibility. Live resume has not run; the dedicated target/window question remains pending. The user separately authorized restoring the missing OAuth test configuration. The exact deployed operator `84b1929` requires `spec.console.machineAuth.queryEngineEnabled`, but the installed CRD omitted that field. A UID/resourceVersion-guarded patch restored only the missing boolean schema property with default false. A second guarded patch enabled it for `ggr-ui-vishal1-cd46e4b9`. No image version was changed.

Read-back verified NamespaceConfig generation/observedGeneration 16, phase Ready and `queryEngineEnabled=true`. The generated xDS Deployment generation/observedGeneration 8 is ready with `QUERY_ENGINE_OAUTH_ENABLED=true`. Planner's existing `config.properties` already contained `OAUTH_ENABLED=true`; no Planner env patch was needed. Retest changed both valid-token sync query and async discovery responses to `UNAVAILABLE: status: 503, cluster is suspended`. A missing-bearer query was independently rejected with `UNAUTHENTICATED: authentication denied`. These results verify the restored authentication path, not successful query execution. The two query tests still fail on suspension.

Final state read-back: `atm1` retains UID `d6dd7270-342f-4ce7-abae-b3ac71896a13`, generation 29, Suspended/green, with all three compute Deployment replica counts zero. The proposed exclusive 10-minute resume test, five-minute readiness bound and restoration to suspension still await user approval. A supplied fault-proxy contract, legacy configuration, real token expiry during fetch and successful metadata/query operation remain necessary for full qualification. How or when the installed CRD lost the field was not established.

## 5. Security findings

OAuth requires verified TLS, HTTPS token endpoints, no redirects/environment proxies, strict Bearer/expiry responses and bounded exchange size/capacity. Target/auth settings are immutable. Pool aliases preserve the lease revision; advanced raw stubs remain explicitly outside high-level policy. Error categories do not contain credential values. The user-provided credential script was parsed as data and never executed; raw credentials were not written to repository artifacts or printed.

Real issuance success does not establish server authorization, revocation, governance or cross-tenant controls. No backend security posture is claimed by this connector change.

## 6. Observability findings

`AmbiguousSubmissionError`, `IncompleteResultError`, known query IDs, structured chained gRPC causes and `cleanup_error` expose uncertain operations. Local pool statistics expose reservation states and failed cleanup. Full runtime request correlation and receiver readiness remain unqualified. Root has identified deployed operator `84b1929` while investigating the missing CRD property; this does not establish the query receiver version or rejecting hop. No new server dashboards, metrics pipeline or alert deployment is included in this connector-only change.

## 7. Missing test coverage

The full package, including generated and legacy modules, exceeds 80% without omissions. Real Thrift codec/client/processor contracts, both protobuf runtimes, generated gRPC base-servicer behavior, binary decoding and cursor state are exercised. Local generated base-servicer tests verify UNIMPLEMENTED responses; they do not simulate successful query-engine behavior. The tests do not prove successful legacy real-service parity, every successful metadata return shape, expired-token continuation after a first batch, forwarding-proxy dropped-response behavior, large-result retained-memory limits, server-injected corrupt payloads or live resume/cancellation outcomes. Historical manual/utility scripts remain explicitly inventoried rather than silently passed.

## 8. Remaining risks

- Coverage gates pass. Keep the 80.01% full-package CI threshold and preserve the changed-function audit.
- Release blocker: successful query-path and fault/resume/legacy qualification incomplete. Use a working explicitly identified test stack and dedicated approved mutation window.
- Compatibility dependency: candidate OAuth base must be integrated before releasing this branch from main.
- Some instrumented runs emitted a multiprocessing resource-tracker KeyError during interpreter teardown while pytest exited successfully. Its cause is not proven; it remains visible in local logs and is not described as fixed.

No database migration is involved. The user-authorized test configuration change reconciled the xDS Deployment without changing its image version. Reinstalling the previous connector wheel restores client code, but cannot prove the outcome of already submitted queries; never automatically replay an uncertain query during rollback.

## 9. Confidence

Moderate for the locally exercised state/ownership and negative paths, limited for successful real-service compatibility. Evidence includes TDD regression sequences, complete offline collection, passing coverage gates and independent defect reproductions. Missing live qualification prevents a production-readiness conclusion.

## 10. Final production readiness assessment

INCOMPLETE. Local coverage gates pass. Complete successful real-service compatibility/failure tests before merge/release qualification; no skipped or failing live case counts as qualified. The final local matrix and bounded independent review are recorded below. OAuth configuration restoration is verified; the suspended cluster still needs the pending approved test window before execution qualification can continue.


## 11. Final local interpreter, dependency and wheel matrix

| Runtime | Dependencies | Full offline suite | Changed-function line + branch coverage | Full-package line + branch coverage | Coverage gate |
| --- | --- | --- | --- | --- | --- |
| Python 3.11.16 | Minimum | 1812 passed, 10 skipped, 1 xfailed | 82.4368% | 89.7648% | PASS |
| Python 3.11.16 | Current | 1812 passed, 10 skipped, 1 xfailed | 82.3023% | 89.7300% | PASS |
| Python 3.12.6 | Minimum | 1812 passed, 10 skipped, 1 xfailed | 82.3830% | 89.7509% | PASS |
| Python 3.12.6 | Current, root run | 1812 passed, 10 skipped, 1 xfailed | 82.2485% | 89.7161% | PASS |
| Python 3.13.5 | Current | 1812 passed, 10 skipped, 1 xfailed | 82.2485% | 89.7161% | PASS |

Every final case includes all 34 package files, 11,004 statements and 3,368 branches, including generated and legacy modules. All exited zero with the 80.01% threshold enforced. The four pre-existing excluded lines remain unchanged. Denominator differences from earlier reports come from actual scalar corrections and strict-decoder code, not omitted modules. JUnit counts the xfail among skipped testcases, so its skipped total is 11. No production source changed during the final runs.

Minimum dependencies include gRPC 1.65.1, protobuf 5.26.1, SQLAlchemy 2.0.0 and Thrift 0.20.0. Current dependencies include gRPC 1.83.1, protobuf 7.36.1, SQLAlchemy 2.0.52 and Thrift 0.24.0. Both use HTTPX 0.28.1. Base, async and async-sqlalchemy clean installation/import checks passed in all five environments, for 15 successful flavor checks, including pip check and absence of HTTPX/async import leakage in base installations.

Final wheel: `e6data_python_connector-2.4.0-py3-none-any.whl`. SHA-256: `7edee1a4e94e81c0e498a2d2a84355c34057baf5ba4de7bb8704bf0a017af472`. All 34 packaged Python source files matched the working source byte-for-byte. Aggregate package source SHA-256 remained `a9ce5da65a2cd9568d10473eb0ad3da0637c700519593f3c1402566595de4a95` before and after the independent matrix.

Detailed commands, constraints, structured results, logs and wheel evidence are indexed in local artifact `task11-matrix-report.md`. The final independent full-matrix logs had no resource-tracker KeyError, never-awaited coroutine or RuntimeWarning matches. Earlier teardown warnings remain historical observations, not a proven corrected defect.

## 12. Coverage methodology and reproduction

The full-package percentage combines executed statements and branch outcomes.
Python 3.12-current separately covers 91.0851% of statements and 85.2435% of
branches. Subprocess instrumentation includes supported native and Python protobuf
runtimes in the same report; no generated-code exclusions were added.

Changed functionality is measured against `48d324ad3d36387caa534d42fa8f579317e9faa6`.
Every new module is included in full. Any existing function touched by additions,
replacements or deletion boundaries is included in full, together with its branch
outcomes. Current-source decorators are included. This scope contains 2,742
statements and 976 branches; the root run covers 2,315 and 743 respectively,
giving 82.2485%. Changed executable lines alone are 84.3296%. These are measured
local execution metrics, not evidence of every downstream service behavior.

Run the complete collection from this worktree with the pinned test environment:

```sh
.venv312/bin/python -m pytest --cov=e6data_python_connector --cov-branch --cov-report=json --cov-report=term-missing --cov-fail-under=80.01
```

The reproducible changed-function audit and per-environment JSON measurements are
stored with the evidence in `.superpowers/sdd/2026-09-10-python-connector-oauth-async-implementation/`.
The baseline 19.15% and intermediate failed gates remain in historical reports;
the final runs above supersede those coverage statuses.

## 13. Restored-stack end-to-end qualification, September 11 IST

The user requested the following exact builds. The xDS, console and Planner tags already matched; the operator was restored from `gh-pr-1.0.3089-b4996fd` to the requested build. Ready pods and immutable image IDs were independently observed.

| Component | Requested and observed tag | Runtime image digest |
| --- | --- | --- |
| xDS | `gh-pr-1.0.661-84b1929` | `sha256:517dc66f4cc67d33de2fc68ea4c244489140476312f8468fa80cfac224d2ad1c` |
| Operator | `gh-pr-1.0.3082-84b1929` | `sha256:b43ae3acb35833ace436a915128aa12341a3694fcc2b0fc1698ea6bfecdcf8b7` |
| Console | `1.0.6565-84b1929` | `sha256:b776c519c99152a9c6586d9dd60272592702ee4049dd2d3e80011bd4cb069d67` |
| Planner | `gh-pr-2.0.4608-86af7cf` | `sha256:a6ea22e8d99bcb6cd0f1af414ceb6de7c39f656960353c66b2e93fac972a88c0` |

Target: AWS account `908027423391`, EKS `1bbf9228c0-us-east-1-eks`, namespace `ggr-ui-vishal1-cd46e4b9`, QueryService `atm1`, UID `d6dd7270-342f-4ce7-abae-b3ac71896a13`. The initial suspended-to-ready probe on operator `b4996fd` resumed compute but then received `UNAUTHENTICATED: OAuth authentication denied`. Planner startup showed `OAUTH_ENABLED=false`. That initial attempt is not a successful end-to-end resume result.

After the explicit build-restoration instruction, the missing `queryEngineEnabled` boolean CRD property was restored from the exact `84b1929` schema using UID/resourceVersion guards, then enabled only in this workspace's NamespaceConfig. Read-back showed generation/observedGeneration 19, Ready. xDS generation/observedGeneration 10 was ready with `QUERY_ENGINE_OAUTH_ENABLED=true`. Planner startup at `18:42:56Z` showed `OAUTH_ENABLED=true`; its authentication manager subsequently logged that trusted Envoy OAuth handling was enabled. A temporary Planner-only override was removed after restoring operator management.

The initial window was closed before its deadline: at `18:39:01Z`, the QueryService was Suspended, all compute Deployments had zero replicas, and no compute pods remained. A second window began at `18:42:50Z`. The later user-requested table benchmark extended its final restoration deadline to `19:07:50Z`.

### Live results

| Scope | Result | Evidence |
| --- | --- | --- |
| Authenticated auto-resume and query | 1 passed, 33.65 s | Independently observed Suspended -> Resuming -> Running; resume started `18:42:54Z`, readiness and operator Envoy ACK at `18:43:19-20Z`, ready Planner/Queue endpoints, successful SELECT result. |
| Final complete ready-state suite | 17 passed, 2 failed, 1 skipped; 76.46 s | The skip is the separately executed resume test. Both failures are catalog-less v1 using absent server default `demohivecatalog`. No failure was converted to skip/xfail. |
| Configured-catalog positive matrix | 16 passed, 74.88 s | Sync/async queries, parameters, executemany, mixed/batch/buffer/iterator/empty fetch, description/rowcount/status/explain, discovery, dry-run, reopen, concurrent routes, pool leases, SQLAlchemy and issuer renewal. |
| Missing-bearer read-only discovery | 1 passed, 1.26 s | Real TLS RPC rejected with exact `INTERNAL: Access denied`, matching this receiver's legacy session-denial path. This does not identify an edge rejection. |
| User-approved table preflight | 1 passed, 10.81 s | Four actual `date_dim` columns verified; ordered query returned 1,000 rows. This explicit benchmark preflight is outside the ordinary 20-case integration collection. |

The final ready-state cases plus the independently successful resume case establish **18 distinct passing live integration cases and two environmental failures**. Token renewal during an open query was induced by invalidating the local cache and reacquiring from the real issuer; it is not natural token expiry, revocation or multi-batch expiry proof. Proxy-dropped responses, real in-flight cancellation, natural expiry and legacy credential parity remain unqualified.

### Defects found and fixed through live testing

1. SQLAlchemy 2.0.52 awaits `_async_soft_close` before returning buffered results. The adapter lacked the hook. A failing real-adapter regression was added first; the minimal hook preserves buffered rows because native cleanup already completed. The full live SQLAlchemy case then passed in 14.27 s.
2. Both sync and async `dry_run` ignored the configured catalog and always used v1. Failing native-channel wire tests proved the request selection. Both now use the existing `dryRunV2` when a catalog is configured, preserving v1 otherwise. Live configured-catalog dry-run passes for both APIs.
3. The pool integration test could wait forever for worker admission after a worker failed. Structured task ownership and bounded work/cleanup now propagate that failure promptly. This was a test-harness fix.
4. The new empty-result test used SQL without a required FROM clause. The test now uses a derived constant table; real empty-result fetching passes.

Independent review of the production delta found no blocker and independently passed 12 focused checks across SQLAlchemy 2.0.0 and 2.0.52. The catalog-less v1 protocol has no catalog field; the deployed server unconditionally substitutes its default. No server catalog was invented or changed to hide those failures.

### Final frozen local/package verification

All five Python/dependency configurations passed **1,817 tests, 20 opt-in live skips and one existing xfail each**. Full line-and-branch coverage ranges from **89.7400% to 89.7887%**; entire touched-function coverage ranges from **82.3073% to 82.4946%**. Every case passes the strict 80.01% gate. All 15 clean package flavor checks pass and all 34 packaged Python files match the final source.

Final aggregate source SHA-256: `d7fa32d981aeb91a77ea34245c4da0acd4574dba530aa5048f01c0c587e448b2`.
Final wheel SHA-256: `ca7c21ddfaa6e2aca84fd602756c36ff7a9ec019489d529611d1b268260bcfab`.

Evidence is in the implementation evidence directory: `e2e-restored-build-verification.json`, `e2e-restored-stack-transition.json`, `e2e-restored-stack-ready.json`, `e2e-restored-stack-operator-resume.json`, `e2e-restored-stack-planner-auth.log`, `e2e-final-complete-suite.log`, `e2e-final-configured-catalog.log`, `e2e-auth-boundary-final.log` and the `e2e-final-*` coverage/package matrix. The updated local artifact `task11-matrix-report.md` indexes the reproducible commands and final artifacts. Earlier sections retain historical, superseded snapshots.

### Benchmark and final restoration

The user-approved 1,000-row `date_dim` benchmark completed all 175 queries, including 144 measured queries, in 225.50 seconds. Four async tasks delivered 3.06x sequential sync throughput, and 10.6% lower aggregate throughput than four sync threads in this run. Trial variation prevents a consistent async-versus-threads ranking. The complete timing boundary, per-trial results, reproduction command and limitations are in [the comparison report](SYNC_ASYNC_BENCHMARK.md).

At `19:04:40Z`, independent read-back verified `atm1` Suspended, all compute Deployment replica counts zero, and no compute pods. The final ledger additionally checks all four original QueryService replica fields, requested backend images and retained managed OAuth configuration. Restoration completed before the extended `19:07:50Z` deadline. The requested builds and OAuth configuration remain in place; the cluster's original suspended state was restored. Scoped temporary cloud credentials were cleared after final verification. See local artifact `e2e-final-runtime-ledger.json`.

## 14. Shared credentials and branch-push validation

The shared credential registry matches token endpoint, client ID, secret, scope, authentication method and provider timeout/renewal policy. It stores weak references under opaque keyed digests. Only token/refresh state is shared; transports, channels, query routes and event-loop tasks keep their original owners. Closing one async provider or pool preserves peers' credentials and pending acquisition. Explicit invalidation changes the matching shared generation. Inherited providers reject use after a fork.

The addition is implemented in `oauth_cache.py`, `oauth.py` and `async_oauth.py`, with separate shared-state unit suites. Tests cover distinct settings, simultaneous callers, waiter cancellation, close, generation races, cached-state lifetime, fork rejection, saturated sync capacity and owner-loop shutdown. Sync overload intentionally rejects a new distinct exchange when all four exchange slots are occupied; cache hits and matching exchange joins remain usable.

### Failure found and corrected before publication

The first complete validation run reported three failures: an admission-deadline test and both Basic/Post real HTTPS transport tests asserted immediate task termination after caller timeout. Caller timeout and actual exchange termination are separate events in the shared lifecycle, so the assertions now wait within a bound and verify no stranded flight or waiters. Independent review additionally reproduced a real defect: an immediate async retry could inherit an already expired retiring exchange deadline and fail without starting another exchange. Retirement now uses the new caller's deadline; an active acquisition still uses its fixed phase deadline. Replacement starts only after the earlier exchange terminates. The strengthened actual-socket regressions failed before the fix and pass afterward.

Independent review passed 82 focused tests after the fix, verified separate exchange tasks for immediate retries with both authentication methods, and checked owner-loop shutdown with an uncancelled foreign waiter. No confirmed code blocker remained in that bounded review. This permits the requested branch push; it is not production rollout qualification.

The Python 3.13 matrix also exposed two tests that incorrectly assumed an empty cache while reusing the same identity as earlier tests. A function-scoped provider factory now gives each test a distinct identity while preserving sharing among providers in that test. The registry is not reset or weakened to make those tests pass. This is test isolation, with no production-source change.

A later full run exceeded a 30-millisecond success deadline in the close-versus-unrelated-caller-work test. That test now synchronizes registration and cancellation with events and allows a one-second close deadline. It still proves close completes while the caller remains blocked on a separate event, and that no refresh flight remains. The change removes an incidental timing assumption rather than changing the connector's deadlines.

### Real issuer sharing

On the final source, `test/integration/test_shared_token_issuance.py` passed all three cases in 5.28 seconds:

| Scenario | Actual issuer exchanges | Result |
| --- | ---: | --- |
| Two sync pools and four worker threads | 1 | Shared bearer; closing one pool preserved the other |
| Two async pools and four tasks | 1 | Shared bearer; closing one pool preserved the other |
| Sync provider plus two separate async event-loop threads | 1 | Shared bearer across all three providers |

The tests count actual provider transport entries without substituting issuer responses, and compare bearer hashes without printing credentials. Reproduce against an authorized issuer using the integration configuration described in `ASYNC_API.md`:

```sh
python -m pytest test/integration/test_shared_token_issuance.py \
  --integration-config /absolute/path/to/operator-config.json -q -s
python -m pytest --cov=e6data_python_connector --cov-branch \
  --cov-report=term-missing --cov-fail-under=80.01
```

### Final local and package checks

| Runtime and dependencies | Complete suite | Full package line + branch | Whole changed-function line + branch |
| --- | --- | ---: | ---: |
| Python 3.11, minimum | 1,844 passed, 23 skipped, 1 xfailed | 89.9720% | 83.7024% |
| Python 3.11, current | 1,844 passed, 23 skipped, 1 xfailed | 89.9380% | 83.5780% |
| Python 3.12, minimum | 1,844 passed, 23 skipped, 1 xfailed | 89.9584% | 83.6526% |
| Python 3.12, current | 1,844 passed, 23 skipped, 1 xfailed | 89.9243% | 83.5282% |
| Python 3.13, current | 1,844 passed, 23 skipped, 1 xfailed | 89.9243% | 83.5282% |

Python 3.12-current and 3.13-current complete suites were rerun after the final event-synchronization test correction. For the other three environments, their successful complete suites were retained and the entire affected seven-test module was rerun after that test-only change. Production source remained identical across these runs. The 23 opt-in live skips and existing xfail are not counted as passes.

Coverage includes all 35 package files, 11,247 statements and 3,422 branches, with the four pre-existing excluded lines unchanged. The whole-function audit includes entire new modules and every touched existing function against base `48d324ad3d36387caa534d42fa8f579317e9faa6`. Both gates remain strictly above 80%.

All 15 clean installation/import checks passed: base, async and async-sqlalchemy in each of the five environments. All 35 packaged Python source files match the frozen implementation. Wheel SHA-256: `847a3468e8690b28ab94f8bd758138a3dd1537668360b94bba61c1507a236ea9`. The final test-only corrections did not change packaged connector source, so the passing wheel checks were retained.

The staged files passed whitespace validation and checks for the known authorized connection credentials and common secret markers; neither credential script was staged. Generated protocol files remain unchanged. Detailed local evidence uses the `push-isolated-final-*`, `push-deadline-final-*`, `push-final-*` and `push-staged-safety.json` artifacts.

### Qualification limits

The real issuer preflight declared a 900-second token lifetime. Natural expiration, receiver rejection of that old bearer, and continuation of the same query handle/channel after that rejection have not been demonstrated. Existing live continuation tests invalidate the cache and acquire real credentials; they must not be described as natural-expiry tests. Remaining live fault/cancellation and legacy qualification gaps from section 13 also remain open. The branch publication does not merge, release or deploy the connector.

Final aggregate package source SHA-256: `582c0b0955d60bb2871e4dddb82f09202f048b004f7cfdc9b7fa877680c44f5e`.
