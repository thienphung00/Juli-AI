"""Card references on the analytics payloads (contract 8: "Xem phân tích" and back).

A Shopee card carries the critical metric it answers, the flow / lever, the product and the
đồng at stake. The screens of ``services/shopee_analytics`` (Phân tích, Sản phẩm, Xếp hạng, the
product x source matrix) show the best open card next to the row it answers:

    row["card"] = {"id", "family", "title", "at_stake_per_month"}

Only open cards count: ``sent`` / ``changes_requested`` / ``approved`` for the seller, plus
``draft`` for Ops (the seller never sees a draft). A row without a card has no ``card`` key.
Matching, strongest first: the card's own critical item id; the same product with the same
metric (and flow / source when the row names one); the same product. Among equals the card the
ranking put first wins. The analytics package stays unaware of this one: the routes call
:func:`attach_card_refs` on the payload a query returned.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shop_proposals import (
    STATUS_APPROVED,
    STATUS_CHANGES_REQUESTED,
    STATUS_DRAFT,
    STATUS_SENT,
)
from juli_backend.services.shopee_recommendations import config, store

SELLER_STATUSES = (STATUS_SENT, STATUS_CHANGES_REQUESTED, STATUS_APPROVED)
OPS_STATUSES = (STATUS_DRAFT, *SELLER_STATUSES)
#: ranking ``xep_theo`` -> the critical metric it is about
XEP_KPI = {"bien": "bien", "aov": "aov", "orders": "orders"}
SCREENS = ("matrix", "critical", "ranking", "product")


@dataclass(frozen=True)
class CardRef:
    id: str
    family: str
    title: str
    at_stake_per_month: float | None
    position: int
    products: tuple[str, ...]
    campaign: str | None
    kpi: str | None
    flow: str | None
    critical_id: str | None

    def json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "family": self.family,
            "title": self.title,
            "at_stake_per_month": self.at_stake_per_month,
        }


def _at_stake(card: dict[str, Any]) -> float | None:
    m = card.get("metric") or {}
    if m.get("at_stake_per_month") is not None:
        return float(m["at_stake_per_month"])
    if m.get("at_stake_per_day") is not None:
        return float(m["at_stake_per_day"]) * config.DAYS_PER_MONTH
    try:  # an opportunity card: no critical item, so the cautious-middle predicted dGMV
        return float(card["predicted"]["money_per_month"]["total"]["p50"]["dgmv"])
    except (KeyError, TypeError):
        return None


def _ref(card_id: uuid.UUID, card: dict[str, Any]) -> CardRef:
    m = card.get("metric") or {}
    return CardRef(
        id=str(card_id),
        family=card["family"],
        title=card["title"],
        at_stake_per_month=_at_stake(card),
        position=int((card.get("rank") or {}).get("position") or 10**6),
        products=tuple(str(p) for p in (card.get("scope") or {}).get("product_ids", [])),
        campaign=(card.get("scope") or {}).get("campaign_key"),
        kpi=m.get("critical_kpi") or card.get("wiring_key"),
        flow=m.get("flow"),
        critical_id=m.get("critical_id"),
    )


class CardIndex:
    def __init__(self, refs: list[CardRef]) -> None:
        self.refs = refs

    def _best(self, tiers: list[tuple[int, CardRef]]) -> dict[str, Any] | None:
        if not tiers:
            return None
        tiers.sort(key=lambda t: (t[0], t[1].position, -(t[1].at_stake_per_month or 0), t[1].id))
        return tiers[0][1].json()

    def for_critical(self, item: dict[str, Any]) -> dict[str, Any] | None:
        tiers = []
        for r in self.refs:
            if r.critical_id == item.get("id"):
                tiers.append((0, r))
            elif r.kpi == item.get("kpi") and item.get("product_id") in r.products:
                tiers.append((1, r))
        return self._best(tiers)

    def for_product(
        self, product_id: str, *, kpi: str | None = None, source: str | None = None
    ) -> dict[str, Any] | None:
        tiers = []
        for r in self.refs:
            if product_id not in r.products:
                continue
            by_kpi = kpi is not None and r.kpi == kpi
            by_source = source not in (None, "all") and r.flow == source
            tier = 2 - int(by_kpi) - int(by_source)
            tiers.append((tier, r))
        return self._best(tiers)

    def all_for_product(self, product_id: str) -> list[dict[str, Any]]:
        mine = sorted(
            (r for r in self.refs if product_id in r.products), key=lambda r: (r.position, r.id)
        )
        return [r.json() for r in mine]

    def for_campaign(self, key: str) -> dict[str, Any] | None:
        return self._best([(0, r) for r in self.refs if r.campaign and r.campaign == key])


async def load_index(session: AsyncSession, shop_id: uuid.UUID, *, audience: str) -> CardIndex:
    statuses = OPS_STATUSES if audience == "ops" else SELLER_STATUSES
    rows = await store.list_cards(session, shop_id, statuses=statuses)
    return CardIndex([_ref(p.id, card) for p, card in rows])


def _put(row: dict[str, Any], ref: dict[str, Any] | None) -> int:
    if ref is None:
        return 0
    row["card"] = ref
    return 1


def attach(index: CardIndex, screen: str, payload: dict[str, Any]) -> int:
    """Add ``card`` to the rows of ``payload`` in place; returns how many rows got one."""
    if screen not in SCREENS:
        raise ValueError(f"screen must be one of {list(SCREENS)}")
    n = 0
    if screen == "matrix":
        for row in payload.get("products", []):
            n += _put(row, index.for_product(str(row["product_id"])))
    elif screen == "critical":
        for item in payload.get("items", []):
            n += _put(item, index.for_critical(item))
    elif screen == "product":
        pid = str(payload["header"]["product_id"])
        n += _put(payload, index.for_product(pid))
        payload["cards"] = index.all_for_product(pid)
    elif screen == "ranking" and payload.get("supported"):
        kind, source = payload.get("kind"), payload.get("source")
        kpi = XEP_KPI.get((payload.get("xep_theo") or {}).get("key", ""))
        seen: set[int] = set()
        rows = [
            *payload.get("down", []),
            *payload.get("up", []),
            *[r for v in (payload.get("views") or {}).values() for r in v.get("rows", [])],
        ]
        for row in rows:
            if id(row) in seen:
                continue
            seen.add(id(row))
            if kind == "products":
                n += _put(row, index.for_product(str(row["id"]), kpi=kpi, source=source))
            elif kind == "campaigns":
                n += _put(row, index.for_campaign(str(row["id"])))
    return n


async def attach_card_refs(
    session: AsyncSession,
    shop_id: uuid.UUID,
    screen: str,
    payload: dict[str, Any],
    *,
    audience: str,
) -> dict[str, Any]:
    """``payload`` with ``card`` on the rows that have an open card (seller: published only)."""
    attach(await load_index(session, shop_id, audience=audience), screen, payload)
    return payload
