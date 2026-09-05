#!/usr/bin/env python3
"""Provision the native LiteLLM ledger; never restart the gateway or run a model.

Run with Ragweld's Python on its runtime host. Secrets stay in owner-only files
and subprocess input/environment, never command arguments or normal output.
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import io
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import asyncpg
import yaml
from dotenv.parser import parse_stream

MARKER = "ragweld-native-litellm-ledger-v1"
MANAGED = {"DATABASE_URL", "STORE_PROMPTS_IN_SPEND_LOGS", "DEFAULT_MAX_RETRIES", "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"}
PRIVATE_BINDINGS = MANAGED | {
    "DIRECT_URL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_OTEL_HOST",
    "POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB",
}


class RefusedError(RuntimeError):
    pass


def validated_environment(raw: bytes) -> dict[str, str | None]:
    """Validate every private binding before selecting a destination or identity."""
    values: dict[str, str | None] = {}
    for binding in parse_stream(io.StringIO(raw.decode())):
        if binding.error:
            raise RefusedError("Malformed existing environment; no settings were rewritten")
        key = binding.key
        if key is None:
            continue
        if key in PRIVATE_BINDINGS and key in values and values[key] != binding.value:
            reason = {
                "DEFAULT_MAX_RETRIES": "Provider SDK retries must be disabled",
                "STORE_PROMPTS_IN_SPEND_LOGS": "Prompt storage must be disabled",
            }.get(key, "ledger/telemetry destination or identity is ambiguous")
            raise RefusedError(f"Conflicting duplicate private environment binding: {reason}; no settings were rewritten")
        values[key] = binding.value
    return values


def private_file(path: Path) -> tuple[bytes, os.stat_result]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RefusedError("Secret input must be a regular, unlinked file")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise RefusedError("Secret input must have mode 0600")
    if info.st_uid not in {0, os.geteuid()} and os.geteuid() != 0:
        raise RefusedError("Secret input belongs to a different owner")
    return path.read_bytes(), info


def atomic_private(path: Path, data: bytes, owner: os.stat_result) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        os.fchown(fd, owner.st_uid, owner.st_gid)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def env_update(original: bytes, dsn: str) -> bytes:
    # Parse whole bindings so a managed-looking line inside an unrelated multiline
    # value remains part of that value, not a setting to delete.
    values = validated_environment(original)
    if values.get("DATABASE_URL") not in (None, dsn):
        raise RefusedError("Existing database destination differs from the selected ledger; no settings were rewritten")
    output: list[str] = []
    for binding in parse_stream(io.StringIO(original.decode())):
        if binding.error:
            raise RefusedError("Malformed existing environment; no settings were rewritten")
        if binding.key == "DEFAULT_MAX_RETRIES" and binding.value != "0":
            raise RefusedError("Provider SDK retries must be disabled: DEFAULT_MAX_RETRIES=0; no settings were rewritten")
        if binding.key == "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT" and binding.value != "false":
            raise RefusedError("Native telemetry content capture must be disabled; no settings were rewritten")
        if binding.key not in MANAGED:
            output.append(binding.original.string)
    text = "".join(output)
    if text and not text.endswith("\n"):
        text += "\n"
    return (text + f"DATABASE_URL={dsn}\nSTORE_PROMPTS_IN_SPEND_LOGS=false\nDEFAULT_MAX_RETRIES=0\nOTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false\n").encode()


def telemetry_environment(original: bytes, project: dict[str, str | None]) -> bytes:
    """Copy the existing private project identity; never rotate or print a key."""
    desired = {key: project.get(key) for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")}
    if any(not value or not value.strip() or value == "disabled" for value in desired.values()):
        raise RefusedError("Native telemetry requires both existing Langfuse project credentials in runtime.env")
    desired["LANGFUSE_OTEL_HOST"] = "http://langfuse:3000"
    found = set()
    for binding in parse_stream(io.StringIO(original.decode())):
        if binding.error:
            raise RefusedError("Malformed existing environment; no settings were rewritten")
        if binding.key in desired:
            if binding.value != desired[binding.key]:
                raise RefusedError("Existing native telemetry identity or destination conflicts with the private project; no settings were rewritten")
            found.add(binding.key)
    text = original.decode()
    if text and not text.endswith("\n"):
        text += "\n"
    for key, value in desired.items():
        if key not in found:
            text += f"{key}={json.dumps(value)}\n"
    return text.encode()


def validate_retry_policy(config: object) -> None:
    """Check the native controls before any migration container is dispatched.

    These settings harden the known native1.94 paths. They do not establish
    runtime attempt-count proof through the native management API.
    """
    refusal = "Generated config must disable native retries, fallback routes and shadow models"
    if not isinstance(config, dict):
        raise RefusedError(refusal)

    def zero(value: object) -> bool:
        return type(value) is int and value == 0

    def no_overrides(params: dict[str, object]) -> bool:
        return (
            all(params.get(key) is None or zero(params[key]) for key in ("num_retries", "max_retries"))
            and not params.get("silent_model")
            and all(params.get(key) in (None, [], {}) for key in (
                "fallbacks", "default_fallbacks", "context_window_fallbacks", "content_policy_fallbacks",
                "retry_policy", "model_group_retry_policy",
            ))
        )

    native = config.get("litellm_settings", {})
    router = config.get("router_settings", {})
    deployments = config.get("model_list", [])
    defaults = router.get("default_litellm_params") if isinstance(router, dict) else None
    valid = (
        isinstance(native, dict) and isinstance(router, dict)
        and zero(native.get("DEFAULT_MAX_RETRIES")) and zero(native.get("num_retries"))
        and no_overrides(native) and zero(router.get("num_retries")) and no_overrides(router)
        and router.get("enable_weighted_failover") is False
        and {"retry_policy", "model_group_retry_policy", "fallbacks", "context_window_fallbacks", "content_policy_fallbacks"}.issubset(router)
        and (defaults is None or isinstance(defaults, dict) and no_overrides(defaults))
        and isinstance(deployments, list) and bool(deployments)
        and all(
            isinstance(row, dict) and isinstance(row.get("litellm_params"), dict)
            and zero(row["litellm_params"].get("num_retries"))
            and zero(row["litellm_params"].get("max_retries"))
            and no_overrides(row["litellm_params"])
            for row in deployments
        )
    )
    if not valid:
        raise RefusedError(refusal)


def validate_dsn(value: str, args: argparse.Namespace) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme not in {"postgres", "postgresql"}
        or parsed.hostname != args.gateway_db_host or (parsed.port or 5432) != args.gateway_db_port
        or unquote(parsed.username or "") != args.database
        or unquote(parsed.path.removeprefix("/")) != args.database
        or parsed.query != "schema=public" or parsed.fragment or not parsed.password):
        raise RefusedError("Existing DATABASE_URL does not match this dedicated ledger target")
    return unquote(parsed.password)


async def provision(args: argparse.Namespace, admin: dict[str, str | None]) -> None:
    target = args.etc_root / "litellm.env"
    original, owner = private_file(target)
    existing = validated_environment(original).get("DATABASE_URL")
    pending = args.etc_root / ".litellm-ledger.pending.json"
    if pending.exists():
        payload, _ = private_file(pending)
        candidate = json.loads(payload)
        if candidate.get("marker") != MARKER:
            raise RefusedError("Unrecognized pending ledger setup")
        dsn = candidate["dsn"]
        password = validate_dsn(dsn, args)
        if existing and existing != dsn:
            raise RefusedError("Existing and pending ledger credentials disagree")
    elif existing:
        dsn = existing
        password = validate_dsn(dsn, args)
    else:
        password = secrets.token_urlsafe(48)
        host = args.gateway_db_host
        if ":" in host:
            host = f"[{host}]"
        dsn = f"postgresql://{args.database}:{quote(password, safe='')}@{host}:{args.gateway_db_port}/{args.database}?schema=public"
    replacement = env_update(telemetry_environment(original, admin), dsn)
    conn = await asyncpg.connect(
        host=admin.get("POSTGRES_HOST") or "127.0.0.1",
        port=int(admin.get("POSTGRES_PORT") or 5432),
        user=admin.get("POSTGRES_USER") or "postgres",
        password=admin.get("POSTGRES_PASSWORD"), database="postgres", timeout=10,
    )
    try:
        await conn.execute("SELECT pg_advisory_lock(hashtextextended($1, 0))", MARKER + args.database)
        role = await conn.fetchrow("""SELECT oid, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
            rolreplication, rolbypassrls, rolinherit, shobj_description(oid, 'pg_authid') AS comment
            FROM pg_roles WHERE rolname=$1""", args.database)
        if role and (role["comment"] != MARKER or not role["rolcanlogin"]
                     or any(role[key] for key in ("rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls", "rolinherit"))):
            raise RefusedError("Existing ledger role is unmanaged or overprivileged; it was not altered")
        if role and await conn.fetchval(
            "SELECT count(*) FROM pg_auth_members WHERE member=$1 OR roleid=$1", role["oid"]
        ):
            raise RefusedError("Existing ledger role has memberships; it was not altered")
        database = await conn.fetchrow("""SELECT datdba, pg_get_userbyid(datdba) AS owner,
            shobj_description(oid, 'pg_database') AS comment FROM pg_database WHERE datname=$1""", args.database)
        if database and (not role or database["owner"] != args.database or database["comment"] not in {None, MARKER}):
            raise RefusedError("Existing database is not owned by this managed ledger role")
        if not pending.exists() and not existing:
            atomic_private(pending, json.dumps({"marker": MARKER, "dsn": dsn}).encode(), owner)
        if not role:
            async with conn.transaction():
                # Identifiers are restricted below; password quoting remains explicit.
                escaped = password.replace("'", "''")
                await conn.execute(f'CREATE ROLE "{args.database}" LOGIN PASSWORD \'{escaped}\' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 20')
                await conn.execute(f'COMMENT ON ROLE "{args.database}" IS \'{MARKER}\'')
        if not database:
            await conn.execute(f'CREATE DATABASE "{args.database}" OWNER "{args.database}"')
        await conn.execute(f'REVOKE ALL ON DATABASE "{args.database}" FROM PUBLIC')
        await conn.execute(f'COMMENT ON DATABASE "{args.database}" IS \'{MARKER}\'')
        # Verify the stored credential really authenticates; never reset an existing
        # role's password silently. Use the admin's reachable endpoint on this host.
        owned = await asyncpg.connect(host=admin.get("POSTGRES_HOST") or "127.0.0.1",
            port=int(admin.get("POSTGRES_PORT") or 5432), user=args.database,
            password=password, database=args.database, timeout=10)
        try:
            await owned.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        finally:
            await owned.close()
        if target.read_bytes() != original:
            raise RefusedError("litellm.env changed during setup; pending credentials retained")
        if replacement != original:
            atomic_private(target, replacement, owner)
        pending.unlink(missing_ok=True)
    finally:
        await conn.close()
    print("Dedicated ledger database and owner-only environment are ready; gateway not restarted.")


async def verify_migrations(args: argparse.Namespace, password: str) -> int:
    runtime, _ = private_file(args.etc_root / "runtime.env")
    admin = validated_environment(runtime)
    conn = await asyncpg.connect(host=admin.get("POSTGRES_HOST") or "127.0.0.1",
        port=int(admin.get("POSTGRES_PORT") or 5432), user=args.database,
        password=password, database=args.database, timeout=10)
    try:
        row = await conn.fetchrow('''SELECT count(*) FILTER (WHERE finished_at IS NOT NULL) AS finished,
            count(*) FILTER (WHERE finished_at IS NULL AND rolled_back_at IS NULL) AS failed
            FROM public._prisma_migrations''')
        if not row["finished"] or row["failed"]:
            raise RefusedError("Native migration history is empty or has unresolved failures")
        if not await conn.fetchval("SELECT to_regclass('public.\"LiteLLM_SpendLogs\"') IS NOT NULL"):
            raise RefusedError("Native spend table is absent after migration")
        return int(row["finished"])
    finally:
        await conn.close()


def migrate(args: argparse.Namespace) -> None:
    original, _ = private_file(args.etc_root / "litellm.env")
    values = validated_environment(original)
    password = validate_dsn(values.get("DATABASE_URL") or "", args)
    if values.get("STORE_PROMPTS_IN_SPEND_LOGS") != "false":
        raise RefusedError("Prompt storage must be disabled before migrations")
    if values.get("DEFAULT_MAX_RETRIES") != "0":
        raise RefusedError("Provider SDK retries must be disabled: DEFAULT_MAX_RETRIES=0")
    env_update(original, values["DATABASE_URL"] or "")  # Also reject conflicting duplicate bindings.
    runtime, _ = private_file(args.etc_root / "runtime.env")
    project = validated_environment(runtime)
    if telemetry_environment(original, project) != original or values.get("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT") != "false":
        raise RefusedError("Run provisioning to install private native telemetry settings before migrations")
    if values.get("DIRECT_URL") and values["DIRECT_URL"] != values["DATABASE_URL"]:
        raise RefusedError("DIRECT_URL points outside the dedicated ledger; no migration was attempted")
    if str(values.get("DISABLE_SCHEMA_UPDATE") or "false").strip().lower() != "false":
        raise RefusedError("Schema updates are disabled; no migration was attempted")
    config = yaml.safe_load((args.repo_root / "infra/litellm-config.yaml").read_text())
    validate_retry_policy(config)
    if config.get("litellm_settings", {}).get("turn_off_message_logging") is not True:
        raise RefusedError("Generated config must disable native telemetry message logging")
    settings = config.get("general_settings", {})
    if settings.get("store_prompts_in_spend_logs") is not False or settings.get("disable_spend_logs") is not False:
        raise RefusedError("Generated config must disable prompt storage and enable native spend logs")
    if settings.get("disable_prisma_schema_update") not in {None, False, "false"}:
        raise RefusedError("Generated config disables native migrations")
    if settings.get("database_url") not in {None, "os.environ/DATABASE_URL"}:
        raise RefusedError("Generated config overrides the dedicated ledger database")
    command = ["docker", "compose", "--project-directory", str(args.repo_root), "--project-name", args.project]
    for name in ("runtime.env", "langfuse.env"):
        path = args.etc_root / name
        if path.exists():
            private_file(path)
            command += ["--env-file", str(path)]
    for path in args.compose_file or ["docker-compose.yml", "infra/docker-compose.observability.yml", "deploy/proxmox/docker-compose.yml"]:
        command += ["-f", str(args.repo_root / path)]
    environment = dict(os.environ)
    oidc_file = args.etc_root / "langfuse-oidc-client-secret"
    if oidc_file.exists():
        raw, _ = private_file(oidc_file)
        environment["LANGFUSE_OIDC_CLIENT_SECRET"] = raw.decode().rstrip("\n")
    elif not args.compose_file:
        raise RefusedError("Production Compose requires the private Langfuse OIDC secret file")
    command += ["run", "--rm", "--no-deps", "litellm", "--config", "/app/config.yaml",
                "--use_v2_migration_resolver", "--enforce_prisma_migration_check", "--skip_server_startup"]
    log = args.etc_root / "litellm-ledger-migration.log"
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        result = subprocess.run(command, cwd=args.repo_root, env=environment,
                                stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RefusedError("Native migration failed; inspect the owner-only migration log. Gateway not restarted")
    count = asyncio.run(verify_migrations(args, password))
    print(f"Native v2 migrations verified: {count} finished, no unresolved failures; gateway not restarted.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["provision", "migrate"])
    parser.add_argument("--apply", action="store_true", help="Required for either operator mutation")
    parser.add_argument("--etc-root", type=Path, default=Path("/etc/ragweld"))
    parser.add_argument("--repo-root", type=Path, default=Path("/opt/ragweld"))
    parser.add_argument("--database", default="ragweld_litellm")
    parser.add_argument("--gateway-db-host", default="postgres")
    parser.add_argument("--gateway-db-port", type=int, default=5432)
    parser.add_argument("--project", default="ragweld")
    parser.add_argument("--compose-file", action="append")
    args = parser.parse_args()
    if not args.apply:
        parser.error("Pass --apply after reviewing the target; no action was performed")
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", args.database):
        parser.error("Database/role must be a simple lowercase PostgreSQL identifier")
    if args.etc_root == Path("/etc/ragweld") and os.geteuid() != 0:
        parser.error("Production setup requires root")
    lock_path = args.etc_root / ".litellm-ledger.lock"
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.action == "provision":
            runtime, _ = private_file(args.etc_root / "runtime.env")
            asyncio.run(provision(args, validated_environment(runtime)))
        else:
            migrate(args)


if __name__ == "__main__":
    try:
        main()
    except RefusedError as exc:
        raise SystemExit(str(exc)) from None
    except Exception as exc:
        # asyncpg/subprocess exception strings may contain a connection credential.
        raise SystemExit(f"Ledger setup failed ({type(exc).__name__}); private state retained for inspection") from None
