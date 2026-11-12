"""Reviewer configuration from the environment (P32-A, D42).

``REVIEWER_SHOP_ID`` -- the reference shop (Fujiwa's ``shops.id``). Never a
literal in code: the seller paths do not know it exists. Optional (D42
amendment, 2026-10-15): unset, a reviewer has no shop and the demo shows its
sample shop; set, the reviewer is pinned to that shop, masked.
``REVIEWER_SHOP_IDS`` (fast track P74-A, D77) -- several pins, comma-separated
``shops.id`` values; the FIRST is the default (a request without ``X-Shop-Id``).
The reviewer switches between them with ``X-Shop-Id`` (``api/reviewer.py``). Set,
it wins over ``REVIEWER_SHOP_ID``, which stays as the one-pin form. Each pin is
classified on its own (``sandbox.classify_pin``): a seller's shop is masked and
read-only, Juli's own sandbox shop is live. D77: Fujiwa (masked) first, the sandbox
shop second.
``REVIEWER_MASK_TERMS`` -- extra brand words to hide, comma-separated.
``REVIEWER_SAMPLE_SHOP_IDS`` (P100 S2-B) -- the pins that may be the synthetic Shopee sample
shop ("Dữ liệu mẫu", mode ``sample``: unmasked, read-only, simulated Duyệt / Thực thi). Parsed
like ``REVIEWER_SHOP_IDS``; it only NARROWS: an id that is not also a pin is ignored, so the
list never adds a shop the reviewer can enter. Listing is necessary, not sufficient --
``sandbox.pin_mode`` still checks the shop itself and falls back to ``masked``.
"""

from __future__ import annotations

import os
import uuid

#: Fixed namespace of the reviewer's shop alias (any UUID would do; it must not change).
_ALIAS_NAMESPACE = uuid.UUID("6f1c2a52-5d0e-4c2b-9a51-32a7e1d4c0de")


def _parse(raw: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(raw.strip())
    except ValueError:
        return None


#: P100 S2-B: shops that are never the unmasked sample shop, whatever the env says (Fujiwa, a
#: real seller's shop). The one place this id is a literal; the seller paths still never see it.
NEVER_SAMPLE_SHOP_IDS: frozenset[uuid.UUID] = frozenset(
    {uuid.UUID("2b1da87b-d0a8-46a6-b3c6-2132be0b5f4f")}
)


def _parse_list(raw: str) -> list[uuid.UUID]:
    """Valid, distinct ids of a comma list, in order; an unparsable entry is skipped."""
    found: list[uuid.UUID] = []
    for entry in raw.split(","):
        value = _parse(entry) if entry.strip() else None
        if value is not None and value not in found:
            found.append(value)
    return found


def reviewer_shop_ids() -> tuple[uuid.UUID, ...]:
    """Every pinned shop, default first (P74-A, D77); empty: no pin (sample mode).

    ``REVIEWER_SHOP_IDS`` when it holds at least one valid id, else ``REVIEWER_SHOP_ID``.
    An unparsable entry is skipped (never widens anything); a repeated id counts once.
    """
    pins = _parse_list(os.getenv("REVIEWER_SHOP_IDS", ""))
    if pins:
        return tuple(pins)
    single = os.getenv("REVIEWER_SHOP_ID", "").strip()
    found = _parse(single) if single else None
    return (found,) if found is not None else ()


def reviewer_sample_shop_ids() -> frozenset[uuid.UUID]:
    """The pins listed in ``REVIEWER_SAMPLE_SHOP_IDS`` (P100 S2-B); never an id that is no pin."""
    listed = _parse_list(os.getenv("REVIEWER_SAMPLE_SHOP_IDS", ""))
    return frozenset(listed).intersection(reviewer_shop_ids())


def reviewer_shop_id() -> uuid.UUID | None:
    """The DEFAULT pin (the first of :func:`reviewer_shop_ids`), or None."""
    pins = reviewer_shop_ids()
    return pins[0] if pins else None


def select_pin(pins: tuple[uuid.UUID, ...], sent: str | None) -> uuid.UUID | None:
    """The pin an ``X-Shop-Id`` value names (its alias or its real id), else the default.

    Selection only: whether the value is ACCEPTED for that pin (a masked pin takes its
    alias only) is decided when the shop is entered (``api/reviewer.enter_reviewer_shop``),
    which refuses anything that is not the selected pin's alias / real id.
    """
    if not pins:
        return None
    value = sent.strip().lower() if sent else ""
    if value:
        for pin in pins:
            if value in (str(shop_alias_id(pin)), str(pin)):
                return pin
    return pins[0]


def shop_alias_id(shop_id: uuid.UUID) -> uuid.UUID:
    """The id a reviewer sees (and must send as ``X-Shop-Id``) instead of the real one."""
    return uuid.uuid5(_ALIAS_NAMESPACE, f"reviewer-shop:{shop_id}")


def extra_mask_terms() -> tuple[str, ...]:
    raw = os.getenv("REVIEWER_MASK_TERMS", "")
    return tuple(term.strip() for term in raw.split(",") if len(term.strip()) >= 3)
