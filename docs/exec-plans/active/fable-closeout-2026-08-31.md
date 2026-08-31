# Fable Closeout Review and Acceptance Ledger

Date: 2026-08-31

Status: active

## Objective

Review and repair the critical `60b23717..9efd4a0c` Ragweld change range, then deploy and visibly accept the result by 2026-08-31 12:00 America/Denver.

## Fixed acceptance rules

- Every repair is root-cause-backed, tested by bug family, implemented by Fable at high effort only when attributable, and independently reviewed by DeepSeek V4 Flash.
- Runtime/build/test work runs on LXC100; Mac remains source-only.
- Browser acceptance uses visible screenshots and real clicks, dropdowns, typing, scrolling, graph interaction, and companion UI navigation.
- Completion requires one clean `main` worktree on Mac and LXC100, exact origin/deployment-marker parity, no active index run, and no unreviewed product changes.

## Tranche 0 — Worktree Preservation and Cleanup

- Mac before: 22 worktrees, local `main` 302 commits behind, three generated/duplicate untracked paths.
- Mac after: one branch/worktree, clean, `main == origin/main == 9efd4a0c`.
- LXC before: 24 worktrees; 23 `/tmp/fable-*`, many dirty; two detached patch-equivalent histories.
- Preservation: `/srv/ragweld/cleanup-backups/tranche0-fable-worktrees-2026-08-31T0540Z` (root-only, SHA256 verified; per-worktree diffs/status/untracked archives; thin and self-contained bundles).
- LXC after: one branch/worktree, clean, `main == origin/main == deployment marker == 9efd4a0c`; service active; `/api/ready` true.
- DeepSeek V4 Flash verdict: PASS. Its soft thin-bundle prerequisite concern was closed by adding and verifying `fable-detached-self-contained.bundle`.
- Residual `/tmp/fable-base` and `/tmp/fable-studrev` were removed only after open-file checks and verified archives.

## GitNexus Baseline

- Initial index at `33a2170` was stale; incremental refresh exposed corrupt `file_fts` state.
- Disposable GitNexus index was cleaned and fully rebuilt at `9efd4a0c`.
- Current graph: 18,319 nodes, 38,931 edges, 734 clusters, 300 flows.
- `60b23717..9efd4a0c`: 411 files, 3,417 symbols, 221 affected processes, CRITICAL risk.

## Verification Matrix

