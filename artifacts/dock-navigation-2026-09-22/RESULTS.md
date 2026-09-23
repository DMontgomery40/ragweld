# Dock navigation continuation — 2026-09-22

GUI-177 is fixed and deployed to the live frontend. Navigating inside an iframe Dock now updates its title and saved target. Reload and Swap preserve the current route and query context; reporting navigation does not reload the iframe. Links across routes retain the embedded layout. Chooser replacement and Undo remain functional.

## Scope and stopping rule

Recovered the prior Codex GUI audit and Claude review history. Applied the convergence rules from `../ttt_ssm_eval/SHARED_SCRATCHPAD.md` (ASTRA-114 / FABLE-088): bounded scope, reachable failures, one initial review and one focused closure, no speculative third round. GitNexus upstream impact was LOW for the Dock components and navigation bridge; the shared App shell was checked explicitly.

Preserved the pre-existing Chat copy cleanup, test locator cleanup, instruction edits, and GUI audit. No backend source changes, commits, or pushes were made in this continuation.

## Peer review

- **GPT-6 Sol, xhigh subagent:** identified a real prompt link that dropped embed/dock flags. Reproduced it in the browser, fixed stable document embedding and flag restoration, and added the regression to the shared Dock suite. Focused closure: no findings.
- **Opus 5.5 via `claude -p`, `claude-opus-5-5`:** identified a conditional stale target reference that could suppress Undo after an external selection. Cleared that reference when navigating the iframe externally. This finding was source-traced; the populated runtime did not reproduce its exact pre-fix condition. Expanded the shared suite with the real Undo journey. Focused closure: both review findings closed, no material introduced regressions.

Both reviewers reviewed source. Runtime results below were independently executed by the primary agent on LXC100.

## Validation

| Check | Result |
| --- | --- |
| Original GUI-177 on the old live UI | Reproduced: Trace Viewer visible while Dock title remained Analysis |
| Expanded Dock suite on current source | 9 passed |
| Same suite against the production build based on the actual live revision | 9 passed |
| Frontend unit suite | 37 passed |
| Frontend lint and production build | Passed on current source and release fixture |
| Docs ownership, banned patterns, generated types, runtime capabilities catalog | Passed |
| Full Python suite | 3,156 passed, 936 skipped, 39 failed initially |
| Failed-only Python rerun with corrected PATH, an empty fixture `.env`, and isolated PostgreSQL | 27 passed; 12 still failed during corpus cleanup because isolated Qdrant was unavailable |
| Authenticated live browser | Passed title synchronization, reload, Swap, cross-route prompt link, preserved prompt query, and absence of a nested app shell |

The full Python suite is **not green**. The remaining 12 failures are at `tests/api/test_models_endpoint.py:599`, where cleanup expects corpus deletion to succeed but receives a Qdrant dependency-unavailable 503. No backend repair was folded into this frontend fix. Skipped service-dependent tests are not acceptance evidence.

The shared browser suite covers Dashboard and RAG native rendering, Eval and Infrastructure iframe rendering, chooser changes, in-frame subtab changes, saved state, reload, Swap, the prompt link across routes, Undo, and existing layout regressions. Tests use the real app/API without interception.

## Deployment and live proof

Published only the Dock frontend patch over live revision `46e84aa810a1a33894989b667d2596441507251a`, preserving its existing Chat copy cleanup. The newer local GraphRAG recovery changes were not included. Backend deployment marker remains that revision.

- Release fixture: LXC100 `/var/tmp/ragweld-dock-release-20260922`
- Live bundle: `/web/assets/index-Df5x7YK0.js`
- Bundle SHA-256: `f9be29183b836b61271f0456a434f964adff2abc7b9543f9f4039743bdd1a40d`
- Live `index.html` SHA-256: `b3beac5b7979c65a00243b970ffc28aeb08791e9eca21ce1eb6219ce1fecc1cf`
- Backup: LXC100 `/var/tmp/ragweld-dock-rollback-20260922/frontend-before.tgz`

Assets were copied first and `index.html` replaced atomically; older hashed assets were retained for already-open clients. No backend restart occurred. Rollback restores the backed-up frontend source and index/assets and removes the newly added `EmbeddedDockNavigation.tsx`.

The existing browser iframe initially reused the previous cached bundle even though the parent loaded the new one. Temporarily disabling cache for the verification tab refreshed both documents; normal caching was restored afterward. Existing cached clients may need a full cache-bypassing refresh. This deployment-cache behavior was recorded rather than expanding the patch into a separate caching project.

Authenticated live verification ended with Chat Settings displaying the selected direct prompt and the Dock displaying Eval Analysis — Trace Viewer. The main URL preserved `subtab=settings&prompt=system_prompt_direct` without embedded-shell flags. No prompt values were edited or saved.

## Evidence locations

On LXC100 under `/var/tmp/`:

- `ragweld-dock-final-browser-20260922.log`
- `ragweld-dock-release-browser-20260922.log`
- `ragweld-dock-unit-20260922.log`
- `ragweld-dock-pytest-20260922.log`
- `ragweld-dock-pytest-rerun-20260922.log`

The accepted Dock slice is closed. The earlier audit backlog and undeployed backend recovery remain separate work.
