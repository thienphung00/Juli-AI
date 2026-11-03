"""Dataset names the loader parses but the gateway does not accept yet.

Two Seller Centre exports have no home in ``platform_period_metrics`` /
``platform_daily_metrics`` / ``platform_promotions`` (ADR-117 §1-§3):

- ``affiliate_order_lines`` -- ``SellerConversionReport_<ts>.csv``: one row per affiliate
  order LINE. It belongs in ``shopee_order_lines`` (migration 112, another lane) with
  ``affiliate = true`` and the commission fields. The raw order id never leaves the
  parser: ``order_ref`` is a keyed hash (``scripts.shopee_exports.parse.order_ref``).
- ``ads_change_log`` -- ``ops_log_*.csv``: the ad change history (budget changes, product
  changes, Shopee's automatic surge optimisation). Append-only events; needs a table.

TODO(migration 112 / ad change log table): when the table and its dataset spec exist, move the
row model into ``schemas.py``, register the spec in ``mapping.DATASETS`` and delete the name
from :data:`RESERVED_DATASETS`. Until then the loader validates these bodies here, prints
their counts under "reserved", and never sends them (the gateway answers 404 for the name).

No buyer data: the models have no field for a buyer's name, phone or address.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from pydantic import Field, StringConstraints

from juli_backend.services.ingest.schemas import (
    Count,
    IngestBody,
    ItemId,
    Money,
    PeriodRowBase,
    Rate,
)

Text64 = Annotated[str, StringConstraints(max_length=64)]
Text120 = Annotated[str, StringConstraints(max_length=120)]


class ShopeeAffiliateOrderLineRow(PeriodRowBase):
    """``affiliate_order_lines``: one affiliate-attributed order line, ready for
    ``shopee_order_lines`` (``affiliate`` is always true)."""

    #: Keyed hash of the order id (HMAC-SHA256, 32 hex): the same function the browser-side
    #: order strip uses, so the two lanes agree on an order.
    order_ref: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
    #: Place among lines sharing order, item and model in one export.
    line_no: Annotated[int, Field(ge=0, le=999)] = 0
    affiliate: bool = True
    item_id: ItemId
    model_id: Annotated[str, StringConstraints(pattern=r"^[0-9]{0,32}$")] = ""
    price: Money | None = None
    qty: Count | None = None
    order_value: Money | None = None
    refund_amount: Money | None = None
    order_status: Text64 | None = None
    #: False when the platform's fraud check did not say "valid".
    valid: bool | None = None
    ordered_at: datetime
    completed_at: datetime | None = None
    conversion_at: datetime | None = None
    campaign_type: Text64 | None = None
    campaign_partner: Text120 | None = None
    commission_code: Text64 | None = None
    #: The creator's public display name and handle (not a buyer).
    partner_name: Text120 | None = None
    affiliate_account: Text120 | None = None
    mcn: Text120 | None = None
    order_kind: Text64 | None = None
    channel: Text64 | None = None
    xtra_product_commission: Money | None = None
    xtra_product_commission_kols: Money | None = None
    xtra_product_commission_kols_rate: Rate | None = None
    xtra_product_commission_mcn: Money | None = None
    xtra_product_commission_mcn_rate: Rate | None = None
    xtra_order_commission: Money | None = None
    xtra_order_commission_kols: Money | None = None
    xtra_order_commission_mcn: Money | None = None
    cost: Money | None = None
    deduction_status: Text64 | None = None
    deduction_method: Text64 | None = None
    deducted_at: datetime | None = None

    def key(self) -> tuple[Any, ...]:
        return (self.order_ref, self.item_id, self.model_id, self.line_no)


class ShopeeAdsChangeLogRow(PeriodRowBase):
    """``ads_change_log``: one line of an ad campaign's change history (``ops_log_*.csv``).
    Times are Seller Centre's wall clock (GMT+7)."""

    campaign_id: Annotated[str, StringConstraints(pattern=r"^[0-9]{1,32}$")]
    item_id: ItemId | None = None
    occurred_at: datetime
    #: ``system`` = Shopee's own optimiser; ``user`` = a person or sub-account of the shop.
    actor_kind: Annotated[str, StringConstraints(pattern=r"^(system|user)$")]
    actor: Text120 | None = None
    surface: Text64 | None = None
    event_type: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    detail: Annotated[str, StringConstraints(max_length=500)] | None = None
    #: Parsed from "Ngân sách hàng ngày: ₫a -> ₫b".
    budget_from: Money | None = None
    budget_to: Money | None = None
    #: Parsed from "Thay đổi số lượng sản phẩm …: a -> b".
    products_from: Count | None = None
    products_to: Count | None = None
    ordinal: Annotated[int, Field(ge=0, le=999)] = 0

    def key(self) -> tuple[Any, ...]:
        return (self.campaign_id, self.occurred_at, self.event_type, self.ordinal)


@dataclass(frozen=True)
class ReservedDataset:
    name: str
    row_model: type[PeriodRowBase]
    #: Where the rows are meant to land once the gateway accepts the name.
    target: str


RESERVED_DATASETS: dict[str, ReservedDataset] = {
    "affiliate_order_lines": ReservedDataset(
        "affiliate_order_lines", ShopeeAffiliateOrderLineRow, "shopee_order_lines (migration 112)"
    ),
    "ads_change_log": ReservedDataset(
        "ads_change_log", ShopeeAdsChangeLogRow, "an ad change log table (no migration yet)"
    ),
}


def validate_reserved(dataset: str, body: IngestBody) -> None:
    """Validate a reserved body's rows (and refuse duplicate keys) like ``validate_rows``;
    raises ``pydantic.ValidationError`` or ``ValueError``."""
    spec = RESERVED_DATASETS[dataset]
    seen: set[tuple[Any, ...]] = set()
    for raw in body.rows:
        row = spec.row_model.model_validate(raw)
        key = row.key()
        if key in seen:
            raise ValueError(f"duplicate row key in {dataset}")
        seen.add(key)
