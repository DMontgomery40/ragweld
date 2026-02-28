#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${REPO_ROOT}/dist"

usage() {
  cat <<'EOF'
Build a portable Codex Agent Teams bundle for other machines.

Usage:
  scripts/export_codex_agent_teams_bundle.sh [--out-dir DIR]

Output:
  <out-dir>/codex-agent-teams-<timestamp>.tar.gz
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out-dir)
      OUT_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

STAMP="$(date +%Y%m%d-%H%M%S)"
BUNDLE_NAME="codex-agent-teams-${STAMP}"
WORK_DIR="${OUT_DIR}/${BUNDLE_NAME}"
ARCHIVE_PATH="${OUT_DIR}/${BUNDLE_NAME}.tar.gz"

rm -rf "${WORK_DIR}"
mkdir -p "${WORK_DIR}"

cp -R "${REPO_ROOT}/server/team_bus" "${WORK_DIR}/team_bus"
cp "${REPO_ROOT}/scripts/install_codex_agent_teams.sh" "${WORK_DIR}/install_codex_agent_teams.sh"
cp "${REPO_ROOT}/scripts/codex_team_container.sh" "${WORK_DIR}/codex_team_container.sh"
cp "${REPO_ROOT}/scripts/codex_overlay.py" "${WORK_DIR}/codex_overlay.py"
chmod +x "${WORK_DIR}/install_codex_agent_teams.sh" "${WORK_DIR}/codex_team_container.sh"

cat > "${WORK_DIR}/README.md" <<'EOF'
# Codex Agent Teams Bundle

Install:

```bash
./install_codex_agent_teams.sh --source ./team_bus --force
~/.codex/bin/codex-team --help
```

Optional containerized mode:

```bash
./codex_team_container.sh --build --source ./team_bus list
```
EOF

mkdir -p "${OUT_DIR}"
tar -czf "${ARCHIVE_PATH}" -C "${OUT_DIR}" "${BUNDLE_NAME}"
echo "${ARCHIVE_PATH}"