- Static contract validators on LXC100: docs ownership PASS; generated boundary types PASS; LiteLLM catalog lockstep PASS (379 aliases); runtime capability catalog PASS (420 rows); contract bundle PASS.
- Initial banned-pattern gate: FAIL, seven forbidden monkeypatch uses across the chat usage and Proxmox deployment contract tests.
- Isolated chat failure root cause: the test inherited production `LITELLM_BASE_URL` and made a real charged web-search call instead of using its loopback gateway; product web grounding was not the cause.
- Tranche A focused verification after repair: four tests PASS as `ragweld`; three Proxmox filesystem tests PASS as root; banned-pattern gate PASS. The live checkout was restored clean after temporary patch application.
- Live readiness: `127.0.0.1:58012/api/ready` reports ready with Postgres, Neo4j, LiteLLM, and index manifests healthy. The earlier `58011` probe was an incorrect port, not a runtime outage.
- Initial full backend census: 1,877 passed, 12 failed, 33 skipped. The 12 failures were traced to inherited live deployment variables, a one-shot MCP lifespan collision, and missing Flyte launch-plan registration rather than twelve independent product defects.
- Repaired standard backend gate: 1,888 passed, 33 skipped, zero failures in 405.37s. The skip audit then proved 26 skips were dishonest on LXC100: the service probe accepted `POSTGRES_*` components while test bodies required a separately composed `POSTGRES_DSN`.
- Final live integration gate with `POSTGRES_DSN` deliberately unset and `RAGWELD_LIVE_GATEWAY=1`: 64/64 passed in 348.93s, including real Postgres, Qdrant, Neo4j, figure-description gateway, promoted-generation, and mounted MCP transport paths. The remaining optional MLX lane is unavailable on Linux and is not represented as passing.
- Final combined backend gate before the warning-only cleanup: 1,927 passed, one honest MLX-on-Linux skip, zero failures in 729.38s. The two avoidable semantic-cache serializer warnings were then removed by using the declared boolean type; both live semantic-cache API tests passed 2/2.
- Frontend type-check and production build PASS on LXC100. The first Playwright launch exposed a missing pinned Chromium binary and then a compositor crash; the deeper cause was a drifted `/tmp` (`ragweld:ragweld 0755` instead of the distro tmpfiles contract `root:root 1777`). The baseline was restored, APT signature refresh passed, and the headed/Xvfb exhaustive preflight passed in 37.6s.
- Final full exhaustive mutation/persistence/probe loop: PASS in 711.34s; 32/32 surfaces; 1,308 recorded outcomes (264 ok, 1,044 policy-visible skips, zero failures); no wall-clock budget exhaustion; no global-config drift; isolated corpus removed with zero `ragweld-exhaustive-*` registry residue.
- Final post-repair backend gate, with `/etc/ragweld/runtime.env` loaded, `POSTGRES_DSN` deliberately unset, and `RAGWELD_LIVE_GATEWAY=1`: 1,928 passed, one honest MLX-on-Linux skip, zero failures in 783.70s. This includes the new real Flyte cancellation-race regression.
- Final GitNexus compare against `main`: 88 changed files, 209 indexed symbols, 57 affected execution flows, CRITICAL aggregate scope. The scope warning is accepted only with the complete green gate and per-tranche reviews above.

## Tranche Reviews

### Tranche A1 — Zero-mock deployment and chat contracts

- Frozen files: `tests/api/test_chat_usage_propagation.py`, `tests/unit/test_proxmox_deployment_contract.py`.
- GitNexus impacts: LOW, exact, zero callers/processes/modules for the changed existing test helpers/functions.
- Fable high-reasoning session: `1105bd94-63e1-4b0f-b31d-9be693198dde`; initial repair cost $2.848314; DeepSeek-directed revision cost $2.726322.
- Fable repair: replaced fake `fchown` interception with real ownership outcome coverage, real `ENAMETOOLONG` staging failure, and a privileged child-process `EPERM` path that proves original-file and temp-cleanup behavior.
- Controller repair: made the loopback gateway temporarily own and restore `LITELLM_BASE_URL`; replaced fake cache hooks with real Prometheus counter invariants proving web-enabled chat performs no cache lookup or write.
- DeepSeek V4 Flash first verdict: FAIL (lost cache-bypass coverage, vacuous ownership fallback, missing real ownership-restore failure).
- All three findings resolved without mocks or skips. DeepSeek V4 Flash second verdict: PASS; only non-blocking duplication/target-environment notes remained.
- Focused LXC proof: 4/4 PASS as `ragweld`; 3/3 PASS as root; `scripts/check_banned.py` PASS; temporary patch reversed cleanly; live readiness remained true.
- Commit/deploy/browser evidence: pending the full gate and visible acceptance drive.

### Tranche A2 — MCP lifespan ownership

- Root cause: Fable-era tests entered `app.router.lifespan_context(app)` more than once in one pytest process even though MCP SDK 1.26's `StreamableHTTPSessionManager.run()` is one-shot.
- Fable high-reasoning repair removed the redundant config-redaction lifespan and consolidated the real DNS-rebinding/advertised-host proof into the one API MCP lifespan test.
- LXC proof: both test-file orders passed 16/16; no environment-dependent skip remained.
- DeepSeek V4 Flash verdict: PASS.

### Tranche A3 — Test/runtime environment isolation and Flyte registration

