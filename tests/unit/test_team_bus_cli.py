from pathlib import Path

from server.team_bus import cli
from server.team_bus.models import MessageType, TeamMessage
from server.team_bus.relay import TeamRelay
from server.team_bus.store import TeamStore

ROOT = Path(__file__).resolve().parents[2]


def _make_team_with_message(tmp_path) -> TeamStore:
    store = TeamStore(base_dir=tmp_path / "teams")
    store.create_team(
        name="alpha",
        description="test team",
        lead_name="lead",
        lead_agent_id="agent-lead",
    )
    store.add_member(team="alpha", name="worker", agent_id="agent-worker")
    relay = TeamRelay(store=store)
    store.queue_message(
        "alpha",
        TeamMessage(
            team="alpha",
            from_member="lead",
            to_member="worker",
            type=MessageType.STATUS_UPDATE,
            text="hello",
        ),
    )
    relay.run_once("alpha")
    return store


def test_wait_rejects_nan_timeout_seconds(tmp_path, capsys) -> None:
    store = _make_team_with_message(tmp_path)
    rc = cli.main(
        [
            "--base-dir",
            str(store.base_dir),
            "wait",
            "alpha",
            "--member",
            "worker",
            "--include-existing",
            "--timeout-seconds",
            "nan",
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert "--timeout-seconds must be a finite number > 0" in captured.err


def test_codex_overlay_installer_keeps_emergency_bypass_before_overlay_exec() -> None:
    source = (ROOT / "scripts" / "install_codex_agent_teams.sh").read_text(encoding="utf-8")
    bypass = 'if [[ "\\${CODEX_TEAM_OVERLAY_DISABLE:-0}" == "1" ]]'
    overlay_exec = 'exec "\\${PREFIX}/.venv/bin/python" "\\${PREFIX}/bin/codex_overlay.py"'

    assert bypass in source
    assert overlay_exec in source
    assert source.index(bypass) < source.index(overlay_exec)
