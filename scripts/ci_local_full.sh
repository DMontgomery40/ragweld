#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[ci_local_full] running Jev semantic lint"
python3 scripts/jev_lint.py

echo "[ci_local_full] checking contract integrity"
uv run scripts/check_contract_integrity.py

echo "[ci_local_full] validating generated types"
uv run scripts/validate_types.py

echo "[ci_local_full] running pytest"
uv run pytest -q

echo "[ci_local_full] running frontend typecheck"
npm --prefix web run typecheck

echo "[ci_local_full] running frontend build"
npm --prefix web run build
