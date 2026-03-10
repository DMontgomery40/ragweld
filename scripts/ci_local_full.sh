#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[ci_local_full] running banned-check"
uv run scripts/check_banned.py

echo "[ci_local_full] validating generated types"
uv run scripts/validate_types.py

echo "[ci_local_full] running pytest"
uv run pytest -q

echo "[ci_local_full] running frontend lint"
npm --prefix web run lint

echo "[ci_local_full] running frontend build"
npm --prefix web run build
