# Jev semantic lint

`python3 scripts/jev_lint.py` checks changed source with the rules in `.jev-lint.json`.
Use explicit repository-relative paths to check only your contribution. `--staged`
reads the Git index; `--base <sha>` checks a committed change; `--all` selects all
tracked source covered by the policy. `--dry-run` shows coverage without a request.

Set `TYPESAFE_API_KEY`, or point `JEV_ENV_FILE` to an existing env file. The runner
can also read the single key from the repo `.env` or `~/.config/jev/env`; it never
executes env files. An explicitly configured local System One service can use
`JEV_BASE_URL` and `JEV_MODEL`; use `JEV_ENDPOINT_API_KEY` only if that endpoint needs authentication. Cloud credentials are never automatically sent to other endpoints. Hosted Jev uses `https://api.typesafe.ai` by default.
GitHub Actions needs the `TYPESAFE_API_KEY` repository secret. Fork PRs without
that secret cannot claim a semantic pass; run the check in an authorized environment.

No source is rewritten. Only allowlisted source is sent. Every selected file is
covered without silent truncation; request/time limits return an incomplete check.
Explicit paths, `--staged` and `--all` send whole files. `--base` sends each changed
hunk with 20 lines of context, the line numbers it adds and the file's import
statements; a slice of a long hunk that adds nothing is not sent. Scope is chosen per
rule: a rule marked `"scope": "file"` in `.jev-lint.json` (the React hook and render
rules, which need the enclosing component) is asked separately, about whole top-level
declarations: those holding a changed line under `--base`, every one otherwise. A
declaration is never split; one over 120,000 characters stops the run as incomplete
(split it). Any other `scope` value stops the run.
CI runs `--base` with `--max-requests 64 --max-seconds 240` so a broad migration
fits the 5-minute job; a larger change returns an incomplete check, not a pass.
Exit 0 means the selected scope passed (or had no applicable changes), 1 means a
violation, and 2 means uncertainty or an unavailable/incomplete check. Findings
identify the file, chunk or hunk start line, rule and probability; they are not proofs.
The configurable thresholds are operating choices, not measured error guarantees.

Identical source, model, endpoint and questions reuse a private Git-directory
answer cache for at most one day. `--no-cache` forces fresh checks. The cache holds
answers and hashes, not source or credentials. Rules for one file are batched together; unrelated files never share evidence.

Type checking, parsers, generated-contract checks, builds and behavioral tests stay
separate. ESLint/Ruff style gates and keyword-based semantic lint are replaced by
Jev. Do not reintroduce them as a workaround for a Jev outage.

Provider contract: https://docs.typesafe.ai/api
Agent usage: https://docs.typesafe.ai/introduction/coding-agents

On LXC100, run the optional real-provider regression matrix after changing rules:
`JEV_LIVE_TESTS=1 uv run pytest -q -s tests/unit/test_jev_policy_live.py`. It checks
positive and negative cases for each rule, including real HTTP PATCH vs mocking,
wire types vs UI types, Model Cards, and React hook ordering.
