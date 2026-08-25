# Handoff — Session 13 (2026-08-25)

Status: session complete. Read `AGENTS.md` → `CLAUDE.md` → project memory →
`ragweld-recovery-foundation-2026-08-19.md` before acting; this handoff and
`session13-pr-loop-and-registry-pollution-2026-08-25.md` (the execution record
with evidence) are required context. The session-12 handoff
(`handoff-2026-08-24-session12.md`) stays as history.

## 1. Scope / status

1. **PR #85 loop** — the session-12 branch was published, reviewed by Codex,
   merged (`d64d063`), and local `main` fast-forwarded. `gh pr merge --auto`
   merged immediately on this unprotected repo (deviation recorded; never pass
   `--auto` here). CI is still billing-locked; local gates are authoritative.
2. **Codex review of #85 acted on** — both P2s fixed with tests: stale
   docs-generator inputs (`bootstrap_docs.py`, plus a second stale glossary
   input the new invariant test caught) and `LineageMeta` alias-state scoping
   (request token, clear-on-failure, scope-change reset, active-corpus
   fallback) with a no-interception Playwright spec on the Benchmark tab.
3. **Registry/lineage pollution root cause** — three seams closed: corpus
   deletion removes corpus-scoped lineage (`delete_repo_lineage`), the synthetic
   run store honors `RAGWELD_SYNTHETIC_RUNS_ROOT` (pytest isolated via
   conftest), and the exhaustive suite provisions/deletes its own corpus.
4. **Exhaustive-suite modernization** (defect-6 residual) — isolated indexed
   corpus, evidence-graded Aurora questions, wall-clock budget, global-config
   isolation proof, host-side action blocklist, honest failure.

Nothing is half-landed. The work is committed locally on `main` as the
session-13 commit (SHA stamped in §2 by the follow-up docs commit);
**operator pushes; never push unprompted** (this session pushed only inside
the explicitly requested PR loop). A `codex exec` adversarial pass refuted
the first cut (4 P1 / 9 P2); 12 findings were acted on before the commit and
the 13th (deletion-saga tombstone) is logged as tech debt — see the session
record §7.

## 2. Working tree / branch

- `main` ahead of `origin/main` by this session's post-merge commits; see
  `git log origin/main..main`. Session-13 code+docs commit: SESSION13_COMMIT_SHA.
- Uncommitted, deliberately: `AGENTS.md` + `CLAUDE.md` GitNexus tooling blocks
  and untracked `.claude/skills/` (operator-local). The `AGENTS.md` handoff
  pointer was committed with the partial-staging trick
  (`git show HEAD:AGENTS.md` → edit → `git hash-object -w` →
  `git update-index --cacheinfo`).
- Orphan residue for the operator to remove (assistant's delete guard blocks
  recursive removal): the 95 paths listed in the session record §3 — every
  `data/lineage/{aliases,bundles}/<id>` and `data/lineage/locks/<id>.lock`
  whose `<id>` is not in `GET /api/corpora`, plus `data/synthetic_runs/pytest_*`,
  plus two per-run directories left by externally killed Playwright runs under
  `output/playwright/exhaustive/corpora/`. All are gitignored data. One-liner from the repo root:
  `python3 -c "import json,urllib.request;from pathlib import Path;live={r['corpus_id'] for r in json.load(urllib.request.urlopen('http://127.0.0.1:58012/api/corpora'))};print('\n'.join(str(p) for k in ('aliases','bundles') for p in Path('data/lineage',k).iterdir() if p.is_dir() and p.name not in live))"`
  to list, then remove what it prints (plus the matching `locks/*.lock` and
  `data/synthetic_runs/pytest_*`).

## 3. Running processes (no tmux)

- **Backend**: host uvicorn on 127.0.0.1:58012, relaunched this session on the
  new code with the previous process's exact environment (captured from the
  running pid, start.sh-faithful); pid file `.ragweld-runtime/backend.pid`
  (`pid|port`), log `.ragweld-runtime/backend.log`. **Next boot: prefer
  `./start.sh` so the canonical launcher owns it again** (it is a supervising
  foreground launcher, which is why the relaunch was manual).
