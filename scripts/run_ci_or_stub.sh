#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
KEY_SERVICE='openevent-api-test-key'
if ! security find-generic-password -s "$KEY_SERVICE" -a "$USER" >/dev/null 2>&1; then
  if [ -n "${OPENAI_API_KEY:-}" ]; then
    security add-generic-password -a "$USER" -s "$KEY_SERVICE" -w "$OPENAI_API_KEY" -U >/dev/null 2>&1 || true
  fi
fi
LIVE=0
if security find-generic-password -s "$KEY_SERVICE" -a "$USER" >/dev/null 2>&1; then
  export OPENAI_API_KEY="$(security find-generic-password -a "$USER" -s "$KEY_SERVICE" -w)"
  if [ -n "${OPENAI_API_KEY:-}" ]; then
    if curl -sS -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $OPENAI_API_KEY" https://api.openai.com/v1/models | grep -q '^200$'; then
      LIVE=1
    fi
  fi
fi
export PYTHONPATH="$(pwd)"
rm -f tmp-integration/e2e-live-happy-path.jsonl run.log || true
if [ "$LIVE" = "1" ]; then
  export AGENT_MODE=openai
  export OPENAI_TEST_MODE=1
  export OPENAI_AGENT_MODEL=gpt-4o-mini
  export OPENAI_INTENT_MODEL=gpt-4o-mini
  export OPENAI_ENTITY_MODEL=gpt-4o-mini
  export NO_UNSOLICITED_MENUS=true
  export PRODUCT_FLOW_ENABLED=true
  export EVENT_SCOPED_UPSELL=true
  export CAPTURE_BUDGET_ON_HIL=true
  export ALLOW_AUTO_ROOM_LOCK=false
  export DISABLE_MANUAL_REVIEW_FOR_TESTS=true
  export TZ=Europe/Zurich
  pytest -q backend/tests_integration/test_room_lock_policy.py::test_no_auto_lock_when_flag_false
  pytest -q backend/tests_integration/test_room_lock_policy.py::test_explicit_lock_is_required
  pytest -q backend/tests_integration/test_offer_requires_lock.py::test_offer_not_generated_before_lock
  pytest backend/tests_integration/test_e2e_live_openai.py -m integration -vv -rA 2>&1 | tee run.log || true
  tail -n 200 tmp-integration/e2e-live-happy-path.jsonl || true
  if rg -n "FAILED|ERRORS" run.log >/dev/null 2>&1; then
    exit 1
  fi
else
  export AGENT_MODE=stub
  export OPENAI_TEST_MODE=0
  export TZ=Europe/Zurich
  pytest -q backend/tests/workflows -k "not live"
  pytest -q backend/tests -k "not e2e and not live and not integration"
fi
