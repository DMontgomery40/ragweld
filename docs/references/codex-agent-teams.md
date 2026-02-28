# Codex Agent Teams (Safety Layer)

This repo includes a local, durable team message bus at `server/team_bus/`.
It mirrors Claude Team concepts while enforcing policy checks before delivery.

## Storage Layout

Default root: `~/.codex/teams/<team>/`

- `config.json`: team members + policy.
- `inboxes/<member>.json`: delivered messages (`pending`/`acked`).
- `outboxes/<member>.json`: queued/sent/rejected messages.
- `journal/events.jsonl`: append-only event log for auditing.

## Safety Controls

Policy fields are in `server/team_bus/models.py` (`TeamPolicy`):

- route allowlist (`allowedRoutes`)
- message type allowlist (`allowedMessageTypes`)
- max payload bytes (`maxMessageBytes`)
- sender rate limit (`maxMessagesPerMinute`)
- max hop count (`maxHops`)
- required-ack message types (`requireAckTypes`)

Enforcement happens in `server/team_bus/policy.py` and relay delivery in
`server/team_bus/relay.py`.

## CLI

Entry point: `scripts/codex_team.py`

Examples:

```bash
uv run scripts/codex_team.py create incident --lead-name orchestrator --lead-agent-id lead-1
uv run scripts/codex_team.py add-member incident --name worker-a --agent-id worker-a-1
uv run scripts/codex_team.py send incident --from-member orchestrator --to-member worker-a --type task_assignment --text "Investigate index corruption"
uv run scripts/codex_team.py relay incident --once
uv run scripts/codex_team.py tail incident --box inbox --member worker-a
uv run scripts/codex_team.py ack incident --member worker-a --message-id <id>
uv run scripts/codex_team.py validate incident
uv run scripts/codex_team.py import-claude my-team --claude-root ~/.claude --overwrite
uv run scripts/codex_team.py watch incident --box journal --follow --poll-interval 0.5
uv run scripts/codex_team.py wait incident --member worker-a --timeout-seconds 120
```

## Import Compatibility

`import-claude` reads `~/.claude/teams/<team>/config.json` and member inboxes,
converts them into Codex team files, and logs an `imported` journal event.

## Global Install (Machine-Wide)

Install globally under `~/.codex`:

```bash
cd /Users/davidmontgomery/ragweld
./scripts/install_codex_agent_teams.sh --force
~/.codex/bin/codex-team list
```

This installs an isolated runtime in `~/.codex/agent-teams` and a global wrapper
binary `~/.codex/bin/codex-team`.

Portable bundle for other machines (no repo checkout required):

```bash
cd /Users/davidmontgomery/ragweld
./scripts/export_codex_agent_teams_bundle.sh
# copy the tar.gz to target machine, then:
tar -xzf codex-agent-teams-<timestamp>.tar.gz
cd codex-agent-teams-<timestamp>
./install_codex_agent_teams.sh --source ./team_bus --force
```

## Containerized Mode

Run the same CLI in Docker:

```bash
cd /Users/davidmontgomery/ragweld
./scripts/codex_team_container.sh --build --source ~/.codex/agent-teams/lib/team_bus list
./scripts/codex_team_container.sh --source ~/.codex/agent-teams/lib/team_bus relay incident --interval-seconds 0.5 --max-iterations 40
```
