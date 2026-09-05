"""Real operator provisioning with an explicitly disposable PostgreSQL endpoint.

Set RAGWELD_NATIVE_LEDGER_TEST_ADMIN_DSN deliberately. These tests never infer it
from the application's PostgreSQL settings, start containers, or invoke providers.
Each case creates and removes only its unique pytest_litellm_setup_* resources.
The pinned image's real migration-only acceptance is also run before deployment.
"""
from __future__ import annotations

import asyncio
import json
import os
import runpy
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

import asyncpg
import pytest
import yaml
from dotenv import dotenv_values

from tests.service_requirements import _strict_mode

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy/proxmox/provision_litellm_ledger.py"
ADMIN_DSN_ENV = "RAGWELD_NATIVE_LEDGER_TEST_ADMIN_DSN"
MARKER = "ragweld-native-litellm-ledger-v1"
pytestmark = pytest.mark.asyncio


@dataclass
class SetupCase:
    etc: Path
    database: str
    admin: asyncpg.Connection
    host: str
    port: int

    def write(self, name: str, data: bytes) -> None:
        path = self.etc / name
        path.write_bytes(data)
        path.chmod(0o600)

    async def run(self, action: str = "provision", *, succeeds: bool = True, repo_root: Path = ROOT) -> str:
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(SCRIPT), action, "--apply", "--etc-root", str(self.etc),
            "--repo-root", str(repo_root), "--database", self.database,
            "--gateway-db-host", self.host, "--gateway-db-port", str(self.port),
            env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT), "RAGWELD_LOAD_DOTENV": "0"},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise
        output = (stdout + stderr).decode()
        assert "postgresql://" not in output, "Operator output exposed a DSN"
        assert "sentinel-provider-123" not in output, "Operator output exposed a provider key"
        assert (process.returncode == 0) == succeeds, f"Unexpected operator status: {output}"
        return output


@pytest.fixture
async def setup_case(tmp_path: Path):
    dsn = os.environ.get(ADMIN_DSN_ENV, "").strip()
    if not dsn:
        message = f"{ADMIN_DSN_ENV} must explicitly identify a disposable native-ledger test PostgreSQL"
        if _strict_mode():
            pytest.fail(message)
        pytest.skip(message)
    parsed = urlsplit(dsn)
    assert parsed.scheme in {"postgres", "postgresql"} and parsed.hostname
    database = f"pytest_litellm_setup_{uuid.uuid4().hex}"
    admin = await asyncpg.connect(dsn, timeout=5)
    etc = tmp_path / "etc"
    etc.mkdir(mode=0o700)
    case = SetupCase(etc, database, admin, parsed.hostname, parsed.port or 5432)
    fields = {
        "POSTGRES_HOST": case.host, "POSTGRES_PORT": str(case.port),
        "POSTGRES_USER": unquote(parsed.username or "postgres"),
        "POSTGRES_PASSWORD": unquote(parsed.password or ""),
        "LANGFUSE_PUBLIC_KEY": "pk-synthetic-project",
        "LANGFUSE_SECRET_KEY": "sk-synthetic-project-secret",
    }
    case.write("runtime.env", "".join(f"{key}={json.dumps(value)}\n" for key, value in fields.items()).encode())
    case.write("litellm.env", b"PROVIDER_FIXTURE_KEY=sentinel-provider-123\n")
    try:
        yield case
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
        await admin.execute(f'DROP ROLE IF EXISTS "{database}"')
        await admin.execute(f'DROP ROLE IF EXISTS "{database}_member"')
    await admin.close()


