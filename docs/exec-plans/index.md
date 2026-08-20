# Execution Plans

Plans are first-class artifacts. They let agents make progress without relying on external context.

## Lightweight plan vs execution plan

- **Lightweight plan**: a short checklist embedded in a PR description or a small doc. Use for low-risk, local changes.
- **Execution plan**: a tracked document in `active/` with decisions, progress, and verification steps. Use for multi-step or cross-cutting work.

## New plan template (required headers)

- **Goal**
- **Scope**
- **Non-goals**
- **Acceptance criteria**
- **Risks / failure modes**
- **Verification**
- **Rollout / rollback** (if applicable)

## Folders

- `active/`: plans currently in progress
- `completed/`: plans that have shipped
- `superseded/`: historical plans and handoffs that must not drive current execution

## Trackers

- [Tech debt tracker](tech-debt-tracker.md)
