# Manual UX Scenario Runs E–H – 2025-10-22 22:41:36Z

## Scenario E
Late date change during negotiation (Step 5 → Step 2 detour).

| TURN | DRAFT type | STATE (step / caller / thread) | DATA (date / room / offers) | AUDIT tail |
| --- | --- | --- | --- | --- |
| 1 | manual_review | - / - / - | - / - / - | - |
| 2 | date_candidates | 2 / - / Awaiting Client Response | - / - / - | date_missing (1->2) |
| 3 | room_available | 3 / - / Awaiting Client Response | 14.11.2025 / - / - | date_confirmed (2->3) |
| 4 | room_available | 3 / - / Awaiting Client Response | 14.11.2025 / - / - | date_confirmed (2->3) |
| 5 | offer_draft | 5 / - / Awaiting Client Response | 14.11.2025 / Room B / 1:Draft | offer_generated (4->4) |
| 6 | negotiation_clarification | 5 / - / Awaiting Client Response | 14.11.2025 / Room B / 1:Draft | offer_generated (4->4) |
| 7 | offer_draft | 5 / - / Awaiting Client Response | 14.11.2025 / Room B / 1:Superseded, 2:Draft | return_to_caller (4->5) |
| 8 | negotiation_clarification | 5 / - / Awaiting Client Response | 14.11.2025 / Room B / 1:Superseded, 2:Draft | return_to_caller (4->5) |
| 9 | negotiation_clarification | 5 / - / Awaiting Client Response | 28.11.2025 / - / 1:Superseded, 2:Draft | date_confirmed (2->5) |
| 10 | room_option | 3 / 5 / Awaiting Client Response | 28.11.2025 / - / 1:Superseded, 2:Draft | requirements_updated (5->3) |
| 11 | offer_draft | 5 / - / Awaiting Client Response | 28.11.2025 / Room A / 1:Superseded, 2:Superseded, 3:Draft | return_to_caller (4->5) |
| 12 | negotiation_accept | 7 / - / In Progress | 28.11.2025 / Room A / 1:Superseded, 2:Superseded, 3:Accepted | transition_ready (6->7) |
| 13 | confirmation_final | 7 / - / In Progress | 28.11.2025 / Room A / 1:Superseded, 2:Superseded, 3:Accepted | transition_ready (6->7) |
| 14 | - | 7 / - / In Progress | 28.11.2025 / Room A / 1:Superseded, 2:Superseded, 3:Accepted | confirmation_sent (7->7) |

Validation: hil_gate ✅ confirmation_hil ✅ detours ✅ thread_fsm ✅ audit ✅ confirmation_variant ✅

## Scenario F
Room upgrade mid-negotiation (Step 5 → Step 3 detour).

| TURN | DRAFT type | STATE (step / caller / thread) | DATA (date / room / offers) | AUDIT tail |
| --- | --- | --- | --- | --- |
| 1 | manual_review | - / - / - | - / - / - | - |
| 2 | room_option | 3 / - / Awaiting Client Response | 10.12.2025 / - / - | date_updated_initial (1->3) |
| 3 | room_available | 3 / - / Awaiting Client Response | 10.12.2025 / - / - | date_updated_initial (1->3) |
| 4 | offer_draft | 5 / - / Awaiting Client Response | 10.12.2025 / Room B / 1:Draft | offer_generated (4->4) |
| 5 | negotiation_clarification | 5 / - / Awaiting Client Response | 10.12.2025 / Room B / 1:Draft | offer_generated (4->4) |
| 6 | room_option | 3 / 5 / Awaiting Client Response | 10.12.2025 / Room B / 1:Draft | requirements_updated (5->3) |
| 7 | offer_draft | 5 / - / Awaiting Client Response | 10.12.2025 / Room B / 1:Superseded, 2:Draft | return_to_caller (4->5) |
| 8 | negotiation_accept | 7 / - / In Progress | 10.12.2025 / Room B / 1:Superseded, 2:Accepted | transition_ready (6->7) |
| 9 | confirmation_question | 7 / - / Awaiting Client Response | 10.12.2025 / Room B / 1:Superseded, 2:Accepted | transition_ready (6->7) |
| 10 | confirmation_question | 7 / - / Awaiting Client Response | 10.12.2025 / Room B / 1:Superseded, 2:Accepted | transition_ready (6->7) |
| 11 | confirmation_final | 7 / - / In Progress | 10.12.2025 / Room B / 1:Superseded, 2:Accepted | transition_ready (6->7) |
| 12 | - | 7 / - / In Progress | 10.12.2025 / Room B / 1:Superseded, 2:Accepted | confirmation_sent (7->7) |

Validation: hil_gate ✅ confirmation_hil ✅ detours ✅ thread_fsm ✅ audit ✅ confirmation_variant ✅

## Scenario G
Deposit request with delayed payment.

