#!/bin/sh
# Source this script to load the OpenEvent-AI dev environment.
# Usage: . scripts/dev/oe_env.sh

export PYTHONPATH="$(pwd -P)"
export OPENAI_API_KEY="$(security find-generic-password -a "$USER" -s 'openevent-api-test-key' -w 2>/dev/null || true)"

# Default to empathetic verbalizer (human-like UX) for development
# Set VERBALIZER_TONE=plain to disable LLM verbalization for testing
export VERBALIZER_TONE="${VERBALIZER_TONE:-empathetic}"

if [ -z "$OPENAI_API_KEY" ]; then
  echo "OpenEvent-AI env activated (PYTHONPATH=${PYTHONPATH}; OPENAI_API_KEY NOT found in Keychain 'openevent-api-test-key')" >&2
else
  echo "OpenEvent-AI env activated (PYTHONPATH=${PYTHONPATH}; OPENAI_API_KEY from Keychain 'openevent-api-test-key')" >&2
fi

