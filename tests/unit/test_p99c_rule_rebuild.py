"""P99c (owner rule: never display wrong information): the stored daily rows hold profit computed
with the seller's giá vốn / đóng gói / VAT rules, so saving such a rule rebuilds them in the same
transaction -- the screens never read profit computed with the old cost. Synthetic shop only
(SQLite, invented figures)."""

from __future__ import annotations

from decimal import Decimal as D

from sqlalchemy import func, select

from juli_backend.models.shopee_metrics import ShopeeProductMetricsDaily, ShopeeShopMetricsDaily
from juli_backend.services import shop_inputs, shop_rules
from juli_backend.services.shopee_analytics import materialize
from tests.support.shopee_analytics import seed_shopee_shop


async def _item_profit(session, shop_id, item_id: str) -> tuple[D, D]:
    t = ShopeeProductMetricsDaily
    row = (
        await session.execute(
            select(func.sum(t.profit), func.sum(t.gmv)).where(
                t.shop_id == shop_id, t.item_id == item_id, t.profit.is_not(None)
            )
        )
    ).one()
    return D(row[0]), D(row[1])


async def _shop_profit(session, shop_id) -> D:
    t = ShopeeShopMetricsDaily
    total = (
        await session.execute(select(func.sum(t.profit)).where(t.shop_id == shop_id))
    ).scalar_one()
    return D(total)


async def test_a_new_gia_von_rebuilds_the_stored_product_profit_and_margin(session):
    seeded = await seed_shopee_shop(session, rules=True)
    actor = shop_inputs.Actor(set_by="seller", user_id=seeded.user.id)
    before, gmv = await _item_profit(session, seeded.shop_id, "1001")
    shop_before = await _shop_profit(session, seeded.shop_id)

    await shop_inputs.write_rule(
        session, seeded.shop_id, rule_key="sku_cost", scope_ref="G1", value=40_000, actor=actor
    )
    session.expunge_all()
    after, gmv_after = await _item_profit(session, seeded.shop_id, "1001")
    assert gmv_after == gmv  # the money in is the same, only the cost moved
    assert after < before  # 10k more giá vốn per unit
    assert after / gmv < before / gmv  # the margin the screens derive follows
    assert await _shop_profit(session, seeded.shop_id) < shop_before

    # the stored rows equal a fresh rebuild with the new rule (nothing left from the old cost)
    await materialize.backfill_shop(session, seeded.shop_id)
    session.expunge_all()
    assert (await _item_profit(session, seeded.shop_id, "1001"))[0] == after


async def test_an_import_change_set_and_a_restore_rebuild_too(session):
    seeded = await seed_shopee_shop(session, rules=True)
    actor = shop_inputs.Actor(set_by="seller", user_id=seeded.user.id)
    first, _ = await _item_profit(session, seeded.shop_id, "1001")
    await shop_inputs.write_versions(
        session,
        seeded.shop_id,
        [shop_inputs.RuleChange("sku_cost", "G1", 10_000)],
        actor=actor,
        reason="giá vốn mới",
    )
    session.expunge_all()
    cheaper, _ = await _item_profit(session, seeded.shop_id, "1001")
    assert cheaper > first
    await shop_inputs.write_rule(
        session, seeded.shop_id, rule_key="sku_cost", scope_ref="G1", value=50_000, actor=actor
    )
    session.expunge_all()
    dearer, _ = await _item_profit(session, seeded.shop_id, "1001")
    assert dearer < first
    await shop_inputs.restore_version(  # v1 = the change set's 10k
        session, seeded.shop_id, rule_key="sku_cost", scope_ref="G1", version=1, actor=actor
    )
    session.expunge_all()
    assert (await _item_profit(session, seeded.shop_id, "1001"))[0] == cheaper


async def test_an_unset_rule_rebuilds_on_its_default(session):
    seeded = await seed_shopee_shop(session, rules=True)
    before = await _shop_profit(session, seeded.shop_id)
    assert await shop_rules.delete_rule(
        session, seeded.shop_id, rule_key="packaging_cost", scope_ref="G1"
    )
    days = await shop_inputs.rules_changed(session, seeded.shop_id, ["packaging_cost"])
    session.expunge_all()
    assert days == len(await materialize.data_days(session, seeded.shop_id))
    assert await _shop_profit(session, seeded.shop_id) > before  # no đóng gói cost any more


async def test_a_rule_the_rows_do_not_hold_rebuilds_nothing(session):
    seeded = await seed_shopee_shop(session, rules=True)
    done = await materialize.after_rules_change(
        session, seeded.shop_id, ["daily_marketing_cap", "max_discount_pct"]
    )
    assert done == materialize.RuleRebuild()


async def test_a_failed_rebuild_clears_the_stale_rows_never_keeps_the_old_profit(
    session, monkeypatch
):
    seeded = await seed_shopee_shop(session, rules=True)

    async def broken(*_a, **_k):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(materialize, "rebuild_days", broken)
    done = await materialize.after_rules_change(session, seeded.shop_id, ["sku_cost"])
    assert done.days == 0 and done.cleared > 0
    left = (
        await session.execute(
            select(func.count())
            .select_from(ShopeeShopMetricsDaily)
            .where(ShopeeShopMetricsDaily.shop_id == seeded.shop_id)
        )
    ).scalar_one()
    assert left == 0  # the screens answer rows_not_materialized ("đang tính lại")
