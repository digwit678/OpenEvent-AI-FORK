# OpenEvent AI Architecture Diagrams

This document provides visual explanations of the system's architecture, workflow stages, and detection logic.

## 1. System Context & High-Level Architecture

This diagram shows how the system interacts with the user and external components.

![System Context Diagram](assets/diagrams/system_context.png)

## 2. Workflow State Machine

The core of the application is a linear state machine with "detour" capabilities.

![Workflow State Machine](assets/diagrams/workflow_state_machine.png)

## 3. Workflow Routing Logic

How the system decides which code module processes an incoming message.

![Routing Logic](assets/diagrams/routing_logic.png)

## 4. Detection Logic (Inside a Stage)

Inside each stage (e.g., Intake, Date Confirmation), a multi-layered approach is used to understand the user's intent.

![Detection Logic](assets/diagrams/detection_logic.png)

## 5. Detailed Stage Definitions

| Step | Name | Description | Key Actions |
| :--- | :--- | :--- | :--- |
| **1** | **Intake** | Initial contact and requirement gathering. | Extract Event Type, Pax, Date preference. Create Event record. |
| **2** | **Date Confirmation** | Nail down the exact date/time. | Handle "Next Friday", specific dates. Check Calendar. |
| **3** | **Room Availability** | Select specific rooms. | Present options based on Pax/Layout. Handle "Room A vs Room B". |
| **4** | **Offer Review** | Present formal offer/quote. | Generate pricing. Handle "Send me the quote". |
| **5** | **Negotiation** | Refine terms. | Handle price objections, menu changes. |
| **6** | **Transition** | Pre-booking checks. | Verify all details before final confirmation. |
| **7** | **Confirmation** | Final booking. | Send confirmation email. Close lead. |