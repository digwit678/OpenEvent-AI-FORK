from __future__ import annotations

import re
from typing import Iterable, List, Sequence, Set

__all__ = [
    "CATERING_SYNONYMS",
    "PRODUCTS_SYNONYMS",
    "normalize_catering",
    "normalize_products",
]

CATERING_SYNONYMS = {
    "coffee service": [
        "coffee service",
        "coffee",
        "coffee break",
        "coffee & tea",
        "coffee/tea",
        "hot beverages",
        "coffee station",
        "filter coffee",
    ],
    "finger food catering": [
        "finger food",
        "finger-food",
        "standing reception",
        "standing reception style",
        "standing cocktail",
        "apero",
        "apéro",
        "cocktail reception",
        "apero riche"
    ]
}

PRODUCTS_SYNONYMS = {
    "u-shape": [
        "u shape",
        "u-shape",
        "u layout",
        "u-shape seating",
        "u-shape setup",
    ],
    "projector": [
        "projector",
        "beamer",
        "projection",
        "projection screen",
    ],
    "cocktail bar": [
        "cocktail bar",
        "cocktail setup",
        "cocktail station",
        "cocktail reception",
        "mixology station",
        "bar area",
        "signature cocktails"
    ],
    "background music": [
        "background music",
        "ambient music",
        "music package",
        "dj set",
        "sound system",
        "music playback",
        "music playlist"
    ],
}


def _normalise_token(token: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", token.lower()).strip()


def _values_to_tokens(value: str | Sequence[str] | None) -> Set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        candidates = [value]
    else:
        candidates = [str(item) for item in value if item]
    tokens: Set[str] = set()
    for candidate in candidates:
        pieces = re.split(r"[;,/]|(?:\s+or\s+)|(?:\s+and\s+)", candidate)
        for piece in pieces:
            normalised = _normalise_token(piece)
            if normalised:
                tokens.add(normalised)
    return tokens


def _match_from_ontology(tokens: Iterable[str], ontology: dict[str, Sequence[str]]) -> List[str]:
    matches: List[str] = []
    token_set = {_normalise_token(token) for token in tokens if token}
    for canonical, variants in ontology.items():
        canonical_normalised = _normalise_token(canonical)
        variant_set = {canonical_normalised}
        variant_set.update(_normalise_token(variant) for variant in variants)
        if not variant_set:
            continue
        if any(
            token in variant_set or any(token in variant for variant in variant_set)
            for token in token_set
        ):
            matches.append(canonical)
    return matches


def normalize_catering(value: str | Sequence[str] | None) -> List[str]:
    """Normalise catering-related phrases to canonical tokens."""

    tokens = _values_to_tokens(value)
    if not tokens:
        return []
    matches = _match_from_ontology(tokens, CATERING_SYNONYMS)
    return sorted(dict.fromkeys(matches))


def normalize_products(value: str | Sequence[str] | None) -> List[str]:
    """Normalise product/layout requests to canonical tokens."""

    tokens = _values_to_tokens(value)
    if not tokens:
        return []
    matches = _match_from_ontology(tokens, PRODUCTS_SYNONYMS)
    return sorted(dict.fromkeys(matches))
