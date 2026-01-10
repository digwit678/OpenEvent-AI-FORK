#!/bin/bash
# Load diverse test data for development/testing
# Usage: ./scripts/load_test_data.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if [ -f "$ROOT_DIR/data/events_database.seed.json" ]; then
    cp "$ROOT_DIR/data/events_database.seed.json" "$ROOT_DIR/events_database.json"
    echo "Loaded test data from data/events_database.seed.json"
    echo "Contains: $(python3 -c "import json; d=json.load(open('$ROOT_DIR/events_database.json')); print(f'{len(d[\"events\"])} events, {len(d[\"clients\"])} clients, {len(d[\"hil_tasks\"])} HIL tasks')")"
else
    echo "Error: data/events_database.seed.json not found"
    exit 1
fi
