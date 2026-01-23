---
name: oe-codex-debug-expert
description: Invokes Codex (gpt-5.2-codex, xhigh reasoning) to diagnose complex bugs. Use this when you have failed to fix a bug twice or are stuck on a "tricky" logical contradiction.
---

# Codex Debug Expert

This skill calls in a "Senior Principal" agent (Codex running `gpt-5.2-codex` with `xhigh` reasoning) to analyze the situation. 

## When to use (The 2-Strike Rule)

You **MUST** use this skill if:
1.  You have attempted to fix a specific bug **2 times** and tests are still failing.
2.  You encounter an error that seems "impossible" or contradicts the code you see.
3.  You suspect a deep architectural issue or feature interference (e.g., Detour vs. Q&A).

## Usage

```bash
# Option 1: Pass a description of the problem
./.claude/hooks/ask-codex-debug.sh "Tests in step4_handler are failing with DetourError even though I added the check."

# Option 2: Pass a file containing the error log / traceback (Recommended)
./.claude/hooks/ask-codex-debug.sh /tmp/error_log.txt

# Option 3: Run without args (Codex will analyze git diff & run tests itself)
./.claude/hooks/ask-codex-debug.sh
```

## Output
Codex will output a diagnosis and potentially a patch. Read its response carefully. It typically finds:
- Hidden edge cases.
- Incorrect assumptions about library behavior.
- "Feature Interference" (Rule 1 violations in CLAUDE.md).