| TURN | DRAFT type | STATE (step / caller / thread) | DATA (date / room / offers) | AUDIT tail |
| --- | --- | --- | --- | --- |
| 1 | manual_review | - / - / - | - / - / - | - |
| 2 | room_option | 3 / - / Awaiting Client Response | 05.05.2025 / - / - | date_updated_initial (1->3) |
| 3 | room_available | 3 / - / Awaiting Client Response | 05.05.2025 / - / - | date_updated_initial (1->3) |
| 4 | offer_draft | 5 / - / Awaiting Client Response | 05.05.2025 / Room A / 1:Draft | offer_generated (4->4) |
| 5 | negotiation_clarification | 5 / - / Awaiting Client Response | 05.05.2025 / Room A / 1:Draft | offer_generated (4->4) |
| 6 | negotiation_clarification | 5 / - / Awaiting Client Response | 05.05.2025 / Room A / 1:Draft | offer_generated (4->4) |
| 7 | negotiation_accept | 7 / - / In Progress | 05.05.2025 / Room A / 1:Accepted | transition_ready (6->7) |
| 8 | room_available | 3 / 7 / Awaiting Client Response | 05.05.2025 / Room A / 1:Accepted | requirements_updated (7->3) |
| 9 | offer_draft | 5 / - / Awaiting Client Response | 05.05.2025 / Room A / 1:Accepted, 2:Draft | return_to_caller (4->7) |
| 10 | negotiation_accept | 7 / - / In Progress | 05.05.2025 / Room A / 1:Accepted, 2:Accepted | transition_ready (6->7) |
| 11 | confirmation_reserve | 7 / - / Awaiting Client Response | 05.05.2025 / Room A / 1:Accepted, 2:Accepted | transition_ready (6->7) |
| 12 | - | 7 / - / Awaiting Client Response | 05.05.2025 / Room A / 1:Accepted, 2:Accepted | reserve_notified (7->7) |
| 13 | confirmation_final | 7 / - / In Progress | 05.05.2025 / Room A / 1:Accepted, 2:Accepted | reserve_notified (7->7) |
| 14 | - | 7 / - / In Progress | 05.05.2025 / Room A / 1:Accepted, 2:Accepted | confirmation_sent (7->7) |

Validation: hil_gate ✅ confirmation_hil ✅ detours ✅ thread_fsm ✅ audit ✅ confirmation_variant ✅

## Scenario H
Site visit request followed by participant increase (Step 7 → Step 3 detour).

| TURN | DRAFT type | STATE (step / caller / thread) | DATA (date / room / offers) | AUDIT tail |
| --- | --- | --- | --- | --- |
| 1 | manual_review | - / - / - | - / - / - | - |
| 2 | room_option | 3 / - / Awaiting Client Response | 18.07.2025 / - / - | date_updated_initial (1->3) |
| 3 | room_available | 3 / - / Awaiting Client Response | 18.07.2025 / - / - | date_updated_initial (1->3) |
| 4 | offer_draft | 5 / - / Awaiting Client Response | 18.07.2025 / Room B / 1:Draft | offer_generated (4->4) |
| 5 | negotiation_clarification | 5 / - / Awaiting Client Response | 18.07.2025 / Room B / 1:Draft | offer_generated (4->4) |
| 6 | negotiation_accept | 7 / - / In Progress | 18.07.2025 / Room B / 1:Accepted | transition_ready (6->7) |
| 7 | confirmation_site_visit | 7 / - / Awaiting Client Response | 18.07.2025 / Room B / 1:Accepted | transition_ready (6->7) |
| 8 | - | 7 / - / Awaiting Client Response | 18.07.2025 / Room B / 1:Accepted | site_visit_proposed (7->7) |
| 9 | room_available | 3 / 7 / Awaiting Client Response | 18.07.2025 / Room B / 1:Accepted | requirements_updated (7->3) |
| 10 | room_option | 3 / 7 / Awaiting Client Response | 18.07.2025 / Room B / 1:Accepted | requirements_updated (7->3) |
| 11 | offer_draft | 5 / - / Awaiting Client Response | 18.07.2025 / Room C / 1:Accepted, 2:Draft | return_to_caller (4->7) |
| 12 | negotiation_clarification | 5 / - / Awaiting Client Response | 18.07.2025 / Room C / 1:Accepted, 2:Draft | return_to_caller (4->7) |
| 13 | negotiation_clarification | 5 / - / Awaiting Client Response | 18.07.2025 / Room C / 1:Accepted, 2:Draft | return_to_caller (4->7) |
| 14 | negotiation_accept | 7 / - / In Progress | 18.07.2025 / Room C / 1:Accepted, 2:Accepted | transition_ready (6->7) |
| 15 | confirmation_final | 7 / - / In Progress | 18.07.2025 / Room C / 1:Accepted, 2:Accepted | transition_ready (6->7) |
| 16 | - | 7 / - / In Progress | 18.07.2025 / Room C / 1:Accepted, 2:Accepted | confirmation_sent (7->7) |

Validation: hil_gate ✅ confirmation_hil ✅ detours ✅ thread_fsm ✅ audit ✅ confirmation_variant ✅

## Findings Summary
| Scenario | HIL gate | Confirmation HIL | Detours | Thread FSM | Audit | Variant | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Scenario E | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Date change detoured to Step 2 and returned with offer v3. |
| Scenario F | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Room B upgrade generated offer v2 and cleared caller_step. |
| Scenario G | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Headcount tweak plus deposit reserve completed with deposit_paid. |
| Scenario H | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Site visit scheduled then Room C confirmed after participant increase. |

## Suggested follow-ups
- All checks passed.
