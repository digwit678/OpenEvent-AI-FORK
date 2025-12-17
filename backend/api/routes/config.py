"""
MODULE: backend/api/routes/config.py
PURPOSE: Configuration management endpoints.

ENDPOINTS:
    GET  /api/config/global-deposit  - Get global deposit config
    POST /api/config/global-deposit  - Set global deposit config

DEPENDS ON:
    - backend/workflow_email.py  # Database operations
"""

from datetime import datetime
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.workflow_email import (
    load_db as wf_load_db,
    save_db as wf_save_db,
)
from backend.ux.universal_verbalizer import (
    UNIVERSAL_SYSTEM_PROMPT,
    STEP_PROMPTS as DEFAULT_STEP_PROMPTS
)


router = APIRouter(prefix="/api/config", tags=["config"])


# --- Request Models ---

class GlobalDepositConfig(BaseModel):
    """
    Global deposit configuration applied to all offers by default.
    """
    deposit_enabled: bool = False
    deposit_type: str = "percentage"  # "percentage" or "fixed"
    deposit_percentage: int = 30
    deposit_fixed_amount: float = 0.0
    deposit_deadline_days: int = 10


class PromptConfig(BaseModel):
    """
    Configuration for LLM prompts (System + Per-Step).
    Used by the "River" configuration page.
    """
    system_prompt: str
    step_prompts: Dict[int, str]


class PromptHistoryEntry(BaseModel):
    ts: str
    config: PromptConfig


class PromptHistoryResponse(BaseModel):
    history: List[PromptHistoryEntry]


# --- Helper Functions ---

def _now_iso() -> str:
    """Return current UTC time in ISO format."""
    return datetime.utcnow().isoformat() + "Z"


# --- Route Handlers ---

@router.get("/global-deposit")
async def get_global_deposit_config():
    """
    Get the current global deposit configuration.

    Returns default values if not yet configured.
    """
    try:
        db = wf_load_db()
        config = db.get("config", {}).get("global_deposit", {})
        return {
            "deposit_enabled": config.get("deposit_enabled", False),
            "deposit_type": config.get("deposit_type", "percentage"),
            "deposit_percentage": config.get("deposit_percentage", 30),
            "deposit_fixed_amount": config.get("deposit_fixed_amount", 0.0),
            "deposit_deadline_days": config.get("deposit_deadline_days", 10),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load deposit config: {exc}"
        ) from exc


@router.post("/global-deposit")
async def set_global_deposit_config(config: GlobalDepositConfig):
    """
    Set the global deposit configuration.

    This setting applies to all offers unless overridden by room-specific
    deposit settings (future feature).
    """
    try:
        db = wf_load_db()
        if "config" not in db:
            db["config"] = {}
        db["config"]["global_deposit"] = {
            "deposit_enabled": config.deposit_enabled,
            "deposit_type": config.deposit_type,
            "deposit_percentage": config.deposit_percentage,
            "deposit_fixed_amount": config.deposit_fixed_amount,
            "deposit_deadline_days": config.deposit_deadline_days,
            "updated_at": _now_iso(),
        }
        wf_save_db(db)
        print(f"[Config] Global deposit updated: enabled={config.deposit_enabled} type={config.deposit_type}")
        return {"status": "ok", "config": db["config"]["global_deposit"]}
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save deposit config: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Prompt Configuration Endpoints
# ---------------------------------------------------------------------------

@router.get("/prompts", response_model=PromptConfig)
async def get_prompts_config():
    """
    Get current prompt configuration.
    Merges DB overrides with code defaults.
    """
    try:
        db = wf_load_db()
        stored = db.get("config", {}).get("prompts", {})
        
        # Merge stored steps with defaults to ensure all keys exist
        merged_steps = DEFAULT_STEP_PROMPTS.copy()
        stored_steps = stored.get("step_prompts", {})
        
        # stored_steps keys might be strings in JSON, convert to int for merging
        for k, v in stored_steps.items():
            try:
                merged_steps[int(k)] = v
            except ValueError:
                pass

        return {
            "system_prompt": stored.get("system_prompt", UNIVERSAL_SYSTEM_PROMPT),
            "step_prompts": merged_steps
        }
    except Exception as exc:
        print(f"[Config][ERROR] Failed to load prompts: {exc}")
        # Fallback to defaults on error
        return {
            "system_prompt": UNIVERSAL_SYSTEM_PROMPT,
            "step_prompts": DEFAULT_STEP_PROMPTS
        }


