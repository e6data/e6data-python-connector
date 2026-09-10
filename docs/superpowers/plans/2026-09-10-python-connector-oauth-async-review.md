# Connector-only OAuth and async plan review

Date: 2026-09-10. Planning review only. No implementation, product tests or live-service validation were performed.

## Reviewed artifacts

- [Design and complete function map](../specs/2026-09-10-python-connector-oauth-async-design.md)
- [Implementation tasks](2026-09-10-python-connector-oauth-async-implementation.md)
- Connector baseline: `48d324ad3d36387caa534d42fa8f579317e9faa6`, candidate branch `mcp/oauth2-client-credentials`, PR 85 OPEN at review time.

Final reviewed SHA-256:

```text
Spec: cf1777ab27988653a9cd407df8525c687f920d86e012ca4b0af279681654bef2
Plan: d0614c0b6ae33f4fa638ed251df1fabc6304cadbaca3f4865b49a285747ff2c0
```

## Independent verdicts

The independent design-gate reviewer approved the revised design for implementation, with confidence 87/100 and no remaining Major findings in its bounded review. The independent security reviewer confirmed all three reported security design gaps resolved. Both verified the final digests and the final coverage requirement.

Production readiness remains not-ready: implementation, full tests, configured real-service qualification, package/dependency qualification and independent review of the resulting code are outstanding. Design approval does not authorize publication, deployment or Jira changes.

## Findings and resolution

| Reviewer | Original finding | Resolution in final plan |
| --- | --- | --- |
| Design, Major | A short first caller could impose its deadline on shared token/session/resume work and fail surviving callers. | Each shared phase owns an immutable deadline from its creation and configured phase cap, including admission. Caller deadlines only control individual waiting. Tasks 5/8 test short-first/long-second and reversed ordering for token, legacy session and resume work. |
| Design, Minor | Secure OAuth gRPC wording did not explicitly cover standalone cluster managers. | TLS validation applies to every async OAuth channel, including direct manager status/resume. Tasks 4/8 require rejection before dispatch. |
| Security, Medium | Four decode workers did not bound batches received while waiting for decoding. | Reserve a process-wide fetch/decode slot before batch RPC dispatch; retain it through actual decode termination. Enforce a proposed finite 64 MiB async message limit. Task 7 measures outstanding batches/bytes and cancellation/churn. Buffered and aggregate application memory are explicitly outside this bound. |
| Security, Medium | Task identity alone could let retained connection/cursor references act after lease return and reacquisition. | Every checkout has a fresh revision and wrapper; validate owner/active revision on each high-level operation and publication. Invalidate before cleanup. Task 9 tests stale calls and close after same-task reacquisition with zero RPC dispatch. |
| Security, Medium | Resume uncertainty could disappear with its final waiter and permit another mutation from a replacement flight. | Persist acknowledged/unknown pending state outside the flight for the owning pool/manager lifetime. Replacement flights inspect status without repeating unresolved resume; ready resolves it, suspended alone does not. Task 8 tests final-waiter cancellation followed immediately by a new waiter. No durable cross-process guarantee is claimed. |

The initial design review rejected the earlier draft for the shared-deadline ambiguity. These corrections were then independently rereviewed; the final approval applies only to the digests above. The final coverage-only revision strengthens acceptance to greater than 80% overall package and changed-functionality coverage, with baseline preservation and no omitted modules; both reviewers confirmed their verdicts unchanged.

## Validation completed during planning

- Source/API inventory grounded in the pinned connector candidate; no backend implementation is included.
- Documentation checks: balanced fenced blocks, all 11 Python examples parse, absolute local artifact links resolve and no em dash characters.
- No product test results or coverage percentages are claimed. Example tests and test commands are future implementation work.
- Tracked connector source remained unchanged; unrelated untracked AGENTS.md, t3.py and t4.py were preserved. New work consists of these planning documents.

## Implementation boundaries to retain

Native async operations use grpc.aio and HTTPX without blocking network wrappers. Pure local properties/helpers stay synchronous; unimplemented poll/log/suspend features remain explicitly unsupported. Sync compatibility, query uncertainty, cancellation, routing, lease ownership and bounded cleanup are acceptance contracts. SQLAlchemy's separate async adapter is part of completion, with one pooling owner per connection.

The connector can preserve its own token/result lifecycle and report actual server outcomes. It cannot establish backend expiry, revocation, authorization or durable deduplication from client behavior alone. Real integrations need an explicitly configured supported test stack and authorized fault/resume window; missing qualification is reported as incomplete, never as a pass.
