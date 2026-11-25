"""KNOWN EXCEPTION to "every number comes from `query()`": the entity SQL (voucher / no voucher /
affiliate / all) over the canonical `order_lines`, `affiliate_lines` and `order_settlements`.

Voucher facts (by code, by programme) are not stored facts in the data-layer batch (#62), so these
reads stay on named SELECTs here, in ONE place, until a voucher fact exists. `ServiceData` mixes
this class in; nothing else in `analytics_agent` reads these tables. Listed as the exception in the
CHAT evidence note.
"""

from __future__ import annotations

from datetime import date
from typing import Any


class EntitySql:
    """Mixin: needs `_q(sql, **params)` (a read-only named SELECT bound to the shop)."""

    async def _q(self, sql: str, **p: Any) -> list[dict[str, Any]]:  # provided by ServiceData
        raise NotImplementedError

    #: The shop headline basis (registry / `shopee_analytics.engine`): a confirmed line has a
    #: payment time and a quantity, and counts in đơn / GMV / AOV unless its status is a refund
    #: status (`counts_in_sales`); the day is the line's order day. Entity rows use exactly this,
    #: so they are a subset of the shop totals.
    @staticmethod
    def _sales_basis() -> str:
        from juli_backend.services.shopee_profit.order_profit import REFUND_STATUSES

        refunds = ", ".join(f"'{x.value}'" for x in sorted(REFUND_STATUSES, key=lambda x: x.value))
        return f"paid_at is not null and qty > 0 and status not in ({refunds})"

    async def entity_totals(
        self, kind: str, a: date, b: date, item: str | None = None
    ) -> dict[str, Any]:
        """Orders, GMV (deal price x qty) and the entity's own cost over [a, b], from the
        canonical `order_lines`: voucher = lines with a seller voucher share (cost = that share,
        registry `offer_voucher`); affiliate = lines flagged affiliate (cost = the commission of
        `affiliate_lines`). Optionally one product."""
        cond = {
            "voucher": "shop_voucher_share > 0",
            "no_voucher": "shop_voucher_share = 0",
            "affiliate": "affiliate",
            "all": "1 = 1",  # the shop's own lines on the same basis: the partition's whole
        }[kind]
        row = (
            await self._q(
                f"""select count(distinct order_ref) as orders,
                           coalesce(sum(deal_price * qty), 0) as gmv,
                           coalesce(sum(shop_voucher_share), 0) as voucher_cost
                      from order_lines
                     where shop_id = :s and platform = 'shopee' and day between :a and :b
                       and {self._sales_basis()} and {cond}
                       and (cast(:i as text) is null or item_id = cast(:i as text))""",  # nosec B608 — fragments are fixed literals (closed dict, registry enum)
                a=a,
                b=b,
                i=item,
            )
        )[0]
        cost = row["voucher_cost"]
        if kind == "affiliate":
            comm = await self._q(
                """select sum(commission) as c from affiliate_lines
                    where shop_id = :s and platform = 'shopee' and day between :a and :b
                      and coalesce(valid, true)
                      and (cast(:i as text) is null or item_id = cast(:i as text))""",
                a=a,
                b=b,
                i=item,
            )
            cost = comm[0]["c"]
        return {"orders": row["orders"], "gmv": row["gmv"], "cost": cost}

    async def voucher_income(self, a: date, b: date) -> dict[str, Any]:
        """Voucher orders and the voucher part of Ưu đãi from the stored per-order income
        (`order_settlements`, the table the fee / profit loaders read): orders with
        `seller_voucher_borne > 0`, the sum of `seller_voucher_borne`, and the GMV of those
        orders from `order_lines`. Only orders that HAVE an income row count (a day without
        income is not 0); `income_to` is the last order day the income holds in the window."""
        head = (
            await self._q(
                """select count(*) as rows,
                          count(*) filter (where seller_voucher_borne > 0) as orders,
                          sum(seller_voucher_borne) as cost,
                          max(ordered_on) as income_to
                     from order_settlements
                    where shop_id = :s and platform = 'shopee' and ordered_on between :a and :b""",
                a=a,
                b=b,
            )
        )[0]
        gmv = (
            await self._q(
                f"""select coalesce(sum(deal_price * qty), 0) as gmv
                      from order_lines
                     where shop_id = :s and platform = 'shopee' and day between :a and :b
                       and {self._sales_basis()}
                       and order_ref in (select order_ref from order_settlements
                                          where shop_id = :s and platform = 'shopee'
                                            and ordered_on between :a and :b
                                            and seller_voucher_borne > 0)""",  # nosec B608 — fragments are fixed literals (registry enum)
                a=a,
                b=b,
            )
        )[0]["gmv"]
        return {
            "rows": head["rows"],
            "orders": head["orders"],
            "gmv": gmv,
            "cost": head["cost"],
            "income_to": head["income_to"],
        }

    async def voucher_rows(self, a: date, b: date) -> list[dict[str, Any]]:
        """One row per voucher code: orders, GMV, the voucher's cost."""
        return await self._q(
            f"""select voucher_code as code, count(distinct order_ref) as orders,
                       coalesce(sum(deal_price * qty), 0) as gmv,
                       coalesce(sum(shop_voucher_share), 0) as cost
                  from order_lines
                 where shop_id = :s and platform = 'shopee' and day between :a and :b
                   and {self._sales_basis()} and shop_voucher_share > 0
                   and voucher_code is not null
                 group by voucher_code order by sum(deal_price * qty) desc""",  # nosec B608 — fragments are fixed literals (registry enum)
            a=a,
            b=b,
        )
