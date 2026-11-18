"""Writer of the ``order_income`` dataset: ``order_settlements`` (migration 119, P91 D-12; named
``shopee_order_income`` until migration 134).

One row per (shop, platform, order). A later post of the same order replaces the row when its
source ranks the same or higher (extension over file, as ``gateway._upsert``); a column the
later post does not state (NULL) never erases one already stored.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shopee_profit import ShopeeOrderIncome
from juli_backend.services.ingest.precedence import count_gap_fills, log_gap_fills, ranked_value
from juli_backend.services.ingest.schemas import IngestBody, ShopeeOrderIncomeRow

logger = logging.getLogger(__name__)

CHUNK = 400
KEY_COLUMNS = ("shop_id", "platform", "order_ref")
#: Row fields copied to the column of the same name (or of :data:`COLUMN_OF`'s name).
AMOUNT_FIELDS: tuple[str, ...] = (
    "payout",
    "product_price",
    "refund_amount",
    "fee_fixed",
    "fee_service",
    "fee_infra",
    "fee_voucher_xtra",
    "fee_payment",
    "fee_piship",
    "fee_nttd",
    "affiliate_commission",
    "ship_actual_cost",
    "ship_shopee_subsidy",
    "ship_buyer_paid",
    "ship_piship_refund",
    "ship_seller_support",
    "net_shipping_cost",
    "return_ship_refund",
    "return_ship_failed",
    "lost_compensation",
    "vat_withheld",
    "pit_withheld",
    "seller_voucher_borne",
    "seller_coin_borne",
    "trade_in_bonus_seller",
    "transaction_fee_rate",
)
#: Migration 134: a wire field whose column has a platform-neutral name.
COLUMN_OF: dict[str, str] = {"ship_shopee_subsidy": "ship_platform_subsidy"}
AMOUNT_COLUMNS: tuple[str, ...] = tuple(COLUMN_OF.get(name, name) for name in AMOUNT_FIELDS)
STATED_COLUMNS: tuple[str, ...] = ("ordered_on", "paid_on", *AMOUNT_COLUMNS)
#: describe the post: they stay with the highest-ranked writer
PROVENANCE_COLUMNS = ("source", "source_rank", "source_version", "raw_payload_id", "updated_at")


def _insert(session: AsyncSession) -> Any:
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        return pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    return sqlite_insert


def income_values(
    rows: list[ShopeeOrderIncomeRow], provenance: dict[str, Any]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        value: dict[str, Any] = {
            "id": uuid.uuid4(),
            "shop_id": provenance["shop_id"],
            "platform": provenance["platform"],
            "order_ref": row.order_ref,
            "ordered_on": row.ordered_on,
            "paid_on": row.paid_on,
            "source": provenance["source"],
            "source_rank": provenance["source_rank"],
            "source_version": provenance["source_version"],
            "raw_payload_id": provenance["raw_payload_id"],
            "updated_at": provenance["updated_at"],
        }
        for name in AMOUNT_FIELDS:
            amount: Decimal | None = getattr(row, name)
            value[COLUMN_OF.get(name, name)] = amount
        out.append(value)
    return out


#: Warning code returned to the sender (and logged) the first time a shop's income export carries
#: a non-zero "Phí vận chuyển - Người bán hỗ trợ" (P91 D-14): the amount is stored for reference
#: and is NOT subtracted from the profit, so Ops must look at it before anyone relies on the
#: shipping figure.
WARN_SELLER_SUPPORT_SHIPPING = "seller_support_shipping_nonzero"


async def _seller_support_warning(
    session: AsyncSession, rows: list[ShopeeOrderIncomeRow], provenance: dict[str, Any]
) -> list[str]:
    """``[WARN_SELLER_SUPPORT_SHIPPING]`` when these rows hold a non-zero seller-support shipping
    value and the shop has never stored one before; else ``[]``."""
    carrying = sum(1 for r in rows if r.ship_seller_support)
    if not carrying:
        return []
    table = ShopeeOrderIncome.__table__
    earlier = await session.scalar(
        select(table.c.id)
        .where(
            table.c.shop_id == provenance["shop_id"],
            table.c.platform == provenance["platform"],
            table.c.ship_seller_support.is_not(None),
            table.c.ship_seller_support != 0,
        )
        .limit(1)
    )
    if earlier is not None:
        return []
    logger.warning(
        "income_seller_support_shipping_nonzero",
        extra={"shop_id": str(provenance["shop_id"]), "orders": carrying},
    )
    return [WARN_SELLER_SUPPORT_SHIPPING]


async def write_order_income(
    session: AsyncSession,
    rows: list[ShopeeOrderIncomeRow],
    body: IngestBody,
    provenance: dict[str, Any],
) -> list[str]:
    """Upsert the rows; returns the warning codes for the sender (see ``WARN_*``)."""
    if not rows:
        return []
    warnings = await _seller_support_warning(session, rows, provenance)
    insert = _insert(session)
    table = ShopeeOrderIncome.__table__
    values = income_values(rows, provenance)
    for start in range(0, len(values), CHUNK):
        part = values[start : start + CHUNK]
        found = await count_gap_fills(session, ShopeeOrderIncome, KEY_COLUMNS, part, STATED_COLUMNS)
        log_gap_fills(
            ShopeeOrderIncome.__tablename__, provenance["shop_id"], provenance["source"], found
        )
        stmt = insert(ShopeeOrderIncome).values(part)
        # owner 2026-11-18: the same or a higher rank replaces with its stated values (a NULL
        # keeps the stored one); a lower rank only fills NULL columns and the provenance stays
        # with the higher writer (``precedence.ranked_value``)
        updated: dict[str, Any] = {
            column: ranked_value(stmt, table, column) for column in STATED_COLUMNS
        }
        updated.update(
            {
                column: ranked_value(stmt, table, column, provenance=True)
                for column in PROVENANCE_COLUMNS
            }
        )
        await session.execute(
            stmt.on_conflict_do_update(index_elements=list(KEY_COLUMNS), set_=updated)
        )
    return warnings
