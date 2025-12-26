#!/bin/bash
# Test script for verifying detour fixes
# Created to avoid repeated manual confirmation of API tests

set -e

API_BASE="http://localhost:8000/api"
EMAIL_PREFIX="detour-fix-test"
TIMESTAMP=$(date +%s)

echo "=============================================="
echo "Detour Fix Verification Tests"
echo "=============================================="
echo ""

# Utility function for API calls
api_call() {
    local endpoint="$1"
    local data="$2"
    curl -s -X POST "${API_BASE}/${endpoint}" \
        -H "Content-Type: application/json" \
        -d "$data"
}

# Test 1: Verify time/date parsing fix
test_time_parsing() {
    echo "=== Test 1: Time/Date Parsing Fix ==="
    local email="${EMAIL_PREFIX}-time-${TIMESTAMP}@example.com"

    local resp=$(api_call "start-conversation" "{
        \"email_body\": \"We need a room for 30 people on 07.02.2026. Projector needed.\",
        \"client_email\": \"${email}\"
    }")

    local start_time=$(echo "$resp" | tr '\n\r\t' '   ' | python3 -c "
import sys, json
try:
    d = json.loads(sys.stdin.read())
    print(d.get('event_info', {}).get('start_time', 'NOT_FOUND'))
except:
    print('PARSE_ERROR')
")

    if [[ "$start_time" == "07:02" ]]; then
        echo "FAIL: Date 07.02 is still being parsed as time 07:02"
        return 1
    elif [[ "$start_time" == "Not specified" ]] || [[ "$start_time" == "NOT_FOUND" ]]; then
        echo "PASS: Date is no longer parsed as time"
        return 0
    else
        echo "INFO: Extracted time: $start_time"
        return 0
    fi
}

# Test 2: Requirements change from Step 4
test_requirements_change() {
    echo ""
    echo "=== Test 2: Requirements Change Detour ==="
    local email="${EMAIL_PREFIX}-req-${TIMESTAMP}@example.com"

    # Step 1: Initial request
    echo "Step 1: Initial request (30 people)..."
    local resp1=$(api_call "start-conversation" "{
        \"email_body\": \"We need a room for 30 people on 08.02.2026. Projector needed.\",
        \"client_email\": \"${email}\"
    }")
    local session=$(echo "$resp1" | tr '\n\r\t' '   ' | python3 -c "
import sys, json
try:
    d = json.loads(sys.stdin.read())
    print(d.get('session_id', ''))
except:
    print('')
")

    if [[ -z "$session" ]]; then
        echo "FAIL: Could not get session ID"
        return 1
    fi
    echo "Session: $session"

    # Step 2: Select room
    echo "Step 2: Selecting Room B..."
    local resp2=$(api_call "send-message" "{
        \"session_id\": \"${session}\",
        \"message\": \"Room B please\"
    }")

    # Step 3: No extras, get offer
    echo "Step 3: Getting offer..."
    local resp3=$(api_call "send-message" "{
        \"session_id\": \"${session}\",
        \"message\": \"No extras, send the offer\"
    }")

    # Step 4: Requirements change
    echo "Step 4: Changing to 50 people..."
    local resp4=$(api_call "send-message" "{
        \"session_id\": \"${session}\",
        \"message\": \"Actually we will have 50 people instead of 30\"
    }")

    # Check the response
    local response_text=$(echo "$resp4" | tr '\n\r\t' '   ' | python3 -c "
import sys, json
try:
    d = json.loads(sys.stdin.read())
    print(d.get('response', '')[:500])
except Exception as e:
    print(f'PARSE_ERROR: {e}')
")

    echo "Response preview: ${response_text:0:200}..."

    # Check for date corruption
    if echo "$response_text" | grep -qi "dec 2025\|december 2025\|24.*dec"; then
        echo "FAIL: Date corruption detected - showing Dec 2025 instead of Feb 2026"
        return 1
    elif echo "$response_text" | grep -qi "fallback"; then
        echo "FAIL: Fallback message detected"
        return 1
    elif echo "$response_text" | grep -qi "room\|capacity\|50\|people"; then
        echo "PASS: Response mentions room/capacity, no date corruption"
        return 0
    else
        echo "INFO: Unexpected response, manual review needed"
        return 0
    fi
}

# Run tests
echo "Starting tests..."
echo ""

PASSED=0
FAILED=0

if test_time_parsing; then
    ((PASSED++))
else
    ((FAILED++))
fi

if test_requirements_change; then
    ((PASSED++))
else
    ((FAILED++))
fi

echo ""
echo "=============================================="
echo "Results: $PASSED passed, $FAILED failed"
echo "=============================================="

if [[ $FAILED -gt 0 ]]; then
    exit 1
fi
exit 0
