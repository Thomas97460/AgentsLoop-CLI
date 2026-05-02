#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || "${2}" != "--" ]]; then
  echo "Usage: $0 <label> -- <command> [args...]" >&2
  exit 2
fi

label="$1"
shift 2
max_lines="${QUIET_LINES:-120}"
output_file="$(mktemp)"
trap 'rm -f "$output_file"' EXIT

if "$@" >"$output_file" 2>&1; then
  printf '✓ %s\n' "$label"
  exit 0
else
  status=$?
fi

printf '✗ %s failed (exit %s)\n' "$label" "$status" >&2
printf '%s\n' "--- first ${max_lines} output lines ---" >&2
sed -n "1,${max_lines}p" "$output_file" >&2
line_count="$(wc -l < "$output_file" | tr -d ' ')"
if [[ "$line_count" -gt "$max_lines" ]]; then
  printf '%s\n' "--- output truncated: ${line_count} total lines, set QUIET_LINES to change limit ---" >&2
fi
exit "$status"
