#!/usr/bin/env bash
set -euo pipefail

VMID="${RAGWELD_CAPACITY_VMID:-100}"
STATE_DIR="${RAGWELD_CAPACITY_STATE_DIR:-/var/lib/ragweld-capacity-guard}"
SENDMAIL="${RAGWELD_SENDMAIL:-/usr/sbin/sendmail}"
LOGGER="${RAGWELD_LOGGER:-/usr/bin/logger}"
TIMEOUT_BIN="${RAGWELD_TIMEOUT_BIN:-/usr/bin/timeout}"
COMMAND_TIMEOUT_SECONDS="${RAGWELD_COMMAND_TIMEOUT_SECONDS:-45}"

die() {
  printf 'ragweld-capacity-guard: %s\n' "$*" >&2
  "$LOGGER" -t ragweld-capacity-guard -- "$*" >/dev/null 2>&1 || true
  exit 1
}

is_number() {
  [[ "$1" =~ ^[0-9]+([.][0-9]+)?$ ]]
}

require_number() {
  is_number "$2" || die "$1 returned an invalid percentage"
}

run_with_timeout() {
  "$TIMEOUT_BIN" --kill-after=10s "${COMMAND_TIMEOUT_SECONDS}s" "$@"
}

journal_transition() {
  local subject="$1"
  local body="$2"

  "$LOGGER" -t ragweld-capacity-guard -- "$subject: $body" >/dev/null 2>&1 || true
}

severity_for() {
  local value="$1"
  local warning="$2"
  local critical="$3"
  local whole="${value%%.*}"

  if (( whole >= critical )); then
    printf 'critical\n'
  elif (( whole >= warning )); then
    printf 'warning\n'
  else
    printf 'ok\n'
  fi
}

resolve_alert_email() {
  if [[ -n "${RAGWELD_CAPACITY_ALERT_EMAIL:-}" ]]; then
    printf '%s\n' "$RAGWELD_CAPACITY_ALERT_EMAIL"
    return
  fi

  local pveum_json
  if ! pveum_json="$(run_with_timeout pveum user list --output-format json 2>/dev/null)"; then
    die "pveum user list failed while resolving root@pam alert email"
  fi

  local alert_email
  if ! alert_email="$(printf '%s\n' "$pveum_json" | python3 -c '
import json
import sys

try:
    rows = json.load(sys.stdin)
except Exception:
    sys.exit(1)

if not isinstance(rows, list):
    sys.exit(1)

print(next((str(row.get("email") or "") for row in rows if row.get("userid") == "root@pam"), ""))
' 2>/dev/null)"; then
    die "pveum returned malformed JSON while resolving root@pam alert email"
  fi

  printf '%s\n' "$alert_email"
}

write_state() {
  local state_file="$1"
  local severity="$2"
  local pending="${state_file}.tmp.$$"

  printf '%s\n' "$severity" > "$pending"
  chmod 0600 "$pending"
  mv -f "$pending" "$state_file"
}

send_transition() {
  local key="$1"
  local label="$2"
  local value="$3"
  local warning="$4"
  local critical="$5"
  local alert_email="$6"
  local state_file="$STATE_DIR/$key.state"
  local old_severity="unknown"
  local new_severity
  local subject
  local body
  local severity_label

  if [[ -f "$state_file" ]]; then
    old_severity="$(<"$state_file")"
  fi
  new_severity="$(severity_for "$value" "$warning" "$critical")"
  if [[ "$new_severity" == "$old_severity" ]]; then
    return 0
  fi

  if [[ "$old_severity" == "unknown" && "$new_severity" == "ok" ]]; then
    write_state "$state_file" "$new_severity"
    return 0
  fi

  if [[ "$new_severity" == "ok" ]]; then
    subject="[Ragweld][RECOVERED] pve1 $label"
    body="$label recovered to ${value}% (warning ${warning}%, critical ${critical}%)."
  else
    severity_label="$(printf '%s' "$new_severity" | tr '[:lower:]' '[:upper:]')"
    subject="[Ragweld][$severity_label] pve1 $label"
    body="$label is at ${value}% (warning ${warning}%, critical ${critical}%)."
  fi

  journal_transition "$subject" "$body"

  if ! printf 'To: %s\nSubject: %s\nContent-Type: text/plain; charset=UTF-8\n\n%s\n' \
    "$alert_email" "$subject" "$body" | "$SENDMAIL" -t; then
    "$LOGGER" -t ragweld-capacity-guard -- "notification delivery failed for $label" \
      >/dev/null 2>&1 || true
    return 1
  fi

  write_state "$state_file" "$new_severity"
}

