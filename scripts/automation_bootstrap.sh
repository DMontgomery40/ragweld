#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

artifact_ts="$(date -u +%Y%m%dT%H%M%SZ)"
artifact_dir="$ROOT_DIR/output/automation/bootstrap/$artifact_ts"
latest_path="$ROOT_DIR/output/automation/bootstrap/latest.json"
mkdir -p "$artifact_dir"

CORPUS_ID="${CORPUS_ID:-epstein-files-1}"
UI_BASE="${UI_BASE:-http://127.0.0.1:5173}"
API_BASE="${API_BASE:-http://127.0.0.1:8012/api}"

ui_url_web="${UI_BASE}/web/rag?subtab=synthetic&corpus=${CORPUS_ID}"
ui_url_root="${UI_BASE}/rag?subtab=synthetic&corpus=${CORPUS_ID}"
api_url="${API_BASE}/health"

ui_web_http_code="$(curl -sS -o "$artifact_dir/ui_probe_web.html" -w "%{http_code}" "$ui_url_web" || echo "000")"
ui_root_http_code="$(curl -sS -o "$artifact_dir/ui_probe_root.html" -w "%{http_code}" "$ui_url_root" || echo "000")"
api_http_code="$(curl -sS -o "$artifact_dir/api_health.json" -w "%{http_code}" "$api_url" || echo "000")"

status="passed"
ui_ok=0
if [ "$ui_web_http_code" != "000" ] && [ "$ui_web_http_code" != "404" ]; then
  ui_ok=1
fi
if [ "$ui_root_http_code" != "000" ] && [ "$ui_root_http_code" != "404" ]; then
  ui_ok=1
fi
if [ "$ui_ok" -ne 1 ] || [ "$api_http_code" = "000" ] || [ "$api_http_code" = "404" ]; then
  status="failed"
fi

python3 - "$artifact_dir/summary.json" "$artifact_ts" "$status" "$ui_web_http_code" "$ui_root_http_code" "$api_http_code" "$ui_url_web" "$ui_url_root" "$api_url" <<'PY'
import json
import sys
from datetime import datetime, timezone

out_path, started_at, status, ui_web_code, ui_root_code, api_code, ui_web_url, ui_root_url, api_url = sys.argv[1:10]
payload = {
    "started_at": started_at,
    "completed_at": datetime.now(timezone.utc).isoformat(),
    "status": status,
    "ui_probe_web": {"url": ui_web_url, "http_code": int(ui_web_code)},
    "ui_probe_root": {"url": ui_root_url, "http_code": int(ui_root_code)},
    "api_probe": {"url": api_url, "http_code": int(api_code)},
}
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2)
    fh.write("\n")
PY

cp "$artifact_dir/summary.json" "$latest_path"
cat "$artifact_dir/summary.json"
if [ "$status" != "passed" ]; then
  exit 1
fi
