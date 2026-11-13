"""P100 S2-D: the sample shop's pre-written card content in ``card_content_specs`` (migration 127).

The shapes are the E.7 ones agreed with Session 1 (``fasttrack/contracts/p100-s2-demo.md``,
"E.7 card specs"). Every row here is ``source='seeded'``, with no LLM call:

- one ``style_profile`` for "Hiên Nhà" (a fixed palette; the covers are the catalogue's own ids);
- one ``title`` spec per product: 3 fixed candidates. The title route on a sample pin serves them
  through the same screen as a live draft (``drafts.screen_titles``);
- one ``banner`` spec per open voucher card and per cover card. Banner values are read from the card
  or the catalogue and named in ``sources``; nothing is invented.

Re-seeding is a no-op while any seeded row exists. ``--reset`` deletes the shop's rows (owner
connection), so the next load writes them again, and the reviewer's live-regenerate quota with them.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.card_content_specs import (
    SCHEMA_VERSION,
    SOURCE_LLM,
    SOURCE_SEEDED,
    SPEC_BANNER,
    SPEC_STYLE_PROFILE,
    SPEC_TITLE,
    CardContentSpec,
)
from juli_backend.services.sample_shop.catalog import KEYWORDS, PRODUCTS, Product

#: The model name a seeded title spec carries (no model wrote it).
SEEDED_MODEL = "seeded"
#: A sample-pin reviewer may run the live title draft this many times per product (contract S2-D).
SAMPLE_LIVE_TITLES_PER_PRODUCT = 1
#: The voucher card kinds a banner is written for (the sample shop's three strategies).
VOUCHER_KINDS = frozenset({"min_spend_voucher", "review_voucher", "voucher_cap"})
#: The open card statuses whose banners the reviewer can see.
OPEN_STATUSES = ("sent", "approved")

PALETTE = ("#2F6B4F", "#F4EFE6", "#E07A3F")
PRIMARY, BACKGROUND, ACCENT = PALETTE

#: Three candidates per product (index into ``PRODUCTS``). Facts only: names, sizes, scents and
#: pack counts the catalogue states. Every candidate carries its product's keyword
#: (``catalog.KEYWORDS``, one per product since S2-D2).
TITLE_CANDIDATES: dict[int, tuple[str, str, str]] = {
    0: (
        "Nước rửa chén sinh học Hiên Nhà chai 500ml hương chanh, hương trà xanh",
        "Combo 3 chai nước rửa chén sinh học Hiên Nhà 500ml hương chanh và trà xanh",
        "Nước rửa chén sinh học Hiên Nhà 500ml, chọn hương chanh hoặc trà xanh, có combo 3 chai",
    ),
    1: (
        "Khăn lau bếp đa năng Hiên Nhà set 5 khăn màu xám, màu pastel",
        "Set 5 khăn lau bếp đa năng Hiên Nhà, chọn màu xám hoặc pastel",
        "Khăn lau bếp Hiên Nhà set 5 khăn đa năng, bộ màu xám và bộ màu pastel",
    ),
    2: (
        "Túi đựng rác tự hủy sinh học Hiên Nhà cuộn 30 túi, size M 45x55cm, size L 55x65cm",
        "Túi đựng rác tự hủy sinh học Hiên Nhà cuộn 30 túi, có size M và size L",
        "Cuộn 30 túi đựng rác tự hủy sinh học Hiên Nhà, size M 45x55cm và L 55x65cm",
    ),
    3: (
        "Găng tay rửa chén cao su Hiên Nhà dày dặn không mùi, size M, size L",
        "Găng tay rửa chén Hiên Nhà cao su dày dặn, không mùi, có size M và L",
        "Găng tay rửa chén cao su không mùi Hiên Nhà, dày dặn, chọn size M hoặc L",
    ),
    4: (
        "Hộp đựng thực phẩm thủy tinh Hiên Nhà nắp kín, hộp 640ml, hộp 1040ml, bộ 3 hộp",
        "Hộp đựng thực phẩm Hiên Nhà thủy tinh nắp kín, có hộp 640ml và 1040ml",
        "Bộ 3 hộp đựng thực phẩm thủy tinh Hiên Nhà nắp kín, hộp 640ml và 1040ml",
    ),
    5: (
        "Hiên Nhà bình xịt vệ sinh đa năng chai 500ml",
        "Bình xịt vệ sinh Hiên Nhà đa năng chai 500ml",
        "Bình xịt vệ sinh đa năng Hiên Nhà, chai 500ml",
    ),
}

#: A pack size as a listing writes it: a volume or weight ("500ml", "1,5l", "200g") or a size in
#: centimetres ("45x55cm").
_SIZE = re.compile(r"\d+(?:[.,]\d+)?\s?(?:ml|l|kg|g)\b|\d+\s?x\s?\d+\s?cm\b", re.IGNORECASE)


@dataclass(frozen=True)
class SeededSpecs:
    """What :func:`seed_content_specs` wrote (all zero when the shop already had them)."""

    style_profile: int = 0
    titles: int = 0
    banners: int = 0


def canonical_hash(value: Any) -> str:
    """sha256 hex of the canonical JSON of ``value`` (sorted keys, no spaces, UTF-8)."""
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cover_image_id(product: Product) -> str:
    """The catalogue's cover id for a product (the generator's and the snapshot's image)."""
    return f"sample_{product.parent_sku.lower()}_cover"


