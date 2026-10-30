# Generation Luna Default and Persistence Implementation Plan

> **For agentic workers:** Use test-driven development with one coordinated implementation owner and a bounded independent review after the stable diff.

**Goal:** Make the production generation default `openai.gpt-6-luna` and let supported primary generation selections persist through Apply, readback and restart.

**Architecture:** Generation model selection becomes corpus owned, seeded from the global production template. The deployment renderer supplies Luna for the clean default while preserving existing operator aliases; enrichment, evaluation and chat defaults keep their existing owners. No repeated read-time Sol migration and no new provider route.

**Tech Stack:** Pydantic, Python/FastAPI/Postgres, React/Zustand, pytest and real Playwright interaction.

**Spec:** User delegation in this task and `../evidence/ragweld-model-persistence-handoff.md` in the task workspace.

## Global Constraints

- Verified alias: `openai.gpt-6-luna`; do not invent model identifiers.
- Source edits in isolated Mac clone; tests/builds exclusively in isolated LXC100 checkout.
- Live configuration/restart/deployment waits for browser reproduction and authenticated UI verification.
- Keep enrichment/evaluation/chat/vision defaults and explicit generation/transport overrides.
- No mocked API/database acceptance, paid generation, auth changes, or unrelated repository edits.

## Review Focus

- Explicit Sol selected after migration must survive subsequent reads and restart.
- Partial corpus config and reset must receive the production template default.
- Renderer rerender must not replace an existing operator model.
- Catalog refresh must retain Luna and still-used Sol routes.
- UI save rejection must remain visible and leave persisted settings unchanged.

## Task 1: Regression tests and generation ownership

Files: `tests/unit/test_generation_default.py`, `tests/api/test_generation_model_persistence.py`, `server/services/config_store.py`, `web/src/components/RAG/RetrievalSubtab.tsx`, `web/tests/e2e/gateway/production_generation_alias.spec.ts`.

- [ ] Add tests that fail on current production reconciliation, partial config/reset default adoption and disabled picker behavior.
- [ ] Run expected-red unit/API tests remotely with disposable stores; record exact assertions.
- [ ] Remove only the primary generation deployment lock/reconciliation; seed omitted values and corpus reset from production global, preserving present operator values.
- [ ] Replace mocked generation picker test with real interaction coverage for select, Apply response, readback and reload.
- [ ] Run green checks, typecheck and frontend build remotely.

## Task 2: Production default and catalog protection

Files: `deploy/proxmox/render_config.py`, `scripts/refresh_models_catalog.py`, renderer/catalog tests.

- [ ] Add failing default/preservation tests: clean default Luna; enrichment/eval remain Sol; explicit production/custom primary and transport aliases retained on rerender.
- [ ] Split the generation-only production alias and protect both Luna and Sol during catalog refresh.
- [ ] Run focused green tests, contract/docs checks and bounded semantic lint remotely.
- [ ] Obtain one bounded Opus 5.5 xhigh review of the stable diff, verify selected reviewer model and repair concrete findings.
- [ ] Run remote GitNexus detect_changes and commit isolated reviewed changes after appropriate checks.

## Task 3: Live acceptance and deployment (blocked on sign-in)

- [ ] Reproduce actual dropdown/HTTP override/Apply response/reload in the same authenticated user browser and record corpus scope.
- [ ] Confirm live symptom matches fix; preserve backup/rollback and check active jobs.
- [ ] Deploy only required source/frontend/API changes; perform one-time legacy deployment-default migration with explicit compare-and-set, preserving transport/custom aliases.
- [ ] Verify Luna default, primary and HTTP changes through Apply, reload, storage readback and required guarded restart without paid generation.

User explicitly authorized implementation before live sign-in in the latest delegation; no additional plan approval is required. Tasks 1–2 can proceed; Task 3 remains gated.

## Implemented and verified source slice (2026-10-01)

Source implementation changes only primary generation ownership/default/picker, missing default seeding, corpus Reset, and production catalog retention. Development schema defaults and chat/enrichment/evaluation defaults are preserved. Transport aliases remain stored settings; no new routing behavior is implied.

LXC100 isolated verification: 172 focused tests passed against disposable real databases; real Playwright selection/Apply/readback/reload passed; actual isolated API process restart retained global Luna and explicit primary Sol/HTTP Luna. Generated types and contract integrity passed. TypeScript typecheck and Vite production build passed. Browser test captures the Luna selectors after reload, requires explicit API target inside the test, and safely cleans its disposable resources. Expected red assertions were observed before implementation.

Independent reviewer: local Claude CLI response metadata verified `claude-opus-5-5`, xhigh, no tools. One full stable diff review and one focused follow-up completed. Follow-up found no source correctness blocker, and its module-scope E2E environment guard issue was corrected. Conditional global-fixture leakage was disproved by existing autouse snapshot/restore and store-reset fixture. JSON renderer coverage and true production fixture were added. No further review loop.

GitNexus impact attempts and detect_changes completed. ConfigStore.get has broad expected downstream reach; latest isolated index reported critical risk across 205 flows. This requires guarded rollout and the real config/API regression suite, which passed. Initial active index returned mismapped edges; direct source inspection and isolated index were used, with graph truncation caveats retained.

Hosted Jev semantic lint is blocked by automatic approval review because the requested upload of internal source to api.typesafe.ai needs explicit destination authorization. Approval was requested for four exact source/test files using the existing configured key. No hosted lint pass is claimed and no rejection bypass attempted.

Live acceptance remains pending user Authelia sign-in. No live config migration, service restart or deployment has occurred. The source commit alone does not fulfill the live fix. Before deployment, snapshot global/corpus config and current legacy values, prevent config writes during rollout, migrate only global primary Sol and recorded deployment-forced corpus Sol snapshots with compare-and-set, preserving custom aliases and every transport/other setting. Never remigrate an explicit Sol selected after rollout. The same signed-in user UI must verify primary/HTTP Apply, reload, readback and guarded restart persistence. Check active jobs and backup/rollback before any necessary ragweld restart; never restart unrelated services.
