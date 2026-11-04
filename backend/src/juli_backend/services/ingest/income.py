"""Writer of the ``order_income`` dataset: ``shopee_order_income`` (migration 117, P91 D-12).

One row per (shop, platform, order). A later post of the same order replaces the row when its
source ranks the same or higher (file over extension, as ``gateway._upsert``); a column the
later post does not state (NULL) never erases one already stored.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import SOURCE_RANK
from juli_backend.models.shopee_profit import ShopeeOrderIncome
from juli_backend.services.ingest.schemas import IngestBody, ShopeeOrderIncomeRow

CHUNK = 400
KEY_COLUMNS = ("shop_id", "platform", "order_ref")
#: Row fields copied to same-named columns.
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
STATED_COLUMNS: tuple[str, ...] = ("ordered_on", "paid_on", *AMOUNT_FIELDS)


def _insert(session: AsyncSession) -> Any:
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        return pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    return sqlite_insert


def _stored_rank(table: Any) -> Any:
    return case(
        *[(table.c.source == source, rank) for source, rank in SOURCE_RANK.items()],
        else_=table.c.source_rank,
    )


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
            value[name] = amount
        out.append(value)
    return out


async def write_order_income(
    session: AsyncSession,
    rows: list[ShopeeOrderIncomeRow],
    body: IngestBody,
    provenance: dict[str, Any],
) -> None:
    if not rows:
        return
    insert = _insert(session)
    table = ShopeeOrderIncome.__table__
    values = income_values(rows, provenance)
    for start in range(0, len(values), CHUNK):
        stmt = insert(ShopeeOrderIncome).values(values[start : start + CHUNK])
        updated: dict[str, Any] = {
            column: func.coalesce(stmt.excluded[column], table.c[column])
            for column in STATED_COLUMNS
        }
        updated.update(
            {
                column: stmt.excluded[column]
                for column in ("source", "source_rank", "source_version", "raw_payload_id")
            }
        )
        updated["updated_at"] = stmt.excluded["updated_at"]
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=list(KEY_COLUMNS),
                set_=updated,
                where=_stored_rank(table) <= stmt.excluded.source_rank,
            )
        )
