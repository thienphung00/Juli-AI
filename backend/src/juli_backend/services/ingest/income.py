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

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import SOURCE_EXTENSION
from juli_backend.models.shopee_profit import ShopeeOrderIncome, ShopeeOrderLine
from juli_backend.services.ingest.precedence import count_gap_fills, log_gap_fills
from juli_backend.services.ingest.rank_guard import (
    excluded_payload_captured_at,
    payload_captured_at,
    ranked_set,
    ranked_where,
)
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
#: ``fee_other`` has no wire field (the TikTok mapper fills it through ``DbCanonicalWriter``).
STATED_COLUMNS: tuple[str, ...] = ("ordered_on", "paid_on", *AMOUNT_COLUMNS, "fee_other")
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
            "fee_other": None,
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
    await upsert_settlement_values(session, income_values(rows, provenance))
    await split_buyer_vouchers(session, rows, provenance)
    return warnings


#: batch-1124-a S1: the buyer-side voucher of an income row -> the ``order_lines`` column it fills.
BUYER_VOUCHER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("buyer_shop_voucher", "shop_voucher_share"),
    ("buyer_platform_voucher", "platform_voucher_share"),
)
CENT = Decimal("0.01")


def _shares(amount: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """``amount`` split by ``weights`` to the cent; the last share takes the rounding rest."""
    total = sum(weights, Decimal(0))
    if total <= 0:
        return []
    out = [(amount * w / total).quantize(CENT) for w in weights[:-1]]
    return [*out, amount - sum(out, Decimal(0))]


async def split_buyer_vouchers(
    session: AsyncSession, rows: list[ShopeeOrderIncomeRow], provenance: dict[str, Any]
) -> int:
    """batch-1124-a S1 (owner 2026-11-24, rule B): the Connector's buyer-side shop / Shopee voucher
    of an order is split onto that order's lines by line value (``deal_price x qty``). It may
    overwrite only a 0 that a Connector line post wrote (line ``source`` = extension); a file
    import's value, or any non-zero, is never touched. Each fill is logged with the income post's
    raw payload (``order_line_voucher_split``) so it can be audited. Returns the lines filled."""
    if provenance["source"] != SOURCE_EXTENSION:
        return 0
    wanted = {
        row.order_ref: row
        for row in rows
        if any(getattr(row, field) for field, _ in BUYER_VOUCHER_COLUMNS)
    }
    if not wanted:
        return 0
    table = ShopeeOrderLine.__table__
    found = await session.execute(
        select(
            table.c.id,
            table.c.order_ref,
            table.c.deal_price,
            table.c.qty,
            table.c.source,
            table.c.shop_voucher_share,
            table.c.platform_voucher_share,
        )
        .where(
            table.c.shop_id == provenance["shop_id"],
            table.c.platform == provenance["platform"],
            table.c.order_ref.in_(sorted(wanted)),
        )
        .order_by(table.c.order_ref, table.c.line_no)
    )
    lines: dict[str, list[Any]] = {}
    for line in found:
        lines.setdefault(line.order_ref, []).append(line)
    filled = 0
    for ref, row in wanted.items():
        order_lines = lines.get(ref, [])
        weights = [Decimal(line.deal_price) * line.qty for line in order_lines]
        for field, column in BUYER_VOUCHER_COLUMNS:
            amount: Decimal | None = getattr(row, field)
            if not amount:
                continue
            # rule B: every line of the order must still hold the Connector's 0, else none moves
            if not order_lines or any(
                line.source != SOURCE_EXTENSION or getattr(line, column) != 0
                for line in order_lines
            ):
                continue
            for line, share in zip(order_lines, _shares(amount, weights), strict=True):
                await session.execute(
                    update(ShopeeOrderLine)
                    .where(ShopeeOrderLine.id == line.id, getattr(ShopeeOrderLine, column) == 0)
                    .values({column: share, "updated_at": provenance["updated_at"]})
                )
                filled += 1
    if filled:
        logger.info(
            "order_line_voucher_split",
            extra={
                "shop_id": str(provenance["shop_id"]),
                "lines": filled,
                "raw_payload_id": str(provenance["raw_payload_id"]),
            },
        )
    return filled


async def upsert_settlement_values(session: AsyncSession, values: list[dict[str, Any]]) -> None:
    """The one ``order_settlements`` upsert (the gateway and ``DbCanonicalWriter`` share it)."""
    insert = _insert(session)
    table = ShopeeOrderIncome.__table__
    for start in range(0, len(values), CHUNK):
        part = values[start : start + CHUNK]
        found = await count_gap_fills(session, ShopeeOrderIncome, KEY_COLUMNS, part, STATED_COLUMNS)
        log_gap_fills(ShopeeOrderIncome.__tablename__, part[0]["shop_id"], part[0]["source"], found)
        stmt = insert(ShopeeOrderIncome).values(part)
        # owner 2026-11-18 + R7 (``rank_guard.ranked_set``): a higher rank replaces with its
        # stated values (a NULL keeps the stored one), an equal rank too unless its capture is
        # older (then it is ignored), a lower rank only fills NULL columns; the provenance stays
        # with the winning writer. This table keeps no capture time: both sides compare their
        # raw payloads'.
        stored_captured = payload_captured_at(table)
        incoming_captured = excluded_payload_captured_at()
        updated = ranked_set(
            table,
            stmt.excluded,
            (*STATED_COLUMNS, *PROVENANCE_COLUMNS),
            PROVENANCE_COLUMNS,
            stored_captured=stored_captured,
            incoming_captured=incoming_captured,
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=list(KEY_COLUMNS),
                set_=updated,
                where=ranked_where(
                    table,
                    stmt.excluded,
                    stored_captured=stored_captured,
                    incoming_captured=incoming_captured,
                ),
            )
        )
