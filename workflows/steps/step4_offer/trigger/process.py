"""
DEPRECATED: Import from step4_handler.py instead.

This module re-exports from the new filename for backwards compatibility.
"""

from .step4_handler import (
    process,
    build_offer,
    _record_offer,
    _apply_product_operations,
    _compose_offer_summary,
)
from ..llm.send_offer_llm import ComposeOffer

__all__ = [
    "process",
    "build_offer",
    "_record_offer",
    "ComposeOffer",
    "_apply_product_operations",
    "_compose_offer_summary",
]