def keywords_of(index: int) -> list[str]:
    return [kw for i, kw in KEYWORDS if i == index]


def style_profile() -> tuple[dict[str, Any], str]:
    """The shop's style profile and its ``inputs_hash`` (the sorted cover image ids)."""
    covers = [
        {"item_id": p.item_id, "image_id": cover_image_id(p), "image_sha256": None}
        for p in PRODUCTS
    ]
    spec = {
        "palette": list(PALETTE),
        "primary": PRIMARY,
        "accent": ACCENT,
        "type_feel": "rounded",
        "radius": "large",
        "text_density": "low",
        "positions_used": ["top_right", "bottom_right"],
        "covers_seen": covers,
    }
    return spec, canonical_hash(sorted(c["image_id"] for c in covers))


def title_spec(index: int) -> tuple[dict[str, Any], str]:
    """Product ``index``'s seeded title spec and its ``inputs_hash`` (of ``inputs``)."""
    product = PRODUCTS[index]
    kws = keywords_of(index)
    inputs = {
        "current_title": product.name,
        "keywords": [{"keyword": k, "role": "chinh", "searches": None} for k in kws],
        "banned_terms": [],
        "max_chars": 100,
    }
    candidates = [
        {
            "title": t,
            "chars": len(t),
            "keywords_placed": [k for k in kws if k.casefold() in t.casefold()],
            "keywords_late": [],
            "note": "",
        }
        for t in TITLE_CANDIDATES[index]
    ]
    spec = {"inputs": inputs, "candidates": candidates, "chosen": None, "model": SEEDED_MODEL}
    return spec, canonical_hash(inputs)


def _size_text(product: Product) -> tuple[str | None, str]:
    """The pack size the listing states, and the field it came from (None: none stated)."""
    found = _SIZE.findall(product.name)
    if found:
        return found[0].replace(" ", ""), "item.name"
    sizes: list[str] = []
    for v in product.variations:
        for s in _SIZE.findall(v.name):
            s = s.replace(" ", "")
            if s not in sizes:
                sizes.append(s)
    if sizes:
        return " · ".join(sizes), "item.variations.name"
    return None, "item.name"


def banner_spec(card_id: uuid.UUID, card: dict[str, Any], product: Product) -> dict[str, Any]:
    """A rule-built banner spec for an open card, with every value's source named."""
    kind = card["change_kind"]
    banners: list[dict[str, Any]] = []
    if kind in VOUCHER_KINDS:
        after = (card.get("change") or {}).get("after") or {}
        values = {"value": after.get("value"), "pct": after.get("pct"),
                  "min_spend": after.get("min_spend")}  # fmt: skip
        values = {k: v for k, v in values.items() if v is not None}
        banners.append(
            {
                "shape": "goc",
                "kind": "voucher",
                "values": values,
                "sources": {
                    k: {"card_id": str(card_id), "field": f"change.after.{k}"} for k in values
                },
                "position": "top_right",
                "colour": ACCENT,
                "size": "M",
            }
        )
    size, field = _size_text(product)
    if size is not None:
        # Only a size the listing states; none stated, no size banner (never an empty one).
        banners.append(
            {
                "shape": "the",
                "kind": "quy_cach",
                "values": {"text": size},
                "sources": {"text": {"card_id": None, "field": field}},
                "position": "bottom_right",
                "colour": PRIMARY,
                "size": "S",
            }
        )
    checks = [
        {"code": "empty_value", "banner": i, "fix": "Điền giá trị hoặc bỏ nhãn này."}
        for i, b in enumerate(banners)
        if any(v is None for v in b["values"].values()) or not b["values"]
    ]
    return {
        "template": "toi_gian",
        "day_mode": "ngay_thuong",
        "size_px": 1200,
        "banners": banners,
        "checks": checks,
        "check_call_id": None,
    }


async def has_seeded(session: AsyncSession, shop_id: uuid.UUID) -> bool:
    found = await session.scalar(
        select(CardContentSpec.id)
        .where(CardContentSpec.shop_id == shop_id, CardContentSpec.source == SOURCE_SEEDED)
        .limit(1)
    )
    return found is not None


