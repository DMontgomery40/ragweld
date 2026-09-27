# Production readiness implementation and acceptance

> **For agentic workers:** Use superpowers:executing-plans for integration. Independent repairs have disjoint owners; all execution and tests run on LXC100.

**Goal:** Ship and verify the existing owners-only Ragweld deployment with grounded-answer regression evidence, bounded requests, truthful readiness/accounting, and demonstrated recovery and rollback.

**Architecture:** Preserve the current FastAPI, LiteLLM, Qdrant/Postgres/Neo4j and authenticated operator deployment. Repair the existing paths, keep one source checkout, and seal release artifacts with source/build/dependency identities. Recovery exercises use isolated containers and existing backups.

**Tech Stack:** Python/FastAPI/Pydantic, TypeScript, Compose, Promptfoo, GitNexus, LXC100.

**Spec:** The production blockers identified in this chat and accepted for implementation on 2026-09-26; the measurable acceptance conditions below are the execution scope.

## Global constraints

- Mac checkout is source-only; all runtime, build, test, index and acceptance work runs on LXC100.
- Preserve the current owners-only access boundary. Public tenant onboarding and GPU training are outside this release.
- No mocked tests, compatibility paths, silent provider fallbacks, or generated-doc edits.
- Run GitNexus impact before symbol edits and detect_changes before commits.
- Root owns schema generation, integration, release and live acceptance; agents own only assigned source files.
- Never restore into production stores. Never expose secrets in source, reports, or release metadata.

## Review focus

- A retrieved number must stay attached to its event, unit and qualifier; do not conflate warning-time fuel with touchdown fuel.
- A request waiting for capacity, retrying, or receiving a trickle response must respect its total deadline and release capacity on cancellation.
- Cancellation/validation/persistence failures must not leave in-flight metrics elevated or increment successful outcomes.
- A running HTTP process with an unavailable Qdrant store must remain live but report not ready.
- Release verification must reject tampered/incomplete artifacts; recovery must validate restored data independently of production.

## Tasks

- [x] **Readiness and telemetry:** repair `server/api/health.py` and `server/api/chat.py`; extend the registered readiness dependency literal; reproduce failure/cancellation accounting with real boundaries and focused tests.
- [x] **Request deadlines:** repair `server/system_one/client.py` and generation transport total deadlines using existing configured budgets; test saturation, retry, cancellation and trickle bodies with real HTTP servers.
- [ ] **Grounded answers:** improve the existing configurable RAG prompts without corpus-specific answer logic, preserve numerical/event distinctions, add the observed counterexample to the evaluation gate, and rerun current deployment answer and retrieval evaluations.
- [ ] **Release and recovery:** add tested release sealing/verification and an isolated restore drill; restore Postgres, Qdrant and Neo4j from the existing backup and record counts/checksums; exercise deployment and rollback with the sealed artifacts.
- [ ] **Integration:** run contract/schema checks, focused tests, repository tests, semantic lint, frontend type/build gates and an independent review. Resolve material failures before publication.
- [ ] **Publication and acceptance:** publish reviewed changes, reconcile CI/source/deployed identities, verify authenticated chat/citations/persistence and observability, run bounded concurrent domain queries, and record exact acceptance results.

## Evidence and decisions

- Baseline: local and LXC source fast-forwarded from `b9097178` to `ac428f5b`; the service was still running the earlier build at task start.
- Fresh GitNexus index built on LXC100 under `/srv/ragweld/gitnexus-prod-readiness` to avoid the old index's storage-version mismatch.
- Browser baseline: two answers completed in 28.9 s and 81.6 s. Second answer correctly reported about 50 s at touchdown but incorrectly described the low-level warning as 45 s; the retrieved text and original PDF page both state 116 s at that warning.
- Browser baseline passed authenticated chat, citation rendering, reload persistence and Grafana trace navigation. Langfuse SSO consent remains pending explicit user approval.
- Shared prompt classes: GitNexus reports CRITICAL impact, 136 upstream symbols / 105 direct dependents; edits are restricted to prompt defaults. Readiness literal has no resolved callers, so absence of graph edges is not treated as proof of isolation.
- Config-cache defect reproduced: global model updates remained invisible to already cached corpora. The repair reconciles deployment-owned fields after database awaits; six real PostgreSQL cases plus ten existing cases pass, including concurrent global saves and `persist=False` purity. Independent review passed.
- A review reproduced abandoned traces when a prepared stream closed before its first body event. Response-owned finalization closes all three early-disconnect boundaries exactly once. Independent review passed; 41 endpoint/usage cases and 13 lifecycle/metrics cases passed (two optional live-gateway cases skipped in the isolated run).
- Frontend gate: 79 tests passed, typecheck passed, staged production build passed. Full backend run: 4,192 passed, 141 capability-gated skips, 17 failures. Eleven failures came from macOS archive metadata, three from the test runner's missing `/usr/local/bin` PATH, one from a stale hardcoded catalog price, one from an inherited DSN in an intentionally unreachable-service subprocess, and one from the intentional timeout exception change. Metadata was removed and transfer flags corrected; focused repairs rechecked all failures, with 52 checks passing and two provider-gated skips, then all 58 pricing/service-harness checks passing after the final DSN repair.
- Full server mypy and schema/type/contract/config-reality/docs-ownership checks passed before the final retrieval repair. File-wide Jev marked three unchanged legacy mapping sections uncertain; the commit-scoped semantic gate must assess the actual introduced lines before publication.
- The 31-case GPT-6 Sol candidate run used a verified scoped model setting: 29 passed, median generation latency 3.8 seconds, maximum 12.8 seconds. One failure is missing table retrieval. The other preserved all fuel quantities and events but failed an unrequested timestamp requirement in the newly authored rubric; that requirement was corrected while preserving the original 30 cases and all numerical/event assertions.
- Isolated restore proof passed for all 14 backup checksums: PostgreSQL 32,633 rows, Qdrant 22,898 points, Neo4j 47,825 nodes / 113,466 relationships. Disposable resource cleanup verified. MLflow/Langfuse remain inventory/checksum-only in this bounded drill.