- Outage, model-discovery, Promptfoo, ConfigStore, bind-default, and runtime-config tests were inheriting healthy production services or deployment-only variables. Each now owns/restores its exact environment boundary; no mocks or interception were added.
- Focused LXC proof: 19/19 passed. DeepSeek initially returned a false FAIL that recommended forbidden mocks and misread the count; after an evidence-backed rebuttal it withdrew every finding and returned PASS.
- Flyte admin was reachable but the learning-agent launch plan was absent. Installed the checksum-verified official `flytectl` v0.8.18 under the `ragweld` account, registered/activated `ragweld/development` version `dc1be4440bfb`, and passed both real create/cancel/out-of-band-abort tests.
- DeepSeek operational review verdict: PASS.

### Tranche A4 — Promoted integration lane and typed MCP failures

- Root causes exposed by the skip audit: deleted `/api/mcp/rag_search` assertions, missing promoted graph/Qdrant generations that prevented dependency calls, and a service probe/body mismatch where components passed collection but `require_env("POSTGRES_DSN")` skipped the body.
- Fable high-reasoning session `b9c5fbdb-9707-4711-b155-243c2e998f2e` confirmed MCP SDK structured-error support and the generation diagnosis but was stopped after 625.9s / $9.499034 because it repeatedly re-read settled mechanics and made no edits.
- Repair: MCP search now returns a validated `CallToolResult` outcome with structured success or typed dependency/leg/contract error; `/api/mcp/probe` preserves 409/503 detail. Real probe tests run in one-lifespan child processes, so the shared suite never starts the one-shot manager twice. Fixtures promote the exact graph/Qdrant generation needed to reach the intended failure.
- Test harness repair: explicit `POSTGRES_DSN` wins; otherwise the same component variables accepted by the capability probe compose a URL-escaped DSN. Missing configuration retains the named skip. The corpus reaper reuses the same resolver.
- GitNexus: four original integration tests LOW/zero; `mcp_probe` LOW/zero; `register_mcp_tools` LOW; `require_env` HIGH because 27 test callers intentionally consume the corrected contract. The HIGH-risk production fusion classifier was not edited.
- LXC proof: ruff PASS; 12/12 service-gating unit/invariant tests PASS; eight formerly failing live cases PASS in 128.27s; complete integration directory 64/64 PASS in 348.93s with live gateway enabled.
- DeepSeek V4 Flash reviews: MCP/error tranche PASS; DSN/service-gating tranche PASS. Two earlier DSN review attempts produced no verdict because the reviewer gateway timed out; only the completed streamed PASS is counted.

### Tranche A5 — Malformed figure replies and lifecycle test identity

- The full suite exposed a stochastic vision-provider reply whose malformed JSON was copied verbatim into figure markdown. Fable high-reasoning session `528ea56f-8c29-4e40-aaab-a053e3daeb5f` repaired strict-parse failures with the already-locked `json-repair` parser, guarded repaired objects by schema keys, and made JSON-looking unrecoverable replies degrade to an empty annotation instead of leaking syntax.
- Figure proof: ruff PASS; 23/23 focused figure/serializer tests PASS; the real live PDF -> vision alias -> figure chunk test passed three consecutive calls (128.48s, 77.54s, 66.56s) and passed again inside the final full suite. DeepSeek V4 Flash verdict: PASS.
- The next full run exposed two Fable-written Proxmox lifecycle tests invoking service-owned secrets as root. Fable session `7d330ff3-e843-489b-a348-ea7b3c8b644b` first repaired the identity mismatch but introduced a shared-ancestor chmod loop. DeepSeek returned FAIL on that cleanup defect. The revision moved both tests into an isolated `tempfile.mkdtemp` root with guaranteed root-process teardown and a real uid/gid privilege drop; the shared HIGH-risk `_run_shell_script` helper was left untouched.
- Lifecycle proof: exact failures PASS 2/2; all 56 Proxmox contracts PASS; no `/tmp/ragweld-lifecycle-contract.*` residue; the decisive full-process ordering passed the same 56 tests. DeepSeek's later version-stale claims about Python `subprocess.Popen(user/group/extra_groups)` and MCP `CallToolResult.structuredContent` were disproved against the installed Python 3.12 and MCP SDK model signatures; it corrected both to PASS.
- System cleanup: LXC100 `/tmp` had drifted to `ragweld:ragweld 0755`; `/usr/lib/tmpfiles.d` declares `root:root 1777`. Restored the declared baseline and verified `apt-get update` signature refresh succeeds.