def _row(
    shop_id: uuid.UUID,
    spec_type: str,
    spec: dict[str, Any],
    inputs_hash: str,
    *,
    now: datetime,
    item_id: str | None = None,
    proposal_id: uuid.UUID | None = None,
) -> CardContentSpec:
    return CardContentSpec(
        id=uuid.uuid4(),
        shop_id=shop_id,
        spec_type=spec_type,
        proposal_id=proposal_id,
        item_id=item_id,
        schema_version=SCHEMA_VERSION,
        inputs_hash=inputs_hash,
        spec=spec,
        source=SOURCE_SEEDED,
        llm_call_id=None,
        created_by_user_id=None,
        created_at=now,
    )


async def seed_content_specs(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime
) -> SeededSpecs:
    """Write the seeded rows (after the cards exist: banners need their card). Caller commits."""
    from juli_backend.services.shopee_recommendations import store

    if await has_seeded(session, shop_id):
        return SeededSpecs()
    profile, profile_hash = style_profile()
    session.add(_row(shop_id, SPEC_STYLE_PROFILE, profile, profile_hash, now=now))
    for index, product in enumerate(PRODUCTS):
        spec, inputs_hash = title_spec(index)
        session.add(_row(shop_id, SPEC_TITLE, spec, inputs_hash, now=now, item_id=product.item_id))
    by_item = {p.item_id: p for p in PRODUCTS}
    banners = 0
    for proposal, card in await store.list_cards(session, shop_id, statuses=list(OPEN_STATUSES)):
        kind = card["change_kind"]
        listed = by_item.get(proposal.item_id or "")
        if listed is None or not (kind == "cover_image" or kind in VOUCHER_KINDS):
            continue
        spec = banner_spec(proposal.id, card, listed)
        session.add(
            _row(
                shop_id,
                SPEC_BANNER,
                spec,
                canonical_hash(spec["banners"]),
                now=now,
                item_id=listed.item_id,
                proposal_id=proposal.id,
            )
        )
        banners += 1
    await session.flush()
    return SeededSpecs(style_profile=1, titles=len(PRODUCTS), banners=banners)


async def latest_title(
    session: AsyncSession, shop_id: uuid.UUID, item_id: str
) -> CardContentSpec | None:
    """The newest title spec of a product (any source)."""
    return await session.scalar(
        select(CardContentSpec)
        .where(
            CardContentSpec.shop_id == shop_id,
            CardContentSpec.spec_type == SPEC_TITLE,
            CardContentSpec.item_id == item_id,
        )
        .order_by(CardContentSpec.created_at.desc())
        .limit(1)
    )


async def live_titles_used(session: AsyncSession, shop_id: uuid.UUID, item_id: str) -> int:
    """How many live (``llm``) title rows a product has: the sample shop's quota count."""
    count = await session.scalar(
        select(func.count())
        .select_from(CardContentSpec)
        .where(
            CardContentSpec.shop_id == shop_id,
            CardContentSpec.spec_type == SPEC_TITLE,
            CardContentSpec.item_id == item_id,
            CardContentSpec.source == SOURCE_LLM,
        )
    )
    return int(count or 0)


def llm_title_row(
    shop_id: uuid.UUID,
    item_id: str,
    *,
    current_title: str,
    keywords: list[str],
    drafts: list[dict[str, Any]],
    model: str,
    user_id: uuid.UUID | None,
    now: datetime,
) -> CardContentSpec:
    """A live draft, stored so the quota counts it (``source='llm'``)."""
    inputs = {
        "current_title": current_title,
        "keywords": [{"keyword": k, "role": "chinh", "searches": None} for k in keywords],
        "banned_terms": [],
        "max_chars": 100,
    }
    candidates = [
        {
            "title": d["title"],
            "chars": d["chars"],
            "keywords_placed": list((d.get("keywords") or {}).get("covered") or []),
            "keywords_late": list(d.get("late_keywords") or []),
            "note": d.get("note") or "",
        }
        for d in drafts
    ]
    return CardContentSpec(
        id=uuid.uuid4(),
        shop_id=shop_id,
        spec_type=SPEC_TITLE,
        proposal_id=None,
        item_id=item_id,
        schema_version=SCHEMA_VERSION,
        inputs_hash=canonical_hash(inputs),
        spec={"inputs": inputs, "candidates": candidates, "chosen": None, "model": model},
        source=SOURCE_LLM,
        llm_call_id=None,
        created_by_user_id=user_id,
        created_at=now,
    )


__all__ = [
    "SAMPLE_LIVE_TITLES_PER_PRODUCT",
    "SEEDED_MODEL",
    "TITLE_CANDIDATES",
    "SeededSpecs",
    "banner_spec",
    "canonical_hash",
    "has_seeded",
    "latest_title",
    "live_titles_used",
    "llm_title_row",
    "seed_content_specs",
    "style_profile",
    "title_spec",
]
