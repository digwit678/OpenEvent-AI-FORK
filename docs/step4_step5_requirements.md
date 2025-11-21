## Room Availability & Offer Composition Requirements

Captured from product feedback on 2025-???, this note summarises expectations for Steps 3–5 so we can reuse them without restating the full prompt.

### Step 3 — Room Availability
- Extract client intent for layouts, catering, and add-ons (e.g. cocktail setup, bar area, background music, finger food) and persist them in `preferences`.
- Rank rooms using contextual similarity, not exact string matches. Products configured on the room that fully cover the client’s request should bubble to the top.
- When preferences map to existing room services, show those matches (e.g. “finger food catering”, “background music”) in the table hints so the client sees why a room is recommended.

### Step 4 — Offer Composition
- When a room is locked, automatically add all products/catering that match the captured preferences and are available for that room. The offer table should show one line per product with quantity and calculated line total.
- Present additional close matches below the offer: product add-ons and catering alternatives (separate section) with meaningful similarity (currently ≥50%; TODO tune threshold later). Do not repeat items that were already added.
- Prefer suggestions that entail the client’s wishes even when the catalog item is broader (e.g. an apéro menu covering “finger food”).
- Continue prompting the client only when no confident matches exist.

### Messaging & Follow-up
- Room selection hints should remain aligned with the matched products.
- Offer drafts must keep a clear CTA; when alternatives are listed, make sure they read as optional recommendations.

> TODO: Expose the similarity threshold as configuration so we can adjust it without code changes.
