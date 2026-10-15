"""Reviewer configuration from the environment (P32-A, D42).

``REVIEWER_SHOP_ID`` -- the reference shop (Fujiwa's ``shops.id``). Never a
literal in code: the seller paths do not know it exists. Optional (D42
amendment, 2026-10-15): unset, a reviewer has no shop and the demo shows its
sample shop; set, the reviewer is pinned to that shop, masked.
``REVIEWER_MASK_TERMS`` -- extra brand words to hide, comma-separated.
"""

from __future__ import annotations

import os
import uuid

#: Fixed namespace of the reviewer's shop alias (any UUID would do; it must not change).
_ALIAS_NAMESPACE = uuid.UUID("6f1c2a52-5d0e-4c2b-9a51-32a7e1d4c0de")


def reviewer_shop_id() -> uuid.UUID | None:
    raw = os.getenv("REVIEWER_SHOP_ID", "").strip()
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


def shop_alias_id(shop_id: uuid.UUID) -> uuid.UUID:
    """The id a reviewer sees (and must send as ``X-Shop-Id``) instead of the real one."""
    return uuid.uuid5(_ALIAS_NAMESPACE, f"reviewer-shop:{shop_id}")


def extra_mask_terms() -> tuple[str, ...]:
    raw = os.getenv("REVIEWER_MASK_TERMS", "")
    return tuple(term.strip() for term in raw.split(",") if len(term.strip()) >= 3)