### Tranche A6 — Strict server typing and Flyte cancellation race

- The warning cleanup exposed 119 strict-mypy errors across 49 server files. Fable high-reasoning session `2a4f363b-7d7f-45da-95bc-1748764de491` reduced the set to 60 before its budget ended; continuation `e4de2a34-8d23-44c2-b890-3abe498c9475` completed the real narrowing/annotation work and verified a cold-cache zero.
- Final static proof on LXC100: `ruff check server` PASS; `mypy server` reports `Success: no issues found in 160 source files`. No blanket mypy disable, broad `Any` cast, or new suppression was accepted.
- The type pass found a real FastAPI contract bug: if an operator cancelled while flyteadmin was creating the execution, `start_train_run` terminated the created execution and returned `None`, producing response-model failure instead of the declared start result. The cleanup is now a typed helper returning `AgentTrainStartResponse(ok=False, run_id=...)`.
- TDD/live proof: the new test first failed at import, then created a real Flyte execution, invoked the cancellation-wins cleanup, asserted the typed response, and observed the execution reach an abort phase with the expected cause. Focused proof PASS 1/1.
- DeepSeek V4 Flash reviews: API/control-plane typing PASS; storage/lineage/training typing PASS; indexing/synthetic typing initially raised two concerns, then returned PASS after the installed Docling `AnyUrl` field type and empty-excerpt normalization were supplied; Flyte race regression PASS.

### Tranche A7 — Headed exhaustive UI repair and truthful crawler state

- The first complete run collapsed 58 action failures into four root-cause families. Route catalog and Eval analysis assertions were corrected; Advanced embedding settings became default-open; Chat received a real minimum usable card height; the per-run query-log directory is now created by the API identity instead of root Playwright.
- Trace screenshots showed the remaining Chat failures were not hidden DOM defects: `gotoSurface` auto-opened every `<details>`, including the Sources popover, and that visible overlay covered later citation, feedback, attachment and retrieval-toggle clicks. Persistent disclosures still open for discovery; the transient Sources popover now remains closed. A focused browser test went red before the fix and green after it.
- The index warning said the contract was locked, but advanced dense-contract inputs remained editable and failed only at Apply. Input truncation, text prefix/suffix, contextual mode, late-chunking bound and max tokens are now disabled while an indexed corpus is locked, and become editable with Force reindex/no existing index. The focused bug-family test went red on the enabled field, then passed across all six controls.
- Apply confirmation is exercised through the real in-app dialog: an unindexed isolated corpus stages an embedding suffix, clicks the index-impact confirmation, reloads, and observes the persisted value. Corpus deletion now allows the multi-store cleanup request 120 seconds while retaining 2xx/404 success and typed-503 retry semantics.
- A generic crawler click on a welcome prompt reused an unavailable optional `ragweld-local` session model. The paid/model action is now covered once in the dedicated Chat lane: pin `openai.gpt-5.6-luna`, select real corpus sources, click the visible welcome prompt, wait for terminal streaming, and reject structured errors. The generic crawler records those duplicate unpinned actions as policy skips.
- Focused headed proof: seven Chat/harness regressions PASS. DeepSeek V4 Flash initially requested the legitimately conditional Eval run-settings field; the revised smoke real-clicks Run Settings and asserts Final K when runs exist, otherwise asserts the typed empty state. Final frontend and cleanup reviews: PASS.

## Honest Residuals

Pending evidence. Do not convert external authentication, provider capacity, or optional upstream service limitations into source fixes without proof.
