#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

artifact_ts="$(date -u +%Y%m%dT%H%M%SZ)"
artifact_dir="$ROOT_DIR/output/automation/acceptance/$artifact_ts"
latest_path="$ROOT_DIR/output/automation/acceptance/latest.json"
mkdir -p "$artifact_dir"

export CORPUS_ID="${CORPUS_ID:-epstein-files-1}"
default_ui_base="http://127.0.0.1:5173/web"
default_api_base="http://127.0.0.1:8012/api"
bootstrap_latest="$ROOT_DIR/output/automation/bootstrap/latest.json"
bootstrap_status=""

if [ -f "$bootstrap_latest" ]; then
  bootstrap_defaults="$(
    python3 - "$bootstrap_latest" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], "r", encoding="utf-8"))
print(str(data.get("status") or "").strip())
ui = str(data.get("ui_base") or "").strip()
api = str(data.get("api_base") or "").strip()
print(ui)
print(api)
PY
  )"
  bootstrap_status="$(printf '%s\n' "$bootstrap_defaults" | sed -n '1p')"
  bootstrap_ui_base="$(printf '%s\n' "$bootstrap_defaults" | sed -n '2p')"
  bootstrap_api_base="$(printf '%s\n' "$bootstrap_defaults" | sed -n '3p')"
else
  bootstrap_ui_base=""
  bootstrap_api_base=""
fi

resolved_ui_base="${UI_BASE:-}"
resolved_api_base="${API_BASE:-}"

if [ -z "$resolved_ui_base" ] && [ "$bootstrap_status" = "passed" ] && [ -n "$bootstrap_ui_base" ]; then
  resolved_ui_base="$bootstrap_ui_base"
fi
if [ -z "$resolved_api_base" ] && [ "$bootstrap_status" = "passed" ] && [ -n "$bootstrap_api_base" ]; then
  resolved_api_base="$bootstrap_api_base"
fi

export API_BASE="$resolved_api_base"
export UI_BASE="$resolved_ui_base"

probe_synthetic_route() {
  local base="$1"
  local code
  code="$(curl -sS -o /dev/null -w "%{http_code}" "${base}/rag?subtab=synthetic&corpus=${CORPUS_ID}" || echo "000")"
  if [ "$code" = "000" ] || [ "$code" = "404" ]; then
    return 1
  fi
  return 0
}

if [ -n "$UI_BASE" ] && [ "$UI_BASE" = "$default_ui_base" ] && ! probe_synthetic_route "$UI_BASE"; then
  fallback_ui_base="http://127.0.0.1:5173"
  if probe_synthetic_route "$fallback_ui_base"; then
    export UI_BASE="$fallback_ui_base"
  fi
fi

runner_exit=1
acceptance_status="failed"
failure_reason=""
latest_summary_path=""

if [ -z "$UI_BASE" ] || [ -z "$API_BASE" ]; then
  failure_reason="bootstrap_stack_unavailable"
elif [ "$bootstrap_status" != "passed" ] && [ -z "${UI_BASE:-}" ] && [ -z "${API_BASE:-}" ]; then
  failure_reason="bootstrap_not_passed"
fi

echo "[acceptance_epstein] corpus=${CORPUS_ID}"
echo "[acceptance_epstein] ui=${UI_BASE}"
echo "[acceptance_epstein] api=${API_BASE}"

log_path="$artifact_dir/runner.log"
if [ -z "$failure_reason" ]; then
  set +e
  npm --prefix web exec -- node "$ROOT_DIR/web/tmp_synthetic_acceptance.mjs" | tee "$log_path"
  runner_exit="${PIPESTATUS[0]}"
  set -e

  latest_summary_path="$(ls -dt "$ROOT_DIR"/tmp/synthetic_acceptance_*/summary.json 2>/dev/null | head -n 1 || true)"
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
  if [ "$acceptance_status" = "completed" ]; then
    acceptance_status="passed"
  fi
  if [ "$runner_exit" -ne 0 ]; then
    acceptance_status="failed"
  fi
else
  printf '%s\n' "bootstrap_latest=${bootstrap_latest}" >"$log_path"
  printf '%s\n' "bootstrap_status=${bootstrap_status:-missing}" >>"$log_path"
  printf '%s\n' "failure_reason=${failure_reason}" >>"$log_path"
fi

python3 - "$artifact_dir/summary.json" "$artifact_ts" "$acceptance_status" "$runner_exit" "$latest_summary_path" "$UI_BASE" "$API_BASE" "$CORPUS_ID" "$failure_reason" "$bootstrap_status" <<'PY'
import json
import sys
from datetime import datetime, timezone

out_path, started_at, status, exit_code, acceptance_summary, ui_base, api_base, corpus_id, failure_reason, bootstrap_status = sys.argv[1:11]
payload = {
    "started_at": started_at,
    "completed_at": datetime.now(timezone.utc).isoformat(),
    "status": status,
    "runner_exit_code": int(exit_code),
    "acceptance_summary_path": acceptance_summary or None,
    "ui_base": ui_base,
    "api_base": api_base,
    "corpus_id": corpus_id,
    "failure_reason": failure_reason or None,
    "bootstrap_status": bootstrap_status or None,
}
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2)
    fh.write("\n")
PY

cp "$artifact_dir/summary.json" "$latest_path"
if [ "$acceptance_status" != "passed" ]; then
  exit 1
fi
