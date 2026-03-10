#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export CORPUS_ID="${CORPUS_ID:-epstein-files-1}"
export UI_BASE="${UI_BASE:-http://127.0.0.1:5173/web}"
export API_BASE="${API_BASE:-http://127.0.0.1:8012/api}"

echo "[acceptance_epstein] corpus=${CORPUS_ID}"
echo "[acceptance_epstein] ui=${UI_BASE}"
echo "[acceptance_epstein] api=${API_BASE}"

npm --prefix web exec -- node "$ROOT_DIR/web/tmp_synthetic_acceptance.mjs"
