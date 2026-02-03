#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL_DIR="${ROOT}/.mcp-tools/FileScopeMCP"
SERVER_PATH="${TOOL_DIR}/dist/mcp-server.js"

if [[ ! -f "${SERVER_PATH}" ]]; then
  echo "FileScopeMCP not built." >&2
  echo "Clone https://github.com/admica/FileScopeMCP into ${TOOL_DIR}, run npm install && npm run build." >&2
  exit 1
fi

node "${SERVER_PATH}" --base-dir="${ROOT}"
