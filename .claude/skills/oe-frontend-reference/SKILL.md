---
name: oe-frontend-reference
description: Reference guide for the REAL frontend (Live URL + Local Code). Use this when you need to verify integration details, UI behavior, or API contracts against the actual frontend implementation.
---

# OpenEvent Frontend Reference

## Live Application
- **URL:** https://app.openevent.io/
- **Usage:** Use this to verify visual behavior, live updates, and deployment status.

## Local Codebase Reference
- **Path:** `/Users/nico/Documents/GitHub`
- **Context:** The user has indicated this path contains the reference frontend code.
- **Action:** When verifying frontend logic (e.g., "how does the frontend parse this API response?"):
  1.  List the contents of `/Users/nico/Documents/GitHub` to locate the active frontend repo (if not obvious).
  2.  Read the relevant components or API clients in that directory.

## Integration Workflow
When modifying backend APIs that affect the frontend:
1.  **Consult this Skill:** Check how the live site (`https://app.openevent.io/`) behaves.
2.  **Verify Types:** Look for TypeScript interfaces in the local code path to ensure backend responses match frontend expectations.
