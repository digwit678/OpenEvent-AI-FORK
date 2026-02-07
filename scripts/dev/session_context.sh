#!/usr/bin/env bash
set -euo pipefail

read_file() {
  local path="$1"
  local lines="$2"
  if [[ -f "$path" ]]; then
    echo "=== $path ==="
    sed -n "1,${lines}p" "$path"
  else
    echo "=== $path (missing) ==="
  fi
}

read_file "docs/daily_scrum/session_primer.md" 220
read_file "docs/daily_scrum/weekly_agent_pack.md" 220
read_file "DEV_CHANGELOG.md" 260
read_file "docs/guides/TEAM_GUIDE.md" 220
read_file "TO_DO_NEXT_SESS.md" 220
