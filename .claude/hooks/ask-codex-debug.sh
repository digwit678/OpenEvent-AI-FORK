#!/bin/bash

# Debug Expert Hook (Codex gpt-5.2-codex xhigh)
# Usage: 
#   ./ask-codex-debug.sh "I'm stuck on this error..."
#   ./ask-codex-debug.sh /path/to/error_log.txt

INPUT="$1"

SYSTEM_INSTRUCTION="You are a Principal Software Engineer (Debug Expert). The current agent has failed to fix this bug twice. Your goal is NOT just to suggest a fix, but to find the *Root Cause* which might be architectural or hidden in edge cases. Analyze the code, run tests if necessary (you are in the same environment), and explain why previous attempts likely failed."

echo "🤔 Calling Codex Debug Expert (gpt-5.2-codex, xhigh)..."
echo "-----------------------------------------------------"

if [ -f "$INPUT" ]; then
    # Input is a file, pipe it in with the instruction
    (echo "$SYSTEM_INSTRUCTION"; echo "---"; cat "$INPUT") | codex exec -m gpt-5.2-codex -c model_reasoning_effort="xhigh" -
elif [ -n "$INPUT" ]; then
    # Input is a string
    codex exec -m gpt-5.2-codex -c model_reasoning_effort="xhigh" "$SYSTEM_INSTRUCTION Context: $INPUT"
else
    # No input, just start the session
    codex exec -m gpt-5.2-codex -c model_reasoning_effort="xhigh" "$SYSTEM_INSTRUCTION. Please analyze the current git diff and test status to diagnose the issue."
fi