async def test_provision_copies_project_credentials_privately_and_idempotently(setup_case: SetupCase) -> None:
    case = setup_case
    output = await case.run()
    assert "sk-synthetic-project-secret" not in output
    raw = (case.etc / "litellm.env").read_bytes()
    values = dotenv_values(case.etc / "litellm.env", interpolate=False)
    assert values["LANGFUSE_PUBLIC_KEY"] == "pk-synthetic-project"
    assert values["LANGFUSE_SECRET_KEY"] == "sk-synthetic-project-secret"
    assert values["LANGFUSE_OTEL_HOST"] == "http://langfuse:3000"
    assert values["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] == "false"
    await case.run()
    assert (case.etc / "litellm.env").read_bytes() == raw


@pytest.mark.parametrize("conflict", [
    b"LANGFUSE_PUBLIC_KEY=other-project\n", b"LANGFUSE_SECRET_KEY=other-secret\n",
    b"LANGFUSE_OTEL_HOST=https://foreign.invalid\n",
    b"OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true\n",
    b"LANGFUSE_SECRET_KEY=other-secret\nLANGFUSE_SECRET_KEY=sk-synthetic-project-secret\n",
])
async def test_provision_refuses_telemetry_conflicts_before_database_mutation(setup_case: SetupCase, conflict: bytes) -> None:
    case = setup_case
    original = (case.etc / "litellm.env").read_bytes() + conflict
    case.write("litellm.env", original)
    output = await case.run(succeeds=False)
    assert "telemetry" in output.lower()
    assert "other-secret" not in output
    assert (case.etc / "litellm.env").read_bytes() == original
    assert not await case.admin.fetchval("SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=$1)", case.database)


@pytest.mark.parametrize("missing", ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"])
async def test_provision_requires_complete_existing_project_credentials(setup_case: SetupCase, missing: str) -> None:
    case = setup_case
    values = dotenv_values(case.etc / "runtime.env", interpolate=False)
    values.pop(missing)
    case.write("runtime.env", "".join(f"{key}={json.dumps(value)}\n" for key, value in values.items()).encode())
    await case.run(succeeds=False)
    assert not await case.admin.fetchval("SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=$1)", case.database)


@pytest.mark.parametrize("capture", [False, None, "true"])
async def test_migrations_refuse_missing_or_disabled_native_message_redaction(setup_case: SetupCase, tmp_path: Path, capture: object) -> None:
    case = setup_case
    await case.run()
    config = yaml.safe_load((ROOT / "infra/litellm-config.yaml").read_text())
    config["litellm_settings"]["turn_off_message_logging"] = capture
    owned_repo = tmp_path / "owned-repo"
    (owned_repo / "infra").mkdir(parents=True)
    (owned_repo / "infra/litellm-config.yaml").write_text(yaml.safe_dump(config))
    output = await case.run("migrate", succeeds=False, repo_root=owned_repo)
    assert "disable native telemetry message logging" in output
    assert not (case.etc / "litellm-ledger-migration.log").exists()


@pytest.mark.parametrize("extra", [
    b"# operator comment\nUNRELATED=value\n",
    b"UNRELATED='first line\nDATABASE_URL=literal-inside-another-value\nlast line'\n",
    b"export UNRELATED=keep\r\n# preserve CRLF\r\n",
    b"UNRELATED='preserve literal\nDEFAULT_MAX_RETRIES=2\ninside multiline'\n",
])
async def test_provision_preserves_private_environment_and_resumes_without_rotation(
    setup_case: SetupCase, extra: bytes,
) -> None:
    case = setup_case
    original = (case.etc / "litellm.env").read_bytes() + extra
    case.write("litellm.env", original)
    owner = (case.etc / "litellm.env").stat()
    await case.run()
    first = (case.etc / "litellm.env").read_bytes()
    assert first.startswith(original)
    current = (case.etc / "litellm.env").stat()
    assert (current.st_uid, current.st_gid) == (owner.st_uid, owner.st_gid)
    assert current.st_mode & 0o777 == 0o600
    saved = dotenv_values(case.etc / "litellm.env", interpolate=False)
    assert saved["STORE_PROMPTS_IN_SPEND_LOGS"] == "false"
    assert saved["DEFAULT_MAX_RETRIES"] == "0"
    await case.run()
    assert (case.etc / "litellm.env").read_bytes() == first
    # Actual partial-install state: managed resources exist, publication did not finish.
    case.write(".litellm-ledger.pending.json", json.dumps({"marker": MARKER, "dsn": saved["DATABASE_URL"]}).encode())
    case.write("litellm.env", original)
    await case.run()
    assert (case.etc / "litellm.env").read_bytes() == first
    assert not (case.etc / ".litellm-ledger.pending.json").exists()
    role = await case.admin.fetchrow("""SELECT rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
        rolreplication, rolbypassrls, rolinherit FROM pg_roles WHERE rolname=$1""", case.database)
    assert role and role["rolcanlogin"]
    assert not any(value for key, value in role.items() if key != "rolcanlogin")
    assert await case.admin.fetchval("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=$1", case.database) == case.database
    assert not await case.admin.fetchval("""SELECT EXISTS(SELECT 1 FROM pg_database d,
        LATERAL aclexplode(d.datacl) a WHERE d.datname=$1 AND a.grantee=0)""", case.database)


@pytest.mark.parametrize("problem", ["mode", "symlink", "hardlink", "malformed", "foreign_url"])
async def test_provision_refuses_unsafe_env_before_creating_resources(setup_case: SetupCase, problem: str) -> None:
    case = setup_case
    target = case.etc / "litellm.env"
    if problem == "mode":
        target.chmod(0o644)
    elif problem == "symlink":
        target.rename(case.etc / "other.env")
        target.symlink_to(case.etc / "other.env")
    elif problem == "hardlink":
        os.link(target, case.etc / "other.env")
    elif problem == "malformed":
        case.write("litellm.env", b"UNRELATED='unterminated\n")
    else:
        case.write("litellm.env", b"DATABASE_URL=postgresql://foreign:secret@127.0.0.1/foreign?schema=public\n")
    original = target.read_bytes()
    await case.run(succeeds=False)
    assert target.read_bytes() == original
    assert not await case.admin.fetchval("SELECT 1 FROM pg_roles WHERE rolname=$1", case.database)
    assert not await case.admin.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", case.database)


@pytest.mark.parametrize("problem", [
    "unmanaged_role",
    "privileged_role",
    "inherits_role",
    "delegates_role",
    "foreign_database",
])
async def test_provision_refuses_existing_resources_it_does_not_safely_own(setup_case: SetupCase, problem: str) -> None:
    case = setup_case
    if problem == "foreign_database":
        await case.admin.execute(f'CREATE DATABASE "{case.database}"')
    else:
        await case.admin.execute(f'CREATE ROLE "{case.database}" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT')
        if problem != "unmanaged_role":
            await case.admin.execute(f'COMMENT ON ROLE "{case.database}" IS \'{MARKER}\'')
        if problem == "privileged_role":
            await case.admin.execute(f'ALTER ROLE "{case.database}" CREATEDB')
        elif problem in {"inherits_role", "delegates_role"}:
            await case.admin.execute(f'CREATE ROLE "{case.database}_member"')
            if problem == "inherits_role":
                await case.admin.execute(f'GRANT "{case.database}_member" TO "{case.database}"')
            else:
                await case.admin.execute(f'GRANT "{case.database}" TO "{case.database}_member"')
    original = (case.etc / "litellm.env").read_bytes()
    before_role = await case.admin.fetchrow("SELECT * FROM pg_roles WHERE rolname=$1", case.database)
    output = await case.run(succeeds=False)
    assert (case.etc / "litellm.env").read_bytes() == original
    assert await case.admin.fetchrow("SELECT * FROM pg_roles WHERE rolname=$1", case.database) == before_role
    if problem in {"inherits_role", "delegates_role"}:
        assert "ledger role has memberships" in output
        ledger_oid = await case.admin.fetchval("SELECT oid FROM pg_roles WHERE rolname=$1", case.database)
        member_oid = await case.admin.fetchval("SELECT oid FROM pg_roles WHERE rolname=$1", f"{case.database}_member")
        expected_role, expected_member = (
            (member_oid, ledger_oid) if problem == "inherits_role" else (ledger_oid, member_oid)
        )
        assert await case.admin.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_auth_members WHERE roleid=$1 AND member=$2)",
            expected_role,
            expected_member,
        )
    if problem != "foreign_database":
        assert not await case.admin.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", case.database)


