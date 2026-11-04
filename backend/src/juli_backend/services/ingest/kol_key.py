"""The hashed KOL key shared by ``affiliate_partner_period`` and the affiliate order lines.

``short_hash("a", affiliate_id)`` is the ``segment`` of an ``affiliate_partner_period`` row (the
platform's numeric affiliate id, never stored). The order report (SellerConversionReport) names a
creator by PUBLIC account handle only, so an order line's ``kol_key`` is the same function over
the lower-cased handle: when the "account" cell is the numeric id the two keys are equal, else
the read model joins the line to the partner row by handle. No raw id is stored either way.
"""

from __future__ import annotations

import hashlib

KOL_PREFIX = "a"


def short_hash(prefix: str, *parts: object) -> str:
    """``prefix`` + 12 hex of the parts (13 characters: fits the 16-character ``segment``)."""
    digest = hashlib.sha1("|".join(str(p) for p in parts).encode(), usedforsecurity=False)
    return f"{prefix}{digest.hexdigest()[:12]}"


def kol_key(account: str) -> str:
    """The key of a creator account handle (trimmed, lower-cased)."""
    return short_hash(KOL_PREFIX, account.strip().lower())


def normal_handle(handle: str | None) -> str:
    """Handle comparison form (trimmed, lower-cased, no leading ``@``)."""
    return (handle or "").strip().lstrip("@").lower()
