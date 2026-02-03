#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL_DIR="${ROOT}/.mcp-tools/RepoMapper"
SERVER_PATH="${TOOL_DIR}/repomap_server.py"
VENV_PY="${TOOL_DIR}/.venv/bin/python"

if [[ ! -f "${SERVER_PATH}" ]]; then
  echo "RepoMapper MCP not installed." >&2
  echo "Clone https://github.com/pdavis68/RepoMapper into ${TOOL_DIR} and install its deps." >&2
  exit 1
fi

if [[ -x "${VENV_PY}" ]]; then
  "${VENV_PY}" "${SERVER_PATH}"
else
  python3 "${SERVER_PATH}"
fi