@pytest.mark.parametrize("extra,reason", [
    (b"DIRECT_URL=postgresql://foreign/database\n", "DIRECT_URL"),
    (b"DISABLE_SCHEMA_UPDATE=true\n", "Schema updates are disabled"),
    (b"STORE_PROMPTS_IN_SPEND_LOGS=true\n", "Prompt storage must be disabled"),
    (b"DEFAULT_MAX_RETRIES=2\n", "Provider SDK retries must be disabled"),
])
async def test_migrations_refuse_unsafe_overrides_before_starting_any_container(
    setup_case: SetupCase, extra: bytes, reason: str,
) -> None:
    case = setup_case
    await case.run()
    original = (case.etc / "litellm.env").read_bytes()
    case.write("litellm.env", original + extra)
    assert reason in await case.run("migrate", succeeds=False)
    assert not (case.etc / "litellm-ledger-migration.log").exists()


@pytest.mark.parametrize("extra", [
    b"DEFAULT_MAX_RETRIES=2\n", b"DEFAULT_MAX_RETRIES=\n",
    b"DEFAULT_MAX_RETRIES=0\nDEFAULT_MAX_RETRIES=2\n",
    b"DEFAULT_MAX_RETRIES=2\nDEFAULT_MAX_RETRIES=0\n",
    b"export DEFAULT_MAX_RETRIES='false'\n",
])
async def test_provision_refuses_conflicting_sdk_retry_env_before_creating_resources(setup_case: SetupCase, extra: bytes) -> None:
    case = setup_case
    original = (case.etc / "litellm.env").read_bytes() + extra
    case.write("litellm.env", original)
    output = await case.run(succeeds=False)
    assert "Provider SDK retries must be disabled" in output
    assert (case.etc / "litellm.env").read_bytes() == original
    assert not await case.admin.fetchval("SELECT 1 FROM pg_roles WHERE rolname=$1", case.database)
    assert not await case.admin.fetchval("SELECT 1 FROM pg_database WHERE datname=$1", case.database)


