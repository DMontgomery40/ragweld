#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
readonly ROOT_DIR
readonly ETC_ROOT="${RAGWELD_ETC_ROOT:-/etc/ragweld}"
readonly DEFAULT_ETC_ROOT="/etc/ragweld"
readonly PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

stat_mode() {
  local path="$1"
  if stat -f '%Lp' "$path" >/dev/null 2>&1; then
    stat -f '%Lp' "$path"
  else
    stat -c '%a' "$path"
  fi
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "required command missing: $1"
}

require_python_hash_support() {
  "$PYTHON_BIN" - <<'PY' >/dev/null
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
Argon2id
PY
}

read_secret_file() {
  local path="$1"
  "$PYTHON_BIN" - "$path" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).read_text(encoding="utf-8").rstrip("\n"), end="")
PY
}

random_alnum() {
  local length="$1"
  "$PYTHON_BIN" - "$length" <<'PY'
import secrets
import string
import sys

alphabet = string.ascii_letters + string.digits
length = int(sys.argv[1])
print("".join(secrets.choice(alphabet) for _ in range(length)), end="")
PY
}

random_hex() {
  local bytes="$1"
  openssl rand -hex "$bytes"
}

pbkdf2_sha512_digest() {
  local secret_path="$1"
  "$PYTHON_BIN" - "$secret_path" <<'PY'
import base64
import hashlib
import secrets
import sys
from pathlib import Path

def ab64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii").rstrip("=").replace("+", ".")

secret = Path(sys.argv[1]).read_text(encoding="utf-8").rstrip("\n").encode("utf-8")
salt = secrets.token_bytes(16)
rounds = 310000
digest = hashlib.pbkdf2_hmac("sha512", secret, salt, rounds)
print(f"$pbkdf2-sha512${rounds}${ab64(salt)}${ab64(digest)}", end="")
PY
}

argon2id_digest() {
  local password_path="$1"
  "$PYTHON_BIN" - "$password_path" <<'PY'
from pathlib import Path
import secrets
import sys
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

password = Path(sys.argv[1]).read_text(encoding="utf-8").rstrip("\n").encode("utf-8")
salt = secrets.token_bytes(16)
kdf = Argon2id(
    salt=salt,
    length=32,
    iterations=3,
    lanes=4,
    memory_cost=65536,
)
print(kdf.derive_phc_encoded(password), end="")
PY
}

write_atomic_file() {
  local destination="$1"
  local parent_dir
  local tmp_path
  parent_dir="$(dirname "$destination")"
  tmp_path="$(mktemp "$parent_dir/.tmp.$(basename "$destination").XXXXXX")"
  cat > "$tmp_path"
  chmod 600 "$tmp_path"
  mv "$tmp_path" "$destination"
}

remove_tree() {
  local target="$1"
  "$PYTHON_BIN" - "$target" <<'PY'
from pathlib import Path
import shutil
import sys

target = Path(sys.argv[1])
try:
    shutil.rmtree(target)
except FileNotFoundError:
    pass
except Exception as exc:
    print(f"Failed to remove secret staging directory {target}: {exc}", file=sys.stderr)
    raise
PY
}

ensure_target_root_is_uninitialized() {
  if [[ ! -e "$ETC_ROOT" ]]; then
    return 0
  fi
  [[ -d "$ETC_ROOT" ]] || die "target root exists and is not a directory: $ETC_ROOT"
  if find "$ETC_ROOT" -mindepth 1 -print -quit | grep -q .; then
    die "target root is already initialized: $ETC_ROOT"
  fi
}

