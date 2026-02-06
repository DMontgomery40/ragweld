# TriBrid / Ragweld Handoff Matrix (Feb 6, 2026)

## Scope Completed
- Enforced `epstein-files-1` as user-facing corpus default across TriBrid + ragweld demo surfaces.
- Purged tracked legacy corpus references (`faxbot`) across all listed local branches and ragweld.
- Locked prompt defaults to the provided database-oriented prompt set across backend + demo/mocks.
- Rebranded learning reranker language to Qwen3 LoRA learning reranker; removed active Qwen3 cross-encoder framing assets.
- Preserved `recall_default` as internal/system behavior while keeping user defaults on `epstein-files-1`.

## Branch Change Matrix
| Repo / Worktree | Branch | Status | Key commits applied for this plan |
|---|---|---|---|
| `/Users/davidmontgomery/tribrid-rag-main` | `main` | ahead 6 | `6ae1225` purge legacy corpus refs, `8eb7431` learning-reranker rebrand, `c1a82d2` prompt lock + epstein paths, `6a56f5a` glossary terminology update, `6f4c011` remove tracked tmp legacy artifacts, `8cb4c2b` drop `CROSS-ENCODER-IMPLEMENTATION` + fix `CLAUDE.md` wording |
| `/Users/davidmontgomery/tribrid-rag-isolated` | `codex/learning-reranker-studio` | ahead 7 | `1fec6b5`, `e6aff37`, `8fd989d`, `b2bfd4a`, `1b852c6`, `e187ea2`, `347e99e` (local studio sizing/scroll cleanup + ledger finalize) |
| `/Users/davidmontgomery/tribrid-rag` | `claude/cleanup-SluCi` | ahead 8, behind 3 | `cfc148d`, `1763450`, `32520de`, `4b4d47f`, `26f8295`, `b62cd4e` |
| `/Users/davidmontgomery/tribrid-cleanup` | `cleanup` | ahead 8, behind 3 | `c530486`, `a671cc1`, `900a320`, `1a84f1d`, `4068e4a`, `0c0b992` |
| `/Users/davidmontgomery/tribrid-cleanup-purged` | `codex/cleanup-purged-history` | local | Already had no `CROSS-ENCODER-IMPLEMENTATION`; contains aligned corpus/prompt/rebrand chain through `97a6a4b` |
| `/Users/davidmontgomery/tribrid-ui-port` | `ui-port` | ahead 4 | Already had no `CROSS-ENCODER-IMPLEMENTATION`; contains aligned corpus/prompt/rebrand chain through `16a87e0` |
| `/Users/davidmontgomery/ragweld.com` | `main` | dirty (many pre-existing unrelated changes) | `a924ae0` clean scoped commit for blog-route + E2E assertion alignment |

## Ragweld Clean Commit (Scoped)
- Commit: `a924ae0`
- Message: `Align blog route and E2E prompt assertions with locked prompt defaults`
- Included only:
  - `src/pages/blog/posts/cross-encoder-paradigm-shift-qwen3-mlx.md` -> `src/pages/blog/posts/learning-reranker-qwen3-mlx.md` (rename)
  - `tests/e2e/blog.spec.ts`
  - `tests/e2e/api-override.spec.ts`
  - `tests/e2e/eval-prompts.spec.ts`
  - `tests/e2e/eval-prompts-live.spec.ts`

## Verification Matrix
| Target | Verification | Result |
|---|---|---|
| TriBrid `main` | `uv run scripts/generate_types.py` | pass |
| TriBrid `main` | `uv run scripts/validate_types.py` | pass |
| TriBrid `main` | `uv run scripts/check_banned.py` | pass |
| TriBrid `main` | `uv run pytest -q` | pass |
| TriBrid `main` | `npm --prefix web run lint` | pass |
| TriBrid `main` | `npm --prefix web run build` | pass |
| TriBrid `codex/learning-reranker-studio` | `uv run scripts/check_banned.py` | pass |
| TriBrid `codex/learning-reranker-studio` | `uv run scripts/validate_types.py` | pass |
| TriBrid `codex/learning-reranker-studio` | `uv run pytest -q` | pass |
| TriBrid `codex/learning-reranker-studio` | `npm --prefix web run lint` | pass |
| TriBrid `codex/learning-reranker-studio` | `npm --prefix web run build` | pass |
| TriBrid `codex/learning-reranker-studio` | `npx playwright test .tests/web/learning-reranker-studio.spec.ts --project web` | pass (6/6) |
| TriBrid all six branches | `uv run scripts/check_banned.py` + `uv run scripts/validate_types.py` | pass on all |
| ragweld | `npm run build:demo` | pass |
| ragweld | `npm run build` | pass |
| ragweld | `npm run test:e2e` | pass (9 passed, 1 skipped) |
| Cross-repo invariant | tracked grep for `faxbot` | 0 hits in all seven repos |
| Naming invariant | Qwen3 with cross/BERT association grep | clean in TriBrid and ragweld active paths; only old->new redirect path remains in `astro.config.mjs` |

## Additional Local Commit (isolated branch)
- Repo: `/Users/davidmontgomery/tribrid-rag-isolated`
- Commit: `347e99e`
- Message: `Finalize studio layout sizing and inspector scroll behavior`
- Files:
  - `TODO.md`
  - `web/src/components/RerankerTraining/NeuralVisualizerWebGL2.tsx`
  - `web/src/components/RerankerTraining/NeuralVisualizerWebGPU.tsx`
  - `web/src/components/RerankerTraining/TrainingStudio.tsx`
  - `web/src/styles/learning-studio.css`

## Notes
- `/Users/davidmontgomery/ragweld.com` remains intentionally dirty with many unrelated pre-existing edits; only `a924ae0` was committed for the scoped request.
- Live execution ledger remains in `/Users/davidmontgomery/tribrid-rag-isolated/TODO.md` through step `L061`.
