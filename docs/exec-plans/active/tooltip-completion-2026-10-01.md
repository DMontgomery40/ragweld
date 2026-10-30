# Glossary completion — 2026-10-01

## Review status and ancestry

Review-only implementation on `feat/glossary-completion-20261001`. Started from `2448941b1cd87fbe0077a7ef587b8611503b36c1`; normally fast-forward merged the separately completed generation fix `49da64e300e53c9fc6aa7a6b246a8f3cdc64029a` after its ownership lock was lifted. Tooltip changes are measured against **49da64e3**. No push, production merge, deployment, restart, settings save or production configuration edit was performed for this task.

Coordinator routing: explicitly requested Astra medium; four workers explicitly spawned as `gpt-6.1-sol`, `low`: source researcher, two content partitions, one wiring partition. Existing workers were reused for bounded follow-up batches. Researcher alone approved new external references; schema and runtime consumers, not vendor docs, established local behavior/defaults.

## Coverage and preserved content

| Measure | Before | After |
|---|---:|---:|
| Glossary definitions | 467 | 721 |
| New definitions | — | 254 |
| Existing definitions corrected with source evidence | — | 64 |
| Existing records left byte-for-byte intact | — | 403 |
| Definitions removed | — | 0 |
| Component TooltipIcon templates | 313 | 484 |
| Bare component label templates | 134 | 6 |
| Config Explorer registered fields with explicit rich glossary mapping | 0 | 460 |
| Literal help keys without definitions | 3 initially found | 0 |

All existing key ordering and unchanged record bytes are preserved. Existing readable titles/categories are retained. Corrections remove misleading claims such as inactive settings supposedly affecting runtime, trace retention supposedly being a duration, generic gateway assumptions, and deterministic enrichment supposedly making paid model calls. Defaults are explicitly schema defaults rather than claims about deployed values. Unsupported/unrelated references were removed instead of attaching generic citations.

The sweep covered all 129 frontend TSX files (477 control templates; 125 component files contain 476). Six remaining bare label templates are accounted for: four repeated options with shared group help, one Admin checkbox label whose enclosing field header now has mapped help, and one mechanical typed-confirmation prompt with action-specific instructions. There are **zero known unhandled technical-setting help gaps in the audited scope**; this is a source inventory plus representative runtime proof, not a claim that every conditional route/control was individually clicked.

See [complete per-file audit](tooltip-wiring-source-audit-2026-10-01.md) and [primary source register](../../references/glossary-sources-2026-10-01.md). The register identifies exact key/path consumer evidence, reference claim boundaries and actual access date 2026-10-01, separately from publication dates. Flyte canonical project/domain/admin references and an unsupported TypeSafe rate-limit assertion were not fabricated; those application-specific explanations use local evidence and no unverified external links.

## Implementation

Added 170 static help instances across 32 components plus the central ConfigFieldEditor help template. The explicit `configGlossaryKeys.json` covers all 460 current descriptors; contract tests fail on newly unhandled or stale paths. This is UI mapping data, not a competing configuration schema. Four Explorer filters and the Raw section selector gained visible help/accessibility names; their filtering logic is unchanged.

The shared TooltipIcon now opens on the first click/tap, supports keyboard navigation into reference links, returns focus on Escape, closes outside, keeps hover links reachable, and fits narrow viewports. Help clicks inside labels no longer toggle their checkboxes. The existing glossary renderer and source/mirror architecture remain in use.

Exactly seven help nodes were added to RetrievalSubtab after incorporating 49da64e3. Removing only those seven nodes reproduces the 49da64e3 source byte-for-byte. Model selection, generation policy, config persistence and all setter logic remain unchanged.

## Validation environment and evidence

All runtime, test, build and index commands ran on LXC100 in `/tmp/ragweld-tooltip-validation-20261001`, with an isolated Vite source server on port 55179. The real read-only API was used without fabricated responses. Production's authenticated Brave Work tab was observed safely through a separate tab to establish baseline UI access; changed-code acceptance is the isolated UI, not deployed production acceptance.

