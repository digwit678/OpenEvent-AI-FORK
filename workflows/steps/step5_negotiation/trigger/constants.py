"""
Step 5 Negotiation Constants.

Extracted from step5_handler.py and classification.py as part of N2 refactoring (Dec 2025).
"""

# Counter proposal limits
MAX_COUNTER_PROPOSALS = 3

# Confidence thresholds for classification
CONFIDENCE_ROOM_SELECTION = 0.85
CONFIDENCE_COUNTER_PRICE = 0.65
CONFIDENCE_CLARIFICATION = 0.6
CONFIDENCE_THRESHOLD_MIN = 0.4
CONFIDENCE_FALLBACK = 0.6
CONFIDENCE_LOWEST = 0.3

# Intent type constants
INTENT_ACCEPT = "accept"
INTENT_DECLINE = "decline"
INTENT_COUNTER = "counter"
INTENT_ROOM_SELECTION = "room_selection"
INTENT_CLARIFICATION = "clarification"

# Offer status constants
OFFER_STATUS_ACCEPTED = "Accepted"
OFFER_STATUS_DECLINED = "Declined"

# Site visit states
SITE_VISIT_PROPOSED = "proposed"
