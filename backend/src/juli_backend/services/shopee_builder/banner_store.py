"""Ảnh bìa banners: what the editor opens with, and saving the seller's banner (E.7 store).

``banner_context`` gives the editor the product (name, the real cover, price), the colours the
shop's style profile allows, the stored spec of the card when there is one (latest wins), and the
values Juli can fill from a card or the listing, each with its source. ``save_banner`` validates a
spec, fills its rule checks and appends a ``source='seller'`` row to ``card_content_specs``
(append-only: an edit is a new row, history stays).

Nothing is generated and nothing leaves Juli: the PNG is rendered in the browser.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.card_content_specs import (
    SCHEMA_VERSION,
    SOURCE_SELLER,
    SPEC_BANNER,
    SPEC_STYLE_PROFILE,
    CardContentSpec,
)
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.services.shopee_builder import banner as bn
from juli_backend.services.shopee_builder.service import NoShopeeData
from juli_backend.services.shopee_recommendations import listing as lst
from juli_backend.services.shopee_recommendations import loader, store

VOUCHER_KINDS = frozenset({"min_spend_voucher", "review_voucher", "voucher_cap"})


class BannerRefused(Exception):
    """A banner the store will not take: ``code`` is the API error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _latest(
    session: AsyncSession, shop_id: uuid.UUID, spec_type: str, proposal_id: uuid.UUID | None
) -> CardContentSpec | None:
    stmt = select(CardContentSpec).where(
        CardContentSpec.shop_id == shop_id, CardContentSpec.spec_type == spec_type
    )
    if spec_type != SPEC_STYLE_PROFILE:
        stmt = stmt.where(CardContentSpec.proposal_id == proposal_id)
    return await session.scalar(stmt.order_by(CardContentSpec.created_at.desc()).limit(1))


async def _card(
    session: AsyncSession, shop_id: uuid.UUID, card_id: uuid.UUID, item_id: str
) -> ShopProposal:
    row = await session.scalar(
        select(ShopProposal).where(ShopProposal.id == card_id, ShopProposal.shop_id == shop_id)
    )
    if row is None:
        raise BannerRefused("card_not_found", "Không có thẻ này")
    if row.item_id is not None and row.item_id != item_id:
        raise BannerRefused("card_other_product", "Thẻ này thuộc sản phẩm khác")
    return row


def _card_values(card: dict[str, Any], card_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    """Prefill from the card's own change: a voucher card fills the Voucher banner."""
    out: dict[str, dict[str, Any]] = {}
    if card.get("change_kind") in VOUCHER_KINDS:
        after = (card.get("change") or {}).get("after") or {}
        values = {"value": after.get("value"), "min": after.get("min_spend")}
        out["voucher"] = {
            "values": {k: v for k, v in values.items() if isinstance(v, int | float)},
            "sources": {
                k: {"card_id": str(card_id), "field": f"change.after.{f}"}
                for k, f in (("value", "value"), ("min", "min_spend"))
                if isinstance(values[k], int | float)
            },
        }
    return out


async def banner_context(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    item_id: str,
    card_id: uuid.UUID | None,
    as_of: date | None,
    now: datetime,
) -> dict[str, Any]:
    env = await loader.load_env(session, shop_id, as_of=as_of, now=now)
    if env is None:
        raise NoShopeeData(str(shop_id))
    if item_id not in env.ctx.catalog.items and env.orders_of(item_id) <= 0:
        raise LookupError(item_id)
    li = env.listings.get(item_id)
    name = (li.title if li and li.title else None) or env.name(item_id)
    price = int(li.price) if li and li.price else None

    prefill: dict[str, dict[str, Any]] = {}
    if price:
        prefill["unit"] = {
            "values": {"price": price},
            "sources": {"price": {"card_id": None, "field": "item.price"}},
        }
    size = lst.unit_price(name, li.price if li else None)
    if size is not None:
        prefill["quy_cach"] = {
            "values": {"text": size.size_text},
            "sources": {"text": {"card_id": None, "field": "item.title"}},
        }
    for v in env.vouchers:
        if v.value is None or (v.ends_at and v.ends_at[:10] < env.as_of.isoformat()):
            continue
        prefill["voucher"] = {
            "values": {"value": int(v.value), **({"min": int(v.min_spend)} if v.min_spend else {})},
            "sources": {
                "value": {"card_id": None, "field": "voucher_settings.value"},
                **(
                    {"min": {"card_id": None, "field": "voucher_settings.min_spend"}}
                    if v.min_spend
                    else {}
                ),
            },
        }
        break

    stored = None
    if card_id is not None:
        proposal = await _card(session, shop_id, card_id, item_id)
        frozen: dict[str, Any] | None = None
        for p, card in await store.list_cards(session, shop_id):
            if p.id == proposal.id:
                prefill.update(_card_values(card, card_id))
                after = (card.get("change") or {}).get("after") or {}
                frozen = after.get("banner") if isinstance(after.get("banner"), dict) else None
                break
        row = await _latest(session, shop_id, SPEC_BANNER, card_id)
        if row is not None:
            stored = {"spec": row.spec, "source": row.source, "created_at": row.created_at}
        elif frozen is not None:
            # a card made in Tự tạo carries its banner in the card itself until it is edited
            stored = {"spec": frozen, "source": "card", "created_at": None}

    profile_row = await _latest(session, shop_id, SPEC_STYLE_PROFILE, None)
    profile = profile_row.spec if profile_row is not None else None
    return {
        "item": {
            "item_id": item_id,
            "name": name,
            "cover_url": li.cover_url if li else None,
            "price": price,
        },
        "palette": list(bn.palette_of(profile)),
        "style_profile": profile,
        "stored": stored,
        "prefill": prefill,
    }


async def save_banner(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    item_id: str,
    card_id: uuid.UUID | None,
    spec: bn.BannerSpec,
    user_id: uuid.UUID | None,
    now: datetime,
) -> dict[str, Any]:
    """Append the seller's banner spec (rule checks filled). Caller commits."""
    if card_id is not None:
        await _card(session, shop_id, card_id, item_id)
    profile_row = await _latest(session, shop_id, SPEC_STYLE_PROFILE, None)
    palette = bn.palette_of(profile_row.spec if profile_row is not None else None)
    if bn.off_palette(spec, palette):
        raise BannerRefused("off_palette", "Màu banner phải lấy từ bảng màu của shop")
    checked = bn.with_checks(spec)
    body = checked.model_dump(mode="json")
    row = CardContentSpec(
        id=uuid.uuid4(),
        shop_id=shop_id,
        spec_type=SPEC_BANNER,
        proposal_id=card_id,
        item_id=item_id,
        schema_version=SCHEMA_VERSION,
        inputs_hash=_hash(body["banners"]),
        spec=body,
        source=SOURCE_SELLER,
        llm_call_id=None,
        created_by_user_id=user_id,
        created_at=now,
    )
    session.add(row)
    await session.flush()
    return {"id": str(row.id), "spec": body, "source": SOURCE_SELLER, "created_at": now}
