"""The "Mẫu KOL" sheet and the samples it stores (P91 D-9, D-11).

One shipment = ``{handle, qty, sent_on, ship_fee}``. The shipments sent to one KOL for one
product live in ONE ``kol_sample`` shop rule (scope ``kol:<kol_key>:<SKU scope>``), so the
sheet is versioned, diffed and restored with the same machinery as the SKU sheet
(``shop_rule_versions``). The sheet is the full state of the pairs it lists: a listed pair's
shipments are replaced by the sheet's rows; a pair the sheet does not list is untouched;
``Số lượng mẫu`` 0 on every row of a pair clears it; a row with no quantity and nothing else
means "no sample sent" and is ignored.

SAMPLE COST (owner, D-9): ``qty x (giá vốn + đóng gói) + phí ship``; no KOL booking fee. The
unit cost is the SKU's ``sku_cost`` (else the item's ``product_cost``); with neither it is 1/3
of the list price, labelled ``assumed`` (the same fallback as every profit figure); packaging
is the imported ``packaging_cost`` else 0, labelled ``assumed``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.run_changes import ShopRule
from juli_backend.services.ingest.kol_key import kol_key
from juli_backend.services.shop_inputs.catalogue import CatalogueSku, CurrentInputs
from juli_backend.services.shop_rules.rules import KOL_SAMPLE, PACKAGING, SKU_COST

SCOPE_PREFIX = "kol:"
SAMPLE_SHEET = "Mẫu KOL"
FALLBACK_COGS_RATIO = Decimal(1) / Decimal(3)
SRC_REAL = "real"
SRC_ASSUMED = "assumed"

#: (header, required, key) of the sheet; keys are the importer's field names.
SAMPLE_COLUMNS: tuple[tuple[str, bool, str], ...] = (
    ("KOL (tay cầm)", True, "kol"),
    ("Sản phẩm (mã SP hoặc SKU)", True, "product"),
    ("Số lượng mẫu", False, "qty"),
    ("Ngày gửi", False, "sent_on"),
    ("Phí ship gửi mẫu", False, "ship_fee"),
    ("Ghi chú", False, "note"),
)
NOTE_SAMPLE = (
    "Chi phí mẫu = số lượng × (giá vốn + đóng gói của sản phẩm) + phí ship. Không có cột phí book "
    "KOL: phí này không tính vào chi phí mẫu. Bỏ trống số lượng nghĩa là chưa gửi mẫu. Ngày gửi: "
    "dd/mm/yyyy. Mỗi lần gửi một dòng."
)


def scope_ref(handle_key: str, sku_scope: str) -> str:
    return f"{SCOPE_PREFIX}{handle_key}:{sku_scope}"


def split_sample_scope(ref: str) -> tuple[str, str]:
    """``kol:<key>:<item>[:<variation>]`` -> ``(kol_key, sku scope)``."""
    body = ref.removeprefix(SCOPE_PREFIX)
    key, _, sku = body.partition(":")
    return key, sku


def is_sample_scope(ref: str) -> bool:
    return ref.startswith(SCOPE_PREFIX)


@dataclass(frozen=True)
class Shipment:
    handle: str
    qty: int
    sent_on: date
    ship_fee: Decimal

    def json(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "qty": self.qty,
            "sent_on": self.sent_on.isoformat(),
            "ship_fee": float(self.ship_fee),
        }


def _shipment(raw: dict[str, Any]) -> Shipment:
    return Shipment(
        str(raw["handle"]),
        int(raw["qty"]),
        date.fromisoformat(str(raw["sent_on"])),
        Decimal(str(raw.get("ship_fee", 0))),
    )


@dataclass(frozen=True)
class UnitCost:
    cogs: Decimal
    packaging: Decimal
    cogs_source: str
    packaging_source: str

    @property
    def total(self) -> Decimal:
        return self.cogs + self.packaging

    @property
    def label(self) -> str:
        if self.cogs_source == SRC_REAL:
            return "giá vốn đã nhập"
        return "giá vốn giả định (1/3 giá niêm yết)"


def unit_cost(
    *,
    sku_scope: str,
    item_id: str,
    list_price: Decimal | None,
    sku_cost: dict[str, Any],
    product_cost: dict[str, Any],
    packaging: dict[str, Any],
) -> UnitCost | None:
    """giá vốn + đóng gói of one unit; ``None`` when there is no cost and no list price."""
    raw = sku_cost.get(sku_scope)
    if raw is None:
        raw = product_cost.get(item_id)
    src = SRC_REAL
    if raw is None:
        if list_price is None or list_price <= 0:
            return None
        cogs, src = (list_price * FALLBACK_COGS_RATIO).quantize(Decimal(1)), SRC_ASSUMED
    else:
        cogs = Decimal(str(raw))
    pack_raw = packaging.get(sku_scope)
    if pack_raw is None:
        pack_raw = packaging.get(item_id)
    if pack_raw is None:
        return UnitCost(cogs, Decimal(0), src, SRC_ASSUMED)
    return UnitCost(cogs, Decimal(str(pack_raw)), src, SRC_REAL)


def sample_cost(shipments: list[Shipment], unit: UnitCost | None) -> Decimal | None:
    """qty x (giá vốn + đóng gói) + phí ship, summed over shipments; ``None`` without a cost."""
    if unit is None:
        return None
    return sum((s.qty * unit.total + s.ship_fee for s in shipments), Decimal(0))


def unit_cost_from_inputs(
    current: CurrentInputs, sku: CatalogueSku | None, sku_scope: str, item_id: str
) -> UnitCost | None:
    sku_cost = {k: v[SKU_COST] for k, v in current.per_sku.items() if SKU_COST in v}
    packaging = {k: v[PACKAGING] for k, v in current.per_sku.items() if PACKAGING in v}
    return unit_cost(
        sku_scope=sku_scope,
        item_id=item_id,
        list_price=sku.list_price if sku else None,
        sku_cost=sku_cost,
        product_cost=current.product_cost,
        packaging=packaging,
    )


async def load_samples(
    session: AsyncSession, shop_id: uuid.UUID
) -> dict[tuple[str, str], list[Shipment]]:
    """``(kol_key, SKU scope) -> shipments`` for every pair with at least one shipment."""
    rows = (
        (
            await session.execute(
                select(ShopRule).where(ShopRule.shop_id == shop_id, ShopRule.rule_key == KOL_SAMPLE)
            )
        )
        .scalars()
        .all()
    )
    out: dict[tuple[str, str], list[Shipment]] = {}
    for row in rows:
        if not isinstance(row.value, list) or not row.value:
            continue
        key, sku = split_sample_scope(row.scope_ref)
        out[(key, sku)] = [_shipment(e) for e in row.value]
    return out


def make_key(handle: str) -> str:
    return kol_key(handle)


@dataclass(frozen=True)
class SampleDiff:
    """One KOL x product whose shipments the sheet changes."""

    scope_ref: str
    kol_key: str
    handle: str
    item_id: str
    sku: str
    old: list[dict[str, Any]]
    new: list[dict[str, Any]]
    old_cost: Decimal | None
    new_cost: Decimal | None
    cost_label: str

    @property
    def tag(self) -> str:
        if not self.old:
            return "Mới"
        return "Xoá" if not self.new else "Đổi"

    @property
    def effect(self) -> str:
        def money(v: Decimal | None) -> str:
            return "(chưa có giá vốn)" if v is None else f"{int(v):,}đ".replace(",", ".")

        return f"Chi phí mẫu {money(self.old_cost)} → {money(self.new_cost)} ({self.cost_label})"


@dataclass
class SampleSheetResult:
    rows: int = 0
    rows_rejected: int = 0
    rows_unchanged: int = 0
    diffs: list[SampleDiff] = field(default_factory=list)


async def known_pairs(
    session: AsyncSession, shop_id: uuid.UUID, *, limit: int = 300
) -> list[tuple[str, str]]:
    """``(handle, item_id)`` of the KOL x product pairs with at least one marked order line."""
    from sqlalchemy import func

    from juli_backend.models.shopee_profit import ShopeeOrderLine as L

    rows = await session.execute(
        select(func.min(L.kol_handle), L.item_id)
        .where(L.shop_id == shop_id, L.kol_key.is_not(None))
        .group_by(L.kol_key, L.item_id)
        .order_by(func.count().desc(), L.item_id)
        .limit(limit)
    )
    return [(h, i) for h, i in rows if h]
