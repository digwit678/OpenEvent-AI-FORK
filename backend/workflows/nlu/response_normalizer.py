from __future__ import annotations

"""
Normalize diverse client responses to canonical forms.
"""

import re
from typing import Optional, Tuple

# Normalization maps
AFFIRMATIVE_VARIANTS = {
    r"\b(yes|yep|yeah|yea|yup|aye|oui|ja|si)\b": "yes",
    r"\b(ok|okay|k|kk)\b": "ok",
    r"\b(?<!not\s)(sure|certainly|absolutely|definitely|of course)\b": "sure",
    r"\b(sounds?\s+)(good|great|fine|perfect|lovely|wonderful)\b": "positive",
    r"\b(looks?\s+)(good|great|fine|perfect|lovely|wonderful)\b": "positive",
    r"\b(that'?s?\s+)(good|great|fine|perfect|lovely|wonderful)\b": "positive",
    r"\b(all\s+)(good|great|fine|set|clear)\b": "positive",
    r"\b(go\s+ahead|proceed|let'?s?\s+do\s+it|do\s+it)\b": "proceed",
    r"\b(i'?m?\s+)?(happy|satisfied|pleased)\b": "positive",
}

NEGATIVE_VARIANTS = {
    r"\b(no|nope|nah|nay)\b": "no",
    r"\b(i\s+don'?t\s+think\s+so)\b": "no",
    r"\b(not\s+really|not\s+quite|not\s+exactly)\b": "negative",
    r"\b(i'?m?\s+not\s+sure|unsure|uncertain)\b": "uncertain",
    r"\b(cancel|nevermind|forget\s+it)\b": "cancel",
}


def normalize_response(text: str) -> Tuple[Optional[str], float]:
    """
    Normalize a client response to a canonical form.

    Returns:
        (canonical_form, confidence)
        canonical_form is None if no pattern matched
    """
    text_lower = (text or "").lower().strip()

    for pattern, canonical in AFFIRMATIVE_VARIANTS.items():
        if re.search(pattern, text_lower):
            return canonical, 0.85

    for pattern, canonical in NEGATIVE_VARIANTS.items():
        if re.search(pattern, text_lower):
            return canonical, 0.85

    return None, 0.0