send_probe_transition() {
  local key="$1"
  local label="$2"
  local new_state="$3"
  local alert_email="$4"
  local state_file="$STATE_DIR/$key.state"
  local old_state="unknown"
  local subject
  local body

  if [[ -f "$state_file" ]]; then
    old_state="$(<"$state_file")"
  fi
  if [[ "$new_state" == "$old_state" ]]; then
    return 0
  fi
  if [[ "$old_state" == "unknown" && "$new_state" == "ok" ]]; then
    write_state "$state_file" "$new_state"
    return 0
  fi

  if [[ "$new_state" == "ok" ]]; then
    subject="[Ragweld][RECOVERED] pve1 $label"
    body="$label is reporting capacity again."
  else
    subject="[Ragweld][WARNING] pve1 $label"
    body="$label failed; capacity visibility is incomplete until the next successful check."
  fi

  journal_transition "$subject" "$body"

  if ! printf 'To: %s\nSubject: %s\nContent-Type: text/plain; charset=UTF-8\n\n%s\n' \
    "$alert_email" "$subject" "$body" | "$SENDMAIL" -t; then
    "$LOGGER" -t ragweld-capacity-guard -- "notification delivery failed for $label" \
      >/dev/null 2>&1 || true
    return 1
  fi

  write_state "$state_file" "$new_state"
}

main() {
  [[ "$VMID" =~ ^[0-9]+$ ]] || die "RAGWELD_CAPACITY_VMID must be an integer"
  [[ -x "$SENDMAIL" ]] || die "sendmail is not executable at the configured path"
  [[ -x "$LOGGER" ]] || die "logger is not executable at the configured path"
  [[ -x "$TIMEOUT_BIN" ]] || die "timeout is not executable at the configured path"
  [[ "$COMMAND_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] \
    || die "RAGWELD_COMMAND_TIMEOUT_SECONDS must be a positive integer"

  install -d -m 0700 "$STATE_DIR"

  local alert_email
  alert_email="$(resolve_alert_email)"
  [[ "$alert_email" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$ ]] \
    || die "root@pam does not have a valid alert email"

  local guest_probe="ok"
  local guest_used="${RAGWELD_GUEST_USED_PERCENT:-}"
  if [[ -n "$guest_used" ]]; then
    require_number "guest root filesystem" "$guest_used"
  elif ! guest_used="$(run_with_timeout pct exec "$VMID" -- df --output=pcent / 2>/dev/null | tail -n 1 | tr -d ' %')" \
    || ! is_number "$guest_used"; then
    guest_probe="failed"
    guest_used=""
  fi

  local pool_probe="ok"
  local pool_data="${RAGWELD_POOL_DATA_PERCENT:-}"
  local pool_meta="${RAGWELD_POOL_META_PERCENT:-}"
  local pool_output=""
  if [[ -n "$pool_data" || -n "$pool_meta" ]]; then
    [[ -n "$pool_data" && -n "$pool_meta" ]] \
      || die "pool data and metadata overrides must be provided together"
    require_number "pve/data data" "$pool_data"
    require_number "pve/data metadata" "$pool_meta"
  elif ! pool_output="$(
    run_with_timeout lvs --noheadings -o data_percent,metadata_percent pve/data 2>/dev/null
  )"; then
    pool_probe="failed"
    pool_data=""
    pool_meta=""
  elif ! read -r pool_data pool_meta <<<"$pool_output" || ! is_number "$pool_data" || ! is_number "$pool_meta"; then
    pool_probe="failed"
    pool_data=""
    pool_meta=""
  fi

  local status=0
  send_probe_transition guest_probe "guest storage probe" "$guest_probe" "$alert_email" || status=1
  send_probe_transition pool_probe "pve/data storage probe" "$pool_probe" "$alert_email" || status=1
  if [[ "$guest_probe" == "ok" ]]; then
    send_transition guest_root "guest root filesystem" "$guest_used" 75 90 "$alert_email" || status=1
  fi
  if [[ "$pool_probe" == "ok" ]]; then
    send_transition pool_data "pve/data data" "$pool_data" 70 85 "$alert_email" || status=1
    send_transition pool_meta "pve/data metadata" "$pool_meta" 70 85 "$alert_email" || status=1
  fi
  return "$status"
}

main "$@"