@pytest.mark.parametrize("section,field,value", [
    ("litellm_settings", "DEFAULT_MAX_RETRIES", 2),
    ("litellm_settings", "DEFAULT_MAX_RETRIES", "0"),
    ("litellm_settings", "DEFAULT_MAX_RETRIES", False),
    ("router_settings", "num_retries", 2),
    ("router_settings", "retry_policy", {"RateLimitErrorRetries": 2}),
    ("router_settings", "model_group_retry_policy", {"sensor": {"TimeoutErrorRetries": 2}}),
    ("router_settings", "fallbacks", [{"sensor": ["secondary"]}]),
    ("router_settings", "default_fallbacks", ["secondary"]),
    ("router_settings", "default_litellm_params", {"default_fallbacks": ["secondary"]}),
    ("router_settings", "context_window_fallbacks", [{"sensor": ["secondary"]}]),
    ("router_settings", "content_policy_fallbacks", [{"sensor": ["secondary"]}]),
    ("router_settings", "enable_weighted_failover", True),
    ("router_settings", "default_litellm_params", {"num_retries": 2}),
    ("deployment", "num_retries", 2),
    ("deployment", "max_retries", 2),
    ("deployment", "silent_model", "secondary"),
    ("deployment", "default_fallbacks", ["secondary"]),
])
async def test_migrations_refuse_native_retry_overrides_before_starting_any_container(
    setup_case: SetupCase, tmp_path: Path, section: str, field: str, value: object,
) -> None:
    case = setup_case
    await case.run()
    config = yaml.safe_load((ROOT / "infra/litellm-config.yaml").read_text())
    target = config["model_list"][0]["litellm_params"] if section == "deployment" else config[section]
    target[field] = value
    fixture_repo = tmp_path / "repo"
    (fixture_repo / "infra").mkdir(parents=True)
    (fixture_repo / "infra/litellm-config.yaml").write_text(yaml.safe_dump(config))
    output = await case.run("migrate", succeeds=False, repo_root=fixture_repo)
    assert "Generated config must disable native retries, fallback routes and shadow models" in output
    assert not (case.etc / "litellm-ledger-migration.log").exists()


async def test_canonical_generated_config_passes_native_retry_preflight() -> None:
    implementation = runpy.run_path(str(SCRIPT))
    config = yaml.safe_load((ROOT / "infra/litellm-config.yaml").read_text())
    implementation["validate_retry_policy"](config)


@pytest.mark.parametrize("file,key,foreign", [
    ("litellm.env", "DATABASE_URL", "postgresql://foreign:private-foreign-key@127.0.0.1/foreign"),
    ("runtime.env", "LANGFUSE_PUBLIC_KEY", "pk-foreign-project"),
    ("runtime.env", "LANGFUSE_SECRET_KEY", "sk-foreign-project-private"),
    ("runtime.env", "POSTGRES_HOST", "foreign.invalid"),
])
@pytest.mark.parametrize("foreign_first", [False, True])
async def test_conflicting_private_bindings_are_refused_before_any_destination_is_selected(
    setup_case: SetupCase, file: str, key: str, foreign: str, foreign_first: bool,
) -> None:
    case = setup_case
    await case.run()
    path = case.etc / file
    original = path.read_bytes()
    binding = f"{key}={json.dumps(foreign)}\n".encode()
    conflicting = binding + original if foreign_first else original + binding
    case.write(file, conflicting)
    target = (case.etc / "litellm.env").read_bytes()
    output = await case.run(succeeds=False)
    assert "Conflicting duplicate private environment binding" in output
    assert foreign not in output
    assert path.read_bytes() == conflicting
    assert (case.etc / "litellm.env").read_bytes() == target


@pytest.mark.parametrize("key", ["DATABASE_URL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"])
async def test_equivalent_repeated_private_bindings_keep_the_same_identity(setup_case: SetupCase, key: str) -> None:
    case = setup_case
    await case.run()
    name = "litellm.env" if key == "DATABASE_URL" else "runtime.env"
    values = dotenv_values(case.etc / name, interpolate=False)
    original = (case.etc / name).read_bytes()
    case.write(name, original + f"{key}={json.dumps(values[key])}\n".encode())
    await case.run()
    assert dotenv_values(case.etc / name, interpolate=False)[key] == values[key]
