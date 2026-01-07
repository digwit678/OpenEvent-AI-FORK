# TODO: Next Testing Session

## Issues from Dec 24 E2E Testing

### ✅ 1. Date Year Extraction Bug (FIXED - Dec 25)
- ~~Natural language dates like "December 10, 2026" sometimes extract as **2025**~~
- ~~"Late spring 2026" extracted as December **2025** (completely wrong)~~
- **Fix:** Added `Today is {today}` to LLM entity extraction prompt in `agent_adapter.py`
- Also added missing `analyze_message()` method to `OpenAIAgentAdapter`
- Commit: `d8d7566`

### ✅ 2. Combined Accept + Billing Not Captured (FIXED - Dec 25)
- ~~Message "Yes, I accept. Billing: [address]" doesn't capture billing~~
- **Fix:** Now captures `billing_address` from `user_info` before calling `_refresh_billing` in step5 handler
- This enables single-message acceptance with billing ("Yes, I accept. Billing: Company, Street, City")
- Commit: `d8d7566`

### ✅ 3. Gate Debug Prints (FIXED - Dec 25)
- Wrapped debug prints in `step5_handler.py` and `domain/models.py` with `WF_DEBUG` flag
- Set `WF_DEBUG_STATE=1` to enable verbose debug output
- Reduces log noise in production
- Commit: `d8d7566`

### 4. Fallback Error in Test 5 (Low Priority)
- Initial "June 11-12, 2026" triggered `[FALLBACK: api.routes.messages.send_message]`
- Action was `room_detour_capacity` with `draft_count=0`
- **Action:** Debug why this caused empty workflow reply

## Tests NOT Yet Verified

### Q&A Flow Testing
- [ ] General questions (e.g., "What are your opening hours?") from every step of the workflow 
- [ ] Catering-specific questions
- [ ] Room capacity questions mid-flow
- [ ] Pricing questions during negotiation

### Shortcut Testing
- [ ] Direct room selection shortcuts
- [ ] Date shortcuts with calendar integration
- [ ] Product shortcut additions

### Edge Cases
- [ ] Multi-language input (German/English mix)
- [ ] Very long email bodies
- [ ] Special characters in billing address
- [ ] Multiple date options in single email

## Tests That Passed (6/6 reached site visit)

1. Team Strategy Workshop (December 2026) - with retry
2. Product Launch Presentation (March 2026) - clean
3. Team Offsite (Late Spring 2026) - wrong date extracted but flow worked
4. Networking Evening (May 8, 2026) - clean, 3 products matched
5. Two-Day Training (June 11-12, 2026) - needed retry with explicit format
6. Private Dinner (February 2026) - clean, "closest" verified working

## Quick Commands for Next Session

```bash
# Start backend
./scripts/dev/dev_server.sh

# Run detection tests
pytest backend/tests/detection/ -v

# Run regression tests
pytest backend/tests/regression/ -v
```
