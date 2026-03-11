# Core Beliefs (Agent-First)

These are the taste and architecture invariants we want to compound over time. When a belief becomes important and repeatedly violated, promote it into mechanical enforcement (scripts/hooks/tests/lints).

- **Pydantic is the law**: define config and API shapes in `/Users/davidmontgomery/ragweld/server/models/tribrid_config_model.py` first.
- **No adapters**: if the frontend expects a different shape, change the Pydantic model instead of mapping payloads.
- **Generated types only**: TypeScript API types come from `/Users/davidmontgomery/ragweld/web/src/types/generated.ts`.
- **Boundaries over cleverness**: keep modules small and dependency directions obvious.
- **Progressive disclosure**: short entrypoints link to deeper pages; avoid monolithic manuals.
- **Mechanical enforcement beats reminders**: encode invariants in code so agents cannot ignore them.
- **Prefer boring, legible dependencies**: choose tools that are easy to reason about and easy to validate in-repo.
- **Minimize hidden state**: explicit inputs/outputs; avoid implicit globals and magic environment-driven behaviour.
- **Config controls behaviour**: tunables belong in Pydantic config, not environment variables or hardcoded constants.
- **Make failure modes inspectable**: when something can fail, add logs/metrics/traces that explain why.
- **Tests are real**: avoid fake-green tests; exercise real integrations where possible.
- **Small PRs, fast loops**: throughput comes from tight feedback loops, not heroic refactors.
- **Automation git must fail closed**: lane branches need sane upstreams, stale worktrees get pruned, and automation stops instead of creating more branch drift.
- **Document after learning**: if a bug or review uncovers a rule, write it down (and consider enforcing it).