Local review evidence is in `<local-evidence-directory>/` outside the Git checkout:

- `tooltip-grafana-settings.png`, `tooltip-synthetic-settings.png`, `tooltip-admin-registry.png`, `tooltip-retrieval-generation.png`
- `tooltip-keyboard-links.png`, `tooltip-mobile.png`
- `glossary-preservation.json`, `generation-preservation.txt`
- `browser-final.log`, `focused-pytest-final.log`, `build-final.log`, `gitnexus-index-final.log`, `gitnexus-detect-changes.log`

Successful checks:

- `python3 scripts/validate_glossary.py`: 721 terms, all literal help keys resolved.
- `.venv/bin/python -m pytest -q --no-cov tests/unit/test_glossary_contract.py tests/unit/test_generation_default.py`: 24 passed. Glossary uniqueness/required data/HTTPS reference shape/mirror parity, actual 460-field schema mapping and generation defaults.
- `npm --prefix web run typecheck` and `npm --prefix web run build`: passed. Existing large-chunk and older Browserslist-data warnings remain.
- `npx playwright test -c tests/browser/tooltip.config.ts`: 6 passed. Actual hover into reference, keyboard Tab/Enter opening a reference in a new tab, Escape/focus return, outside dismissal, checkbox isolation, mobile touch toggle, 320×280 long-content overflow; actual Grafana/Synthetic/Admin/Retrieval help; all 460 rendered Admin mappings; generation selection unchanged; zero config writes.
- Documentation ownership, generated types, contract integrity (0 errors), runtime capability catalog (390 rows): passed.
- `git diff --check`: passed.

GitNexus pre-edit impacts were run by each owner. The initial advertised index missed several symbols: these were **UNKNOWN**, never interpreted as zero risk. The isolated index was rebuilt. Shared TooltipIcon and GrafanaDashboard produced CRITICAL warnings (reported before their subsequent edits); final retrieval impact was LOW. Final `detect_changes --scope all`: 44 staged changed files, 67 symbols, 82 flows, **critical** aggregate risk, consistent with broad shared UI help coverage. Output is truncated by the tool. Large glossary JSON files are excluded by the indexer's size limit and are separately contract-tested. Index-generated instruction/skill drift was restored, not committed.

Full `.venv/bin/python -m pytest -q --no-cov`: **3,446 passed, 984 skipped, 42 failed** in 454.61 seconds. Replayed exactly those 42 failed test IDs in a separate unchanged `49da64e3` checkout: **the same 42 failed** (11.30 seconds). The failures are missing isolated `.env`/database credentials and consequent API failures, not new tooltip regressions. Production secrets were not copied to make this broad suite green. See `full-pytest.log`, `failed-test-ids.txt`, and `baseline-failed-tests.log`. The full suite is not reported as passing.

## Remaining gates

Mandatory hosted Jev lint was **not executed**: this task has no approval to disclose its private source files to `api.typesafe.ai`; another task's four-file request does not authorize this scope. Local `--dry-run` additionally exposes an existing limit: `IndexingSubtab.tsx` needs 203,118 characters for file-scoped rules, exceeding the configured 120,000-character request limit. Nothing was sent. The browser test directory and public mirror are outside Jev's configured source scope. Do not claim the mandatory lint gate passed.

Production visual acceptance of changed code remains pending a separately authorized deployment. No implementation gap is being hidden by that gate.

## Screenshot fixture correction

The first mobile fixture screenshot lacked the app's `tokens.css`, so `--card-bg` was unresolved and underlying fixture text showed through the bubble. The application already imports these tokens. The fixture now imports the app base styles in the same order, selects the light theme, and asserts both an opaque computed background and the expected foreground color before capturing the narrow viewport. Re-ran only `tooltip-accessibility.spec.ts`: **3 passed** in 2.6 seconds, including keyboard reference opening, overflow and touch. Replaced `tooltip-mobile.png` and `tooltip-keyboard-links.png`; see `browser-theme-fixture.log`. No application behavior changed in this follow-up.
