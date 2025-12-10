# OpenEvent-AI: The Autonomous Venue Booking Engine

OpenEvent-AI is a sophisticated, full-stack system designed to automate the end-to-end venue booking flow for "The Atelier". It combines the flexibility of Large Language Models (LLMs) with the reliability of deterministic state machines to handle inquiries, negotiate offers, and confirm bookings with "Human-In-The-Loop" (HIL) oversight.


## 🚀 Overview

The system ingests client inquiries (currently simulated via chat), maintains a deterministic event record, and coordinates every step of the booking process. Unlike simple chatbots, OpenEvent-AI is built on a **workflow engine** that tracks the lifecycle of an event from a "Lead" to a "Confirmed" booking.

### Key Features
- **Deterministic Workflow**: A 7-step state machine ensures no inquiry is lost and every booking follows the strict business rules.
- **Hybrid AI/Logic**: Uses LLMs for Natural Language Understanding (NLU) and drafting responses, but relies on rigid Python logic for pricing, availability, and state transitions.
- **"Safety Sandwich"**: A unique architectural pattern where LLM outputs are "sandwiched" between deterministic fact-extraction and verification layers to prevent hallucinations (e.g., inventing prices or rooms).
- **Human-In-The-Loop (HIL)**: Critical actions (sending offers, confirming dates) generate "Tasks" that require manager approval before proceeding.
- **Seamless Detours**: Clients can change their minds (e.g., "Actually, I need a bigger room") at any point, and the system intelligently "detours" to the previous necessary step without losing context.

---

## 🏗 Architecture

The system is composed of two main applications:

```mermaid
graph TD
    A[Client Frontend (Next.js)] <-->|REST API| B[Backend API (FastAPI)]
    B <--> C[Workflow Engine (Python)]
    C <--> D[LLM Adapter (OpenAI)]
    C <--> E[Data Store (JSON / Supabase)]
    C <--> F[Calendar & Inventory]
```

### 1. Frontend (`atelier-ai-frontend/`)
A **Next.js 15** application that serves as the user interface for:
- **Clients**: To chat with the AI assistant.
- **Managers**: To review HIL tasks, configure global settings (deposits, pricing), and monitor active events.

### 2. Backend (`backend/`)
A **Python FastAPI** application that acts as the brain. It exposes endpoints for the frontend and hosts the `workflow_email.py` orchestrator.

- **Orchestrator (`backend/workflow_email.py`)**: The central nervous system. It receives messages, loads state, executes the current step's logic, and persists the result.
- **Groups (`backend/workflows/groups/`)**: Logic is divided into "Groups" corresponding to workflow steps (e.g., `intake`, `room_availability`, `offer`).
- **NLU/Detectors (`backend/workflows/nlu/`)**: Specialized modules that analyze text to detect intents (e.g., `site_visit_detector`, `general_qna_classifier`).

---

## 🧠 Core Concepts

### The 7-Step Workflow
1.  **Intake**: Classify intent, capture contact info, and understand requirements.
2.  **Date Confirmation**: Propose and lock in a specific date.
3.  **Room Availability**: Check inventory, handle conflicts, and select a room.
4.  **Offer**: Generate a priced offer (PDF/Text) with deposits and policies.
5.  **Negotiation**: Handle counter-offers and questions.
6.  **Transition**: Final prerequisites check.
7.  **Confirmation**: Payment processing and final booking confirmation.

### Detectors & Gates
- **Detectors**: Instead of a giant "AI Prompt", the system uses targeted classifiers. For example, `detect_structural_change` checks if a user is trying to change a previously agreed date.
- **Entry Guards**: Each step has strict entry requirements (e.g., "You cannot enter Step 3 without a confirmed date in Step 2").
- **Hash Guards**: To save compute and API costs, steps calculate a "requirements hash". If the user's input hasn't changed the requirements, the expensive calculation is skipped.

### Detours
Real conversations aren't linear. "Detours" allow the workflow to react to non-linear requests.
*   *Example*: A user at Step 5 (Negotiation) says "Wait, is Room A available instead?".
*   *Action*: The **Change Propagation** module detects the intent, rewinds the state to Step 3 (Room Availability), re-runs availability, and then attempts to return to the latest possible step.

### Safety Sandwich
To ensure trust:
1.  **Deterministic Input**: We calculate the exact price: `CHF 500`.
2.  **LLM "Verbalizer"**: We ask the AI to write a polite message including "CHF 500".
3.  **Deterministic Verifier**: We scan the AI's output. If it wrote "CHF 400" or "500 Euros", the system rejects the draft and forces a correction or fallback.

---

## 📂 Project Structure

```text
/
├── atelier-ai-frontend/    # Next.js Frontend application
├── backend/                # Python Backend application
│   ├── api/                # FastAPI endpoints
│   ├── agents/             # Legacy & specialized agent tools
│   ├── main.py             # App entry point
│   ├── workflow_email.py   # Core State Machine Orchestrator
│   └── workflows/          # Business Logic
│       ├── groups/         # Step implementations (intake, offer, etc.)
│       ├── nlu/            # Detectors & Classifiers
│       └── io/             # Database & Task Management
├── docs/                   # Detailed documentation & rules
└── tests/                  # Pytest suite
```

---

## 🚦 Getting Started

### Prerequisites
- **Python 3.10+**
- **Node.js 18+**
- **OpenAI API Key** (Set as `OPENAI_API_KEY` env var)

### 1. Setup Backend
```bash
cd backend
# Create virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements-dev.txt

# Run the API
# Note: Ensure you are in the project root
export PYTHONPATH=$PYTHONPATH:.
uvicorn backend.main:app --reload --port 8000
```

### 2. Setup Frontend
```bash
cd atelier-ai-frontend
npm install
npm run dev
```
The frontend will be available at `http://localhost:3000`.

### 3. Run Tests
The project has a comprehensive regression suite.
```bash
# Run all tests
pytest

# Run specific workflow tests
pytest backend/tests/workflows/test_workflow_v3_alignment.py
```

---

## 🛠 Current Status & Configuration

### Recent Updates
- **Supabase Integration**: Can be toggled via `OE_INTEGRATION_MODE=supabase`.
- **Site Visit Logic**: Dedicated sub-flow for handling venue tours.
- **Deposit Configuration**: Managers can now set global deposit rules.

### Configuration
Key environment variables (create a `.env` file):
- `OPENAI_API_KEY`: Required for NLU and Verbalizer.
- `OE_INTEGRATION_MODE`: `json` (default) or `supabase`.
- `WF_DEBUG_STATE`: Set to `1` for verbose workflow logging.

---

## 📚 Documentation
For deeper dives into specific subsystems:
- **[Workflow Rules](docs/workflow_rules.md)**: The "Constitution" of the booking logic.
- **[Team Guide](docs/TEAM_GUIDE.md)**: Best practices and troubleshooting.
- **[Integration Guide](docs/INTEGRATION_PREPARATION_GUIDE.md)**: How to deploy and connect to real infrastructure.