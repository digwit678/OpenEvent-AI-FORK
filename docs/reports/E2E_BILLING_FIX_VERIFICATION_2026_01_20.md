# E2E Scenario Report: Billing Company Name Fix Verification

**Date:** 2026-01-20
**Status:** PASSED
**Test Type:** Full workflow E2E via Playwright
**Fix Verified:** `21ddf3f` - Billing address company name field mismatch

## Bug Summary

**Problem:** When capturing billing address, the company name was not appearing in the billing display. Instead, the city name "Zurich" was duplicated at the start.

**Root Cause:** LLM schema used `"company"` field but code expected `"name_or_company"`, causing the company name to be lost during capture.

**Before Fix:**
```
Input:  "TechCorp AG, Limmatstrasse 100, 8005 Zurich, Switzerland"
Output: "Zurich, Limmatstrasse 100, 8005 Zurich, Switzerland"  ✗
         ^^^^^                          ^^^^^^
         City duplicated, company name lost
```

**After Fix:**
```
Input:  "TechCorp AG, Limmatstrasse 100, 8005 Zurich, Switzerland"
Output: "TechCorp AG, Limmatstrasse 100, 8005 Zurich, Switzerland"  ✓
         ^^^^^^^^^^^
         Company name correctly displayed
```

## Test Steps and Results

### Step 1: Initial Inquiry with Parking Q&A
**Client Message:** "Hi, I'd like to book a room for a corporate workshop on May 15, 2026 with 30 attendees. Do you have parking available?"

**Result:** PASSED
- Room availability shown (Room A, B, C, F)
- Parking Q&A answered (Europaallee underground parking)

### Step 2: Room Selection
**Client Messages:**
1. "14:00-18:00 works for us. Room A sounds perfect for our needs."
2. "Let's go with Room C then. May 15, 2026 from 14:00-18:00 please."

**Result:** PASSED
- Room C selected
- Offer generated: CHF 850.00 (Room: 500 + Valet: 350)

### Step 3: Billing Address Capture (KEY TEST)
**Client Message:** "The billing address should be: TechCorp AG, Limmatstrasse 100, 8005 Zurich, Switzerland"

**Expected:** Company name "TechCorp AG" at start of billing address
**Actual:** PASSED ✓

**Verified in UI:**
- Client line: `"Client: Client (GUI) · TechCorp AG"`
- Billing address: `"Billing address: TechCorp AG, Limmatstrasse 100, 8005 Zurich, Switzerland"`

## Fix Details

### Files Modified

1. **`detection/unified.py:186`** - Updated LLM prompt schema
   ```python
   # Before:
   "billing_address": {{"company": "", "street": "", ...}}

   # After:
   "billing_address": {{"name_or_company": "", "street": "", ...}}
   ```

2. **`workflows/common/billing_capture.py:207-209`** - Added defensive normalization
   ```python
   # Normalize field aliases: LLM might return "company" instead of "name_or_company"
   if "company" in billing_data and "name_or_company" not in billing_data:
       billing_data["name_or_company"] = billing_data.pop("company")
   ```

### Commit
```
21ddf3f fix: billing address company name field mismatch
```

## Test Configuration

- **Frontend:** http://localhost:3000 (restored from origin/development-branch)
- **Backend:** Hybrid mode (I:gem, E:gem, V:ope)
- **Port 8000:** Backend API

## Screenshots

- `e2e_billing_fix_verified.png` - Full conversation view
- `e2e_billing_fix_company_name_correct.png` - Billing address with correct company name

## Conclusion

The billing address company name fix is **verified working** in the E2E flow:
- LLM now extracts company name to `name_or_company` field
- Defensive normalization handles legacy `company` field if LLM uses old format
- Billing display correctly shows company name at the start of the address

No regressions detected. The fix prevents the "Zurich, ..., Zurich" duplicate city bug.