main() {
  [[ $# -eq 2 ]] || die "usage: bootstrap-secrets.sh <owner-username> <owner-password-file>"

  local owner_username="$1"
  local password_file="$2"
  local parent_dir
  local staging_root
  local cleanup_root
  local owner_password_hash
  local oidc_secret
  local oidc_digest
  local postgres_password
  local langfuse_postgres_password
  local neo4j_password
  local litellm_api_key
  local grafana_password
  local langfuse_salt
  local langfuse_encryption_key
  local langfuse_nextauth_secret
  local langfuse_clickhouse_password
  local langfuse_redis_password
  local langfuse_minio_password
  local langfuse_public_key
  local langfuse_secret_key
  local langfuse_init_user_password
  local service_owner_user
  local service_owner_group

  [[ -f "$password_file" ]] || die "owner password file is missing: $password_file"
  [[ ! -L "$password_file" ]] || die "owner password file must be a regular file, not a symlink: $password_file"
  [[ "$(stat_mode "$password_file")" == "600" ]] || die "owner password file must have mode 0600: $password_file"
  [[ -n "$(read_secret_file "$password_file")" ]] || die "owner password file must not be empty"

  if [[ "$ETC_ROOT" == "$DEFAULT_ETC_ROOT" && "$(id -u)" != "0" ]]; then
    die "bootstrap-secrets.sh must run as root when targeting $DEFAULT_ETC_ROOT"
  fi

  require_cmd openssl
  require_cmd install
  require_cmd mktemp
  [[ -x "$PYTHON_BIN" ]] || die "required repo python is missing or not executable: $PYTHON_BIN"
  require_python_hash_support || die "repo python must provide cryptography Argon2 support for Authelia-compatible hashes"
  ensure_target_root_is_uninitialized

  if [[ "$(id -u)" == "0" ]]; then
    id ragweld >/dev/null 2>&1 || die "service user 'ragweld' must exist before bootstrapping production secrets"
    service_owner_user="ragweld"
    service_owner_group="ragweld"
  else
    service_owner_user="$(id -un)"
    service_owner_group="$(id -gn)"
  fi

  parent_dir="$(dirname "$ETC_ROOT")"
  cleanup_root="$(mktemp -d "$parent_dir/.ragweld-bootstrap.XXXXXX")"
  trap 'remove_tree "$cleanup_root"' EXIT
  staging_root="$cleanup_root/root"
  install -d -m 0700 "$staging_root"
  install -d -m 0700 "$staging_root/authelia"
  install -d -m 0700 "$staging_root/authelia/state"

  oidc_secret="$(random_alnum 72)"
  printf '%s\n' "$oidc_secret" | write_atomic_file "$staging_root/langfuse-oidc-client-secret"
  oidc_digest="$(pbkdf2_sha512_digest "$staging_root/langfuse-oidc-client-secret")"
  printf '%s\n' "$oidc_digest" | write_atomic_file "$staging_root/authelia/langfuse-client-secret-digest"

  owner_password_hash="$(argon2id_digest "$password_file")"
  printf '%s\n' "$(random_hex 64)" | write_atomic_file "$staging_root/authelia/session-secret"
  printf '%s\n' "$(random_hex 64)" | write_atomic_file "$staging_root/authelia/storage-encryption-key"
  printf '%s\n' "$(random_hex 64)" | write_atomic_file "$staging_root/authelia/oidc-hmac-secret"
  openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$staging_root/authelia/oidc-rsa.pem" >/dev/null 2>&1
  chmod 600 "$staging_root/authelia/oidc-rsa.pem"

  postgres_password="$(random_alnum 48)"
  langfuse_postgres_password="$(random_alnum 48)"
  neo4j_password="$(random_alnum 48)"
  litellm_api_key="sk-ragweld-$(random_alnum 48)"
  grafana_password="$(random_alnum 48)"
  langfuse_salt="$(random_hex 16)"
  langfuse_encryption_key="$(random_hex 32)"
  langfuse_nextauth_secret="$(random_hex 24)"
  langfuse_clickhouse_password="$(random_alnum 32)"
  langfuse_redis_password="$(random_alnum 32)"
  langfuse_minio_password="$(random_alnum 32)"
  langfuse_public_key="pk-lf-$(random_hex 12)"
  langfuse_secret_key="sk-lf-$(random_hex 12)"
  langfuse_init_user_password="$(random_alnum 32)"

  cat <<EOF | write_atomic_file "$staging_root/runtime.env"
LITELLM_BASE_URL=http://127.0.0.1:54000/v1
LITELLM_API_KEY=$litellm_api_key
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=tribrid_rag
POSTGRES_USER=postgres
POSTGRES_PASSWORD=$postgres_password
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=$neo4j_password
SERVER_HOST=0.0.0.0
BACKEND_PORT=58012
DEBUG=false
GRAFANA_URL=http://127.0.0.1:3301
PROMETHEUS_URL=http://127.0.0.1:59090
METRICS_ENABLED=true
TRACING_ENABLED=true
RAGWELD_CONFIG_PATH=$DEFAULT_ETC_ROOT/tribrid_config.json
MODELS_DIR=/opt/ragweld/models
DATA_DIR=/opt/ragweld/data
GRAFANA_ADMIN_PASSWORD=$grafana_password
LANGFUSE_PUBLIC_KEY=$langfuse_public_key
LANGFUSE_SECRET_KEY=$langfuse_secret_key
EOF

  cat <<'EOF' | write_atomic_file "$staging_root/litellm.env"
# Provider keys are installed separately after bootstrap.
EOF

  cat <<EOF | write_atomic_file "$staging_root/langfuse.env"
LANGFUSE_POSTGRES_PASSWORD=$langfuse_postgres_password
DATABASE_URL=postgresql://langfuse:$langfuse_postgres_password@langfuse-postgres:5432/langfuse
SALT=$langfuse_salt
ENCRYPTION_KEY=$langfuse_encryption_key
NEXTAUTH_SECRET=$langfuse_nextauth_secret
TELEMETRY_ENABLED=false
CLICKHOUSE_URL=http://langfuse-clickhouse:8123
CLICKHOUSE_MIGRATION_URL=clickhouse://langfuse-clickhouse:9000
CLICKHOUSE_USER=langfuse
CLICKHOUSE_PASSWORD=$langfuse_clickhouse_password
CLICKHOUSE_CLUSTER_ENABLED=false
REDIS_HOST=langfuse-redis
REDIS_PORT=6379
REDIS_AUTH=$langfuse_redis_password
LANGFUSE_S3_EVENT_UPLOAD_BUCKET=langfuse
LANGFUSE_S3_EVENT_UPLOAD_REGION=auto
LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID=langfuse
LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY=$langfuse_minio_password
LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT=http://langfuse-minio:9000
LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE=true
LANGFUSE_INIT_ORG_ID=ragweld
LANGFUSE_INIT_ORG_NAME=Ragweld
LANGFUSE_INIT_PROJECT_ID=ragweld
LANGFUSE_INIT_PROJECT_NAME=ragweld
LANGFUSE_INIT_PROJECT_PUBLIC_KEY=$langfuse_public_key
LANGFUSE_INIT_PROJECT_SECRET_KEY=$langfuse_secret_key
LANGFUSE_INIT_USER_EMAIL=$owner_username@ragweld.local
LANGFUSE_INIT_USER_NAME=$owner_username
LANGFUSE_INIT_USER_PASSWORD=$langfuse_init_user_password
EOF

  cat <<EOF | write_atomic_file "$staging_root/authelia/users_database.yml"
users:
  $owner_username:
    displayname: $owner_username
    email: $owner_username@ragweld.local
    password: '$owner_password_hash'
    groups:
      - owners
EOF

  chmod 700 "$staging_root" "$staging_root/authelia" "$staging_root/authelia/state"
  find "$staging_root" -type f -exec chmod 600 {} +
  if [[ "$(id -u)" == "0" ]]; then
    chown -R "$service_owner_user:$service_owner_group" "$staging_root"
  fi

  if [[ -d "$ETC_ROOT" ]]; then
    rmdir "$ETC_ROOT"
  fi
  mv "$staging_root" "$ETC_ROOT"
  trap - EXIT
  rmdir "$cleanup_root"
}

main "$@"
