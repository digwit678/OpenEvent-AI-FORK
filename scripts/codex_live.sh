set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
export PYTHONPATH="$(pwd)"
export OPENAI_API_KEY="$(security find-generic-password -a "$USER" -s 'openevent-api-test-key' -w)"
[ -n "$OPENAI_API_KEY" ]
rm -f tmp-integration/e2e-live-happy-path.jsonl run.log
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
pytest backend/tests_integration/test_e2e_live_openai.py -m integration -vv -rA 2>&1 | tee run.log
tail -n 200 tmp-integration/e2e-live-happy-path.jsonl || true
