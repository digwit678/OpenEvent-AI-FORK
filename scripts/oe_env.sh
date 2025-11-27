#!/bin/sh
# Source this script to load the OpenEvent-AI dev environment.
# Usage: . scripts/oe_env.sh

#!/bin/s/

export PYTHONPATH="$(pwd -P)"
export OPENAI_API_KEY="$(security find-generic-password -a "$USER" -s 'openevent-api-test-key' -w 2>/dev/null || true)"

if [ -z "$OPENAI_API_KEY" ]; then
  echo "OpenEvent-AI env activated (PYTHONPATH=${PYTHONPATH}; OPENAI_API_KEY NOT found in Keychain 'openevent-api-test-key')" >&2
else
  echo "OpenEvent-AI env activated (PYTHONPATH=${PYTHONPATH}; OPENAI_API_KEY from Keychain 'openevent-api-test-key')" >&2
fi

