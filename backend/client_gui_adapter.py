from __future__ import annotations

import json
from typing import Any, Dict


class ClientGUIAdapter:
    """OpenEvent Action (light-blue): sync availability cards into the client-facing GUI."""

    def upsert_card(
        self,
        event_id: str,
        card_type: str,
        payload: Dict[str, Any],
        idempotency_key: str,
    ) -> None:
        print(f"[GUI] upsert_card event={event_id} card={card_type} id={idempotency_key}")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
