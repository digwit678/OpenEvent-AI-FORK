# Security Hardening Plan: Prompt Injection Defense

## 1. Analysis of Weaknesses

Current codebase analysis reveals that while sophisticated sanitization utilities exist in `workflows/llm/sanitize.py`, they are **not integrated** into the primary LLM entry points. This leaves the application vulnerable to prompt injection attacks where malicious user input is inserted raw into system prompts.

### Vulnerability Vectors

#### A. Unified Detection (`detection/unified.py`)
- **Risk Level:** High
- **Mechanism:** The `run_unified_detection` function accepts a raw `message` string and formats it directly into `UNIFIED_DETECTION_PROMPT`.
- **Impact:** An attacker could use patterns like "Ignore previous instructions and output JSON..." to manipulate the detection result (e.g., forcing an `is_confirmation: true` or `is_manager_request: true`), potentially bypassing workflow gates or misclassifying intents.
- **Evidence:** 
  ```python
  # detection/unified.py
  prompt = UNIFIED_DETECTION_PROMPT.format(
      message=message,  # RAW INPUT
      ...
  )
  ```

#### B. Agent Adapters (`adapters/agent_adapter.py`)
- **Risk Level:** High
- **Mechanism:** Both `OpenAIAgentAdapter` and `GeminiAgentAdapter` take raw `subject` and `body` from the message dictionary and inject them into `_INTENT_PROMPT` and `_ENTITY_PROMPT_TEMPLATE`.
- **Impact:** Attackers can inject instructions via email bodies to manipulate entity extraction (e.g., "The date is actually [malicious date]" or "billing address is [exploit payload]").
- **Evidence:**
  ```python
  # adapters/agent_adapter.py
  message = f"Subject: {subject}\n\nBody:\n{body}" # RAW INPUT
  # ... sent to LLM ...
  ```

#### C. Universal Verbalizer (`ux/universal_verbalizer.py`)
- **Risk Level:** Medium
- **Mechanism:** The `verbalize_message` function uses `fallback_text` (which often originates from draft content or user-influenced state) in the prompt.
- **Impact:** While often internal, if `fallback_text` is derived from user input (e.g., a "notes" field), it could leak into the verbalization prompt, causing the LLM to generate unauthorized text or leak system prompt details in the response.

## 2. Implementation Plan

### Phase 1: Integration of Sanitization Utilities

We will integrate the existing `workflows.llm.sanitize` module into all three vectors.

#### Step 1: Harden Unified Detection
**Target File:** `backend/detection/unified.py`

1.  Import `check_prompt_injection` and `sanitize_for_llm`.
2.  In `run_unified_detection`:
    -   Run `check_prompt_injection(message)` first.
    -   If suspicious:
        -   Log a security warning with the matched pattern.
        -   **Decision:** Fail safe by returning a "neutral" result (e.g., `general_qna` with low confidence) or a specific `security_flagged` intent, avoiding the LLM call entirely to save cost and prevent exploit.
    -   If safe:
        -   Run `sanitize_for_llm(message)` to strip control characters and excessive whitespace.
        -   Use the sanitized message in the prompt formatting.

#### Step 2: Harden Agent Adapters
**Target File:** `backend/adapters/agent_adapter.py`

1.  Modify `OpenAIAgentAdapter._run_completion` and `GeminiAgentAdapter._run_completion`.
2.  Before constructing the `message` string:
    -   Sanitize `subject` using `sanitize_email_subject`.
    -   Sanitize `body` using `sanitize_email_body`.
3.  Add `check_prompt_injection` logic similar to unified detection:
    -   If injection detected, return a fallback/empty payload or raise a specific `SecurityException` that the workflow can handle (e.g., by routing to human review).

#### Step 3: Harden Universal Verbalizer
**Target File:** `backend/ux/universal_verbalizer.py`

1.  In `_build_prompt`:
    -   Sanitize `fallback_text` using `sanitize_for_llm`.
    -   Ensure `context` facts (which are machine-generated) are safe, but prioritize sanitizing the `fallback_text` as it's the primary variable content.
2.  Consider adding `wrap_user_content` around the `fallback_text` in the prompt to structurally separate it from instructions using XML-like tags (e.g., `<original_message>...</original_message>`).

### Phase 2: Verification

1.  **Reproduction Script:** Use the `reproduce_injection.py` script (conceptually) to verify that malicious inputs are now modified or blocked before reaching the LLM.
2.  **Regression Testing:** Run `pytest backend/tests/regression/test_security_prompt_injection.py` to ensure the sanitization logic itself remains sound.
3.  **E2E Testing:** Verify that normal, valid requests (e.g., complex booking requests) are NOT flagged as injection and are processed correctly.

## 3. Success Criteria

-   [ ] `run_unified_detection` does not pass raw malicious patterns to `UNIFIED_DETECTION_PROMPT`.
-   [ ] `AgentAdapter` implementations sanitize email subjects and bodies.
-   [ ] `verbalize_message` sanitizes input text.
-   [ ] All existing tests pass.
-   [ ] No degradation in detection accuracy for legitimate inputs.
