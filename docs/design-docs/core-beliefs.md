# Core Beliefs (Agent-First)

These are the taste and architecture invariants we want to compound over time. When a belief becomes important and repeatedly violated, promote it into mechanical enforcement (scripts/hooks/tests/lints).

- **Pydantic at serialized boundaries**: validate public API payloads, persisted operator configuration, and untrusted external/cross-process data with domain-owned schemas.
- **Generated public wire contracts**: TypeScript representations of registered API/configuration payloads come from `/Users/davidmontgomery/ragweld/web/src/types/generated.ts`.
- **Local types stay local**: internal Python domain types and local UI props, state, and view models may use the language's ordinary type tools.
- **Explicit boundary transformations**: named, typed, tested mappings are valid at semantic boundaries; hidden/lossy transforms and competing canonical contracts are not.
- **Boundaries over cleverness**: keep modules small and dependency directions obvious.
- **Progressive disclosure**: short entrypoints link to deeper pages; avoid monolithic manuals.
- **Mechanical enforcement beats reminders**: encode invariants in code so agents cannot ignore them.
- **Prefer boring, legible dependencies**: choose tools that are easy to reason about and easy to validate in-repo.
- **Minimize hidden state**: explicit inputs/outputs; avoid implicit globals and magic environment-driven behaviour.
- **Config controls real tunables**: operator/runtime choices belong in typed domain config; constants, invariants, derived values, and UI-only state do not become fake knobs.
- **Make failure modes inspectable**: when something can fail, add logs/metrics/traces that explain why.
- **Tests are real**: avoid fake-green tests; exercise real integrations where possible.
- **Small PRs, fast loops**: throughput comes from tight feedback loops, not heroic refactors.
- **Automation git must fail closed**: lane branches need sane upstreams, stale worktrees get pruned, and automation stops instead of creating more branch drift.
- **Document after learning**: if a bug or review uncovers a rule, write it down (and consider enforcing it).