@router.post("/prompts")
async def set_prompts_config(config: PromptConfig):
    """
    Save new prompt configuration.
    Archives the previous version to history.
    """
    try:
        db = wf_load_db()
        if "config" not in db:
            db["config"] = {}
        
        # Archive current state if exists
        current = db["config"].get("prompts")
        if current:
            history = db["config"].get("prompts_history", [])
            history.insert(0, {
                "ts": _now_iso(),
                "config": current
            })
            # Keep history limited (e.g. last 50 versions)
            db["config"]["prompts_history"] = history[:50]
        
        # Save new state
        db["config"]["prompts"] = {
            "system_prompt": config.system_prompt,
            "step_prompts": {str(k): v for k, v in config.step_prompts.items()},
            "updated_at": _now_iso()
        }
        wf_save_db(db)
        print("[Config] Prompts updated and persisted.")
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save prompts: {exc}"
        ) from exc


@router.get("/prompts/history", response_model=PromptHistoryResponse)
async def get_prompts_history():
    """Get the history of prompt changes."""
    try:
        db = wf_load_db()
        history = db.get("config", {}).get("prompts_history", [])
        return {"history": history}
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to load prompt history: {exc}"
        ) from exc


@router.post("/prompts/revert/{index}")
async def revert_prompts_config(index: int):
    """
    Revert prompt configuration to a historical version.
    The current state is pushed to history before reverting.
    """
    try:
        db = wf_load_db()
        history = db.get("config", {}).get("prompts_history", [])
        
        if index < 0 or index >= len(history):
            raise HTTPException(status_code=404, detail="History index out of range")
            
        target_entry = history[index]
        target_config = target_entry.get("config")
        
        if not target_config:
            raise HTTPException(status_code=400, detail="Invalid history entry")

        # Archive current
        current = db["config"].get("prompts")
        if current:
            history.insert(0, {
                "ts": _now_iso(),
                "config": current
            })
            
        # Apply revert
        db["config"]["prompts"] = target_config
        db["config"]["prompts"]["updated_at"] = _now_iso()
        
        # Update history
        db["config"]["prompts_history"] = history[:50]
        
        wf_save_db(db)
        print(f"[Config] Reverted prompts to version from {target_entry.get('ts')}")
        return {"status": "ok"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to revert prompts: {exc}"
        ) from exc



# ---------------------------------------------------------------------------
# Room-Specific Deposit Endpoints (INACTIVE - For Future Integration)
# ---------------------------------------------------------------------------
# INTEGRATION NOTE FOR FRONTEND INTEGRATORS:
# ==========================================
# These endpoints are prepared for future integration with the main OpenEvent
# frontend. They allow setting deposit requirements per room, which override
# the global deposit setting.
#
# To activate:
# 1. Uncomment the endpoints below
# 2. Add the corresponding UI in the Rooms Setup page
# 3. Update the offer generation logic to check room-specific deposits first
#
# Data structure (stored in db.config.room_deposits[room_id]):
# {
#   "deposit_required": boolean,
#   "deposit_percent": number (1-100),
#   "updated_at": ISO timestamp
# }
# ---------------------------------------------------------------------------

# @router.get("/room-deposit/{room_id}")
# async def get_room_deposit_config(room_id: str):
#     """
#     Get deposit configuration for a specific room.
#
#     INACTIVE - Uncomment when integrating with main frontend.
#     """
#     try:
#         db = wf_load_db()
#         room_deposits = db.get("config", {}).get("room_deposits", {})
#         config = room_deposits.get(room_id, {})
#         return {
#             "room_id": room_id,
#             "deposit_required": config.get("deposit_required", False),
#             "deposit_percent": config.get("deposit_percent", None),
#             "updated_at": config.get("updated_at"),
#         }
#     except Exception as exc:
#         raise HTTPException(
#             status_code=500, detail=f"Failed to load room deposit config: {exc}"
#         ) from exc
#
#
# @router.post("/room-deposit/{room_id}")
# async def set_room_deposit_config(room_id: str, deposit_required: bool, deposit_percent: Optional[int] = None):
#     """
#     Set deposit configuration for a specific room.
#
#     INACTIVE - Uncomment when integrating with main frontend.
#
#     This overrides the global deposit setting for offers using this room.
#     """
#     try:
#         db = wf_load_db()
#         if "config" not in db:
#             db["config"] = {}
#         if "room_deposits" not in db["config"]:
#             db["config"]["room_deposits"] = {}
#         db["config"]["room_deposits"][room_id] = {
#             "deposit_required": deposit_required,
#             "deposit_percent": deposit_percent,
#             "updated_at": _now_iso(),
#         }
#         wf_save_db(db)
#         print(f"[Config] Room deposit updated: room={room_id} required={deposit_required} percent={deposit_percent}")
#         return {"status": "ok", "room_id": room_id, "config": db["config"]["room_deposits"][room_id]}
#     except Exception as exc:
#         raise HTTPException(
#             status_code=500, detail=f"Failed to save room deposit config: {exc}"
#         ) from exc
