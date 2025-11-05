# V4 Shortcut Policy & UX Guarantees

## Shortcut Way (capture) vs No Shortcut Way (orchestration)
- **No Shortcut Way**: Advance strictly via gates (Intake → Date → Room → Products/Offer). Shortcuts never skip gates.
- **Shortcut Way**: Eagerly capture relevant entities **out of order** and reuse at their owning step **without re-asking**, if valid and unchanged.

## Deterministic Rules
1) Eager capture (Regex → NER → LLM refine); persist with `source="shortcut"`, `captured_at_step`.
2) Validate with owning-step rules; if invalid/ambiguous, don’t persist (owning step will ask).
3) No re-ask at owning step if a valid shortcut exists and user hasn’t changed it.
4) Changes supersede prior values; recompute hashes; detour **only dependent steps**.
5) Values provided at owning step override shortcuts.
6) **UX “never left in the dark”:** Every client-facing message must include:
   - **Step**, **Next expected action**, **Wait state** (`Awaiting Client` / `Waiting on HIL`),
   - A clear continuation cue (choices or short instruction).
