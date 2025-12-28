# Manual UX Scenario Runs I–J – 2025-10-23 00:17:27Z

## Scenario I
Site visit requested before confirmation; slots proposed, scheduled, and booking finalized.

| TURN | DRAFT type | STATE (step / caller / thread) | DATA (date / room / offers) | AUDIT tail |
| --- | --- | --- | --- | --- |
| 1 | manual_review | - / - / - | - / - / - | - |
| 2 | room_option | 3 / - / Awaiting Client Response | 18.07.2025 / - / - (visit=idle) | date_updated_initial (1->3) |
| 3 | offer_draft | 5 / - / Awaiting Client Response | 18.07.2025 / Room B / 1:Draft (visit=idle) | offer_generated (4->4) |
| 4 | negotiation_clarification | 5 / - / Awaiting Client Response | 18.07.2025 / Room B / 1:Draft (visit=idle) | offer_generated (4->4) |
| 5 | negotiation_accept | 7 / - / In Progress | 18.07.2025 / Room B / 1:Accepted (visit=idle) | transition_ready (6->7) |
| 6 | confirmation_site_visit | 7 / - / Awaiting Client Response | 18.07.2025 / Room B / 1:Accepted (visit=proposed) | transition_ready (6->7) |
| 7 | - | 7 / - / Awaiting Client Response | 18.07.2025 / Room B / 1:Accepted (visit=proposed) | site_visit_proposed (7->7) |
| 8 | confirmation_final | 7 / - / In Progress | 18.07.2025 / Room B / 1:Accepted (visit=scheduled @17.07.2025 at 10:00) | site_visit_proposed (7->7) |
| 9 | - | 7 / - / In Progress | 18.07.2025 / Room B / 1:Accepted (visit=scheduled @17.07.2025 at 10:00) | confirmation_sent (7->7) |

Validation: hil_gate ✅ confirmation_hil ✅ detours ✅ thread_fsm ✅ audit ✅ confirmation_variant ✅ site_visit ✅ better_room_altdates ❌

## Scenario J
Larger-room alternatives suggested via alt dates; client later detours to a new date before confirming.

| TURN | DRAFT type | STATE (step / caller / thread) | DATA (date / room / offers) | AUDIT tail |
| --- | --- | --- | --- | --- |
| 1 | manual_review | - / - / - | - / - / - | - |
| 2 | room_option | 3 / - / Awaiting Client Response | 10.07.2025 / - / - | date_updated_initial (1->3) |
| 3 | room_available | 3 / - / Awaiting Client Response | 10.07.2025 / - / - | date_updated_initial (1->3) |
| 4 | room_available | 3 / - / Awaiting Client Response | 24.07.2025 / - / - | date_confirmed (2->3) |
| 5 | offer_draft | 5 / - / Awaiting Client Response | 24.07.2025 / Room B / 1:Draft | offer_generated (4->4) |
| 6 | negotiation_clarification | 5 / - / Awaiting Client Response | 24.07.2025 / Room B / 1:Draft | offer_generated (4->4) |
| 7 | negotiation_accept | 7 / - / In Progress | 24.07.2025 / Room B / 1:Accepted | transition_ready (6->7) |
| 8 | confirmation_question | 7 / - / Awaiting Client Response | 05.08.2025 / - / 1:Accepted | date_confirmed (2->7) |
| 9 | confirmation_question | 7 / - / Awaiting Client Response | 05.08.2025 / - / 1:Accepted | date_confirmed (2->7) |
| 10 | confirmation_question | 7 / - / Awaiting Client Response | 05.08.2025 / - / 1:Accepted | date_confirmed (2->7) |
| 11 | confirmation_final | 7 / - / In Progress | 05.08.2025 / - / 1:Accepted | date_confirmed (2->7) |
| 12 | - | 7 / - / In Progress | 05.08.2025 / - / 1:Accepted | confirmation_sent (7->7) |

Alt dates offered on TURN2: 2025-07-24, 2025-07-31, 2025-08-05 → final chosen date 05.08.2025 (matches 2025-08-05).

Validation: hil_gate ✅ confirmation_hil ✅ detours ✅ thread_fsm ✅ audit ✅ confirmation_variant ✅ site_visit ❌ better_room_altdates ✅

## Checks
| Scenario | hil_gate | confirmation_hil | detours | thread_fsm | audit | confirmation_variant | site_visit | better_room_altdates |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Scenario I | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Scenario J | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |

## Follow-ups
- Scenario I: better_room_altdates ❌ by design (no alternative-room request).
- Scenario J: site_visit ❌ expected since no visit flow triggered.
