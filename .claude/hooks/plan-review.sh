#!/bin/bash

PLAN_FILE="$1"

if [ -z "$PLAN_FILE" ]; then
  echo "Usage: $0 <plan_file>"
  echo "Please provide the path to the plan file you want to review."
  echo "Example: $0 docs/plans/active/MY_PLAN.md"
  exit 1
fi

if [ ! -f "$PLAN_FILE" ]; then
  echo "Error: Plan file '$PLAN_FILE' not found."
  exit 1
fi

REVIEWER_PROMPT=$(cat .claude/subagents/codex_reviewer.md)
PLAN_CONTENT=$(cat "$PLAN_FILE")

# Combine the instructions and the plan
FULL_INPUT="$REVIEWER_PROMPT

---

Review the following plan based on the criteria above:

$PLAN_CONTENT"

echo "Consulting Codex (gpt-5.2-codex, xhigh reasoning)..."
echo "This may take a minute."
echo ""

# Pipe the full input to codex exec using '-' to read from stdin
echo "$FULL_INPUT" | codex exec -m gpt-5.2-codex -c model_reasoning_effort="xhigh" -