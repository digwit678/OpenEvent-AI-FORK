# To-Do Next Session

This file tracks active implementation goals and planned roadmap items. **Check this file at the start of every session.**

## 🎯 Primary Focus for Tomorrow
1.  **Finalize Phase 1 Stability:** Ensure all 7 steps pass happy-path and edge-case regression tests.
2.  **Begin Database Consolidation:** Execute the merger of redundant JSON data files.
3.  **Initiate Gemini Strategy:** Start implementing the dual-engine LLM provider.

---

## 1. Active Implementation Phase (Current Session / Immediate)
*Must be stabilized before moving to full roadmap implementation.*

| Date Identified | Task | Goal | Priority |
| :--- | :--- | :--- | :--- |
| 2025-12-24 | **System Resilience** | Handle diverse client inputs (languages, edge cases) | **Urgent** |
| 2025-12-24 | **Production Stability** | Verified via zero-failure regression runs | **Urgent** |
| 2025-12-24 | **Circular Bug Elimination** | Audit routing loops and special flow guards | **Urgent** |
| 2025-12-24 | **Integration Completion** | Supabase/Hostinger production readiness | **High** |
| 2025-12-24 | **Billing Flow Robustness** | Frontend/Backend session sync stability | **High** |
| 2025-12-27 | **Product Change Mid-Flow** | Adding catering after room selection triggers `change_detour` with no draft (fallback). Step4 line 353 returns `halt=False` but detour target doesn't produce response. | **Medium** |
| 2025-12-27 | **Billing Address Capture Failure** | When billing address provided ("Billing address: X"), it's not parsed into `billing_details`. Event reverts to step 3, deposit button fails. LLM extraction may not be recognizing the format. | **High** |

---

## 2. Planned Roadmap (Pending Implementations)
*Detailed plans located in `docs/plans/`.*

| Date Added | Task / Plan | Reference | Priority |
| :--- | :--- | :--- | :--- |
| 2025-12-24 | **Database Consolidation** | `docs/plans/DATABASE_CONSOLIDATION_PLAN.md` | Medium |
| 2025-12-22 | **Dual-Engine (Gemini)** | `docs/plans/MIGRATION_TO_GEMINI_STRATEGY.md` | Medium |
| 2025-12-20 | **Detection Improvement** | `docs/plans/DETECTION_IMPROVEMENT_PLAN.md` | Medium |
| 2025-12-18 | **Multi-Variable Q&A** | `docs/plans/MULTI_VARIABLE_QNA_PLAN.md` | Medium |
| 2025-12-15 | **Site Visit Sub-flow** | `docs/plans/site_visit_implementation_plan.md` | Medium |
| 2025-12-12 | **Junior Dev Links** | `docs/plans/JUNIOR_DEV_LINKS_IMPLEMENTATION_GUIDE.md` | Low |
| 2025-12-10 | **Multi-Tenant Expansion** | `docs/plans/MULTI_TENANT_EXPANSION_PLAN.md` | Low |
| 2025-12-08 | **Test Pages/Links** | `docs/plans/test_pages_and_links_integration.md` | Low |
| 2025-12-05 | **Pseudo-links Calendar** | `docs/plans/pseudolinks_calendar_integration.md` | Low |
| 2025-12-01 | **Hostinger Logic Update** | `docs/plans/HOSTINGER_UPDATE_PLAN.md` | Medium |
