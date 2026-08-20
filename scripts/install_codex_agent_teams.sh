#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${HOME}/.codex/agent-teams"
BIN_DIR="${HOME}/.codex/bin"
SOURCE_DIR=""
FORCE=0
INSTALL_CODEX_WRAPPER=1

usage() {
  cat <<'EOF'
Install Codex Agent Teams globally under ~/.codex.

Usage:
  scripts/install_codex_agent_teams.sh [--prefix DIR] [--bin-dir DIR] [--source DIR] [--force]
                                       [--install-codex-wrapper|--skip-codex-wrapper]

Options:
  --prefix DIR   Installation root (default: ~/.codex/agent-teams)
  --bin-dir DIR  Wrapper binary directory (default: ~/.codex/bin)
  --source DIR   Source team_bus directory (default auto-detect)
  --force        Overwrite existing install
  --install-codex-wrapper  Install ~/.codex/bin/codex wrapper with Shift+Down team overlay (default)
  --skip-codex-wrapper     Do not install codex wrapper
  -h, --help     Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prefix)
      PREFIX="$2"
      shift 2
      ;;
    --bin-dir)
      BIN_DIR="$2"
      shift 2
      ;;
    --source)
      SOURCE_DIR="$2"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --install-codex-wrapper)
      INSTALL_CODEX_WRAPPER=1
      shift
      ;;
    --skip-codex-wrapper)
      INSTALL_CODEX_WRAPPER=0
      shift
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

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required for installation" >&2
  exit 1
fi

if [[ -z "${SOURCE_DIR}" ]]; then
  if [[ -d "${SCRIPT_DIR}/../server/team_bus" ]]; then
    SOURCE_DIR="${SCRIPT_DIR}/../server/team_bus"
  elif [[ -d "${SCRIPT_DIR}/team_bus" ]]; then
    SOURCE_DIR="${SCRIPT_DIR}/team_bus"
  else
    echo "Cannot auto-detect team_bus source. Use --source DIR." >&2
    exit 1
  fi
fi

if [[ ! -d "${SOURCE_DIR}" ]]; then
  echo "Source directory does not exist: ${SOURCE_DIR}" >&2
  exit 1
fi

PREFIX_PARENT="$(dirname "${PREFIX}")"
BIN_PARENT="$(dirname "${BIN_DIR}")"
mkdir -p "${PREFIX_PARENT}" "${BIN_PARENT}"
PREFIX="$(cd "${PREFIX_PARENT}" && pwd)/$(basename "${PREFIX}")"
BIN_DIR="$(cd "${BIN_PARENT}" && pwd)/$(basename "${BIN_DIR}")"

if [[ -d "${PREFIX}/lib/team_bus" && "${FORCE}" -ne 1 ]]; then
  echo "Existing install found at ${PREFIX}. Re-run with --force to overwrite." >&2
  exit 1
fi

mkdir -p "${PREFIX}/lib" "${BIN_DIR}"
rm -rf "${PREFIX}/lib/team_bus"
cp -R "${SOURCE_DIR}" "${PREFIX}/lib/team_bus"
mkdir -p "${PREFIX}/bin"

python3 -m venv "${PREFIX}/.venv"
"${PREFIX}/.venv/bin/python" -m pip install --upgrade --quiet pip
"${PREFIX}/.venv/bin/python" -m pip install --quiet "pydantic>=2.5,<3"

cat > "${BIN_DIR}/codex-team" <<EOF
#!/usr/bin/env bash
set -euo pipefail
PREFIX="${PREFIX}"
export PYTHONPATH="\${PREFIX}/lib\${PYTHONPATH:+:\${PYTHONPATH}}"
exec "\${PREFIX}/.venv/bin/python" -m team_bus.cli "\$@"
EOF
chmod +x "${BIN_DIR}/codex-team"

OVERLAY_SOURCE=""
if [[ -f "${SCRIPT_DIR}/codex_overlay.py" ]]; then
  OVERLAY_SOURCE="${SCRIPT_DIR}/codex_overlay.py"
fi

if [[ ${INSTALL_CODEX_WRAPPER} -eq 1 ]]; then
  if [[ -z "${OVERLAY_SOURCE}" ]]; then
    echo "Warning: codex overlay source not found; skipping codex wrapper install." >&2
  else
    cp "${OVERLAY_SOURCE}" "${PREFIX}/bin/codex_overlay.py"
    chmod +x "${PREFIX}/bin/codex_overlay.py"

    WRAPPER_TARGET="${BIN_DIR}/codex"
    REAL_CODEX_PATH="$(command -v codex || true)"
    if [[ "${REAL_CODEX_PATH}" == "${WRAPPER_TARGET}" && -f "${PREFIX}/real_codex_path.txt" ]]; then
      REAL_CODEX_PATH="$(cat "${PREFIX}/real_codex_path.txt")"
    fi

    if [[ -z "${REAL_CODEX_PATH}" ]]; then
      echo "Warning: unable to locate existing codex binary; skipping codex wrapper install." >&2
    else
      echo "${REAL_CODEX_PATH}" > "${PREFIX}/real_codex_path.txt"
      cat > "${WRAPPER_TARGET}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
PREFIX="${PREFIX}"
REAL_CODEX_PATH="${REAL_CODEX_PATH}"
if [[ "\${CODEX_TEAM_OVERLAY_DISABLE:-0}" == "1" ]]; then
  exec "\${REAL_CODEX_PATH}" "\$@"
fi
exec "\${PREFIX}/.venv/bin/python" "\${PREFIX}/bin/codex_overlay.py" --real-codex "\${REAL_CODEX_PATH}" -- "\$@"
EOF
      chmod +x "${WRAPPER_TARGET}"
    fi
  fi
fi

cat > "${PREFIX}/uninstall.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
rm -f "${BIN_DIR}/codex-team"
rm -f "${BIN_DIR}/codex"
rm -rf "${PREFIX}"
echo "Removed Codex Agent Teams from ${PREFIX}"
EOF
chmod +x "${PREFIX}/uninstall.sh"

echo "Installed Codex Agent Teams:"
echo "  runtime: ${PREFIX}"
echo "  binary:  ${BIN_DIR}/codex-team"
echo "  source:  ${SOURCE_DIR}"
if [[ ${INSTALL_CODEX_WRAPPER} -eq 1 ]]; then
  echo "  codex wrapper: ${BIN_DIR}/codex (Shift+Down snapshot)"
fi
echo
echo "Quick test:"
echo "  ${BIN_DIR}/codex-team list"
echo
echo "If needed, add to PATH:"
echo "  export PATH=\"${BIN_DIR}:\$PATH\""
