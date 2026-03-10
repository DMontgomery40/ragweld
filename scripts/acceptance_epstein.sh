#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

artifact_ts="$(date -u +%Y%m%dT%H%M%SZ)"
artifact_dir="$ROOT_DIR/output/automation/acceptance/$artifact_ts"
latest_path="$ROOT_DIR/output/automation/acceptance/latest.json"
mkdir -p "$artifact_dir"

export CORPUS_ID="${CORPUS_ID:-epstein-files-1}"
export API_BASE="${API_BASE:-http://127.0.0.1:8012/api}"
default_ui_base="http://127.0.0.1:5173/web"
export UI_BASE="${UI_BASE:-$default_ui_base}"

probe_synthetic_route() {
  local base="$1"
  local code
  code="$(curl -sS -o /dev/null -w "%{http_code}" "${base}/rag?subtab=synthetic&corpus=${CORPUS_ID}" || echo "000")"
  if [ "$code" = "000" ] || [ "$code" = "404" ]; then
    return 1
  fi
  return 0
}

if [ "$UI_BASE" = "$default_ui_base" ] && ! probe_synthetic_route "$UI_BASE"; then
  fallback_ui_base="http://127.0.0.1:5173"
  if probe_synthetic_route "$fallback_ui_base"; then
    export UI_BASE="$fallback_ui_base"
  fi
fi

echo "[acceptance_epstein] corpus=${CORPUS_ID}"
echo "[acceptance_epstein] ui=${UI_BASE}"
echo "[acceptance_epstein] api=${API_BASE}"

log_path="$artifact_dir/runner.log"
set +e
npm --prefix web exec -- node "$ROOT_DIR/web/tmp_synthetic_acceptance.mjs" | tee "$log_path"
runner_exit="${PIPESTATUS[0]}"
set -e

latest_summary_path="$(ls -dt "$ROOT_DIR"/tmp/synthetic_acceptance_*/summary.json 2>/dev/null | head -n 1 || true)"
acceptance_status="failed"
if [ -n "$latest_summary_path" ] && [ -f "$latest_summary_path" ]; then
  parsed_status="$(python3 - "$latest_summary_path" <<'PY'
import json
import sys
try:
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        data = json.load(fh)
    print(data.get("acceptance_status", "failed"))
except Exception:
    print("failed")
PY
)"
  acceptance_status="${parsed_status:-failed}"
fi
if [ "$runner_exit" -ne 0 ]; then
  acceptance_status="failed"
fi

python3 - "$artifact_dir/summary.json" "$artifact_ts" "$acceptance_status" "$runner_exit" "$latest_summary_path" "$UI_BASE" "$API_BASE" "$CORPUS_ID" <<'PY'
import json
import sys
from datetime import datetime, timezone

out_path, started_at, status, exit_code, acceptance_summary, ui_base, api_base, corpus_id = sys.argv[1:9]
payload = {
    "started_at": started_at,
    "completed_at": datetime.now(timezone.utc).isoformat(),
    "status": status,
    "runner_exit_code": int(exit_code),
    "acceptance_summary_path": acceptance_summary or None,
    "ui_base": ui_base,
    "api_base": api_base,
    "corpus_id": corpus_id,
}
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2)
    fh.write("\n")
PY

cp "$artifact_dir/summary.json" "$latest_path"
if [ "$acceptance_status" != "passed" ]; then
  exit 1
fi