- **Frontend**: Vite on 127.0.0.1:55173 (`/web/` base), untouched.
- **Local model**: host `vllm-metal` on 58080, untouched (operator-present
  rule; the suite never drives it — probes use `openai.gpt-5.6-luna`).
- **Compose (`ragweld`)**: all services up/healthy; nothing restarted.
- Live registry at handoff: exactly `aurora_acceptance`, `epstein-files-1`,
  `recall_default`.

## 4. Verification state (final tree)

Final tree: repo validators green (docs ownership, banned patterns, type
sync, LiteLLM lockstep 404 aliases, config reality 451 keys, capability
catalog 445 rows); `npm --prefix web run lint` + `build` green; the exhaustive
test directory type-checks under `tsc --strict`; `uv run pytest -q` →
**1158 passed / 79 skipped**; `requires_*` lineage + synthetic + containment
suites against the live compose services → **41 passed** with no residue;
Playwright (no interception): `lineage_alias_meta` 1/1, `chat_reliability`
3/3 (mining now asserts `triplets_mined >= 1`), `coverage` preflight 30/30
surfaces, `coverage` smoke (3-minute budget) → red by design on ONE real
finding (dead `/api/webhooks/alertmanager/status`, acceptance residual 4)
with 3/3 grounded provider probes and zero global-config drift. Details and
the codex review outcome: session record §5–§7.

Not run: `playwright.config.ts --project web` (structurally a no-op, see
session 12), the B8 training drive (operator-present only).

## 5. Next steps (ordered)

1. **Operator**: push `main`; remove the orphan residue (§2); decide whether
   to keep the isolated corpus prefix `ragweld-exhaustive-*` or move it to a
   dedicated test namespace in the registry.
2. **Full-budget exhaustive run** (30 min default, or longer with
   `EXHAUSTIVE_BUDGET_MS`), read `output/playwright/exhaustive/summary.json`
   and `outcomes.ndjson`: every `failed` row is a real finding (post-change
   persistence, propagation, ungrounded answers after retrieval mutations,
   global-config drift). The bounded 3-minute smoke runs this session are the
   loop proof, not the coverage claim.
3. **B8 training drive** — operator-present session only.
4. **A5 deferred product decisions** (unchanged from session 12; acceptance
   matrix residuals 4–5).
5. **GitNexus MCP reader** still storage v40 vs index v42 (CLI works:
   `node .gitnexus/run.cjs impact <symbol> --repo ragweld`).

## 6. Needs tightening (carried + new)

- Carried from session 12 §6 unchanged: Ragas judge retries, dashboard
  `vector(0)`/template boxes, benchmark model filter box, cosmetic nits,
  `ENRICH_DISABLED` flip confirmation.
- New (product): the Dashboard / Monitoring dock still calls the never-built
  `GET /api/webhooks/alertmanager/status` (404) — the exhaustive smoke loop
  fails on it by design; it is acceptance residual 4 (build it or remove the
  control).
- New: `GET /api/index/<id>/stats` answers 404 for an existing-but-unindexed
  corpus (the shell polls it; strict no-4xx specs must index first). Task 5's
  rule reserves 404 for "corpus does not exist" — consider an empty-stats 200.
- New: `pickProviderCandidate` fallback still takes the first catalog alias
  when the preferred one is not advertised; the catalog is alphabetical and
  carries retired upstreams (`openai.gpt-3.5-turbo` → gateway 400).
- New: `chat.litellm.default_model` is corpus-scoped but the Chat UI picker
  does not preselect it; probes pin the model through the picker each time.

## 7. Risks / gotchas (new this session)

- Never point plain pytest at live services with only `POSTGRES_*` exported:
  creates succeed, teardown deletes 503 at Neo4j, corpora leak (14 in one
  minute). Use `scripts/test_integration.sh` or the whole `.env` service set.
- Playwright `beforeAll` request contexts cannot be reused in `afterAll`; pass
  the hook's own `request` to `dispose(request)` or the corpus leaks.
- The assistant's delete guard (dcg) blocks recursive removal and even
  heredocs that mention it; cleanup goes through the live API
  (`DELETE /api/corpora/<id>`, now lineage-aware) or the operator.
- Session-12 gotchas still apply: no navigation/HMR during an eval stream,
  start.sh-faithful env for manual relaunches, counters reset per restart.
