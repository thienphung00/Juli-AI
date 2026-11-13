"""P98 / ADR-122 d.2-d.3: the stored funnel as the one read model of Lượt xem / CTR / CTOR.

Pure tests build ``funnel.FunnelRows`` by hand; the DB tests (SQLite) rebuild the synthetic shop
of ``tests/support/shopee_analytics`` and read it back through the screens. Synthetic data only.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy import delete

from juli_backend.models.shopee_metrics import ShopeeSourceMetricsDaily
from juli_backend.services.shopee_analytics import funnel, materialize, queries
from juli_backend.services.shopee_analytics.funnel import (
    FunnelRows,
    ScopeDay,
    SourceDay,
    base_from_rows,
    known_total,
)
from juli_backend.services.shopee_analytics.windows import Window
from juli_backend.services.shopee_builder.engine.contract import RESIDUAL, SOURCES
from tests.support.shopee_analytics import CUR_END, seed_shopee_shop

D1, D2, D3 = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)
W = Window(D1, D3)
D = Decimal


def _src(day, source, views, clicks, orders, gmv, profit=D(0), item=None, **ads):
    return SourceDay(day, item, source, views, clicks, orders, D(gmv), profit, **ads)


def _shop_day(day, sources):
    """The six shop rows of a day: ``sources`` = {source: (views, clicks, orders, gmv)}."""
    out = []
    for s in SOURCES:
        v, c, o, g = sources.get(s, (None, None, 0, 0))
        out.append(_src(day, s, v, c, o, g, D(g) / 10))
    return out


def _by(base):
    return {s.source: s for s in base.sources}


# ------------------------------------------------------------------------------- pure


def test_window_sums_never_average_daily_ratios():
    rows = FunnelRows(
        W,
        tuple(
            _shop_day(D1, {"the_san_pham_khac": (1000, 10, 1, 100_000)})
            + _shop_day(D2, {"the_san_pham_khac": (100, 50, 5, 500_000)})
        ),
        (
            ScopeDay(D1, None, 1, D(100_000), D(10_000)),
            ScopeDay(D2, None, 5, D(500_000), D(50_000)),
        ),
    )
    card = _by(base_from_rows(rows, "s"))["the_san_pham_khac"]
    assert (card.views, card.clicks, card.orders) == (1100, 60, 6)
    # sums: 60 / 1100, not the mean of 1 % and 50 %
    assert card.ctr == D(60) / D(1100) and card.ctor == D(6) / D(60)


def test_the_residual_carries_orders_but_counts_zero_traffic_in_the_totals():
    rows = FunnelRows(
        W,
        tuple(
            _shop_day(
                D1, {"the_san_pham_khac": (900, 40, 2, 170_000), RESIDUAL: (None, None, 2, 80_000)}
            )
        ),
        (ScopeDay(D1, None, 4, D(250_000), D(25_000)),),
    )
    base = base_from_rows(rows, "s")
    res = _by(base)[RESIDUAL]
    assert res.orders == 2 and res.views is None and res.clicks is None
    assert base.total("orders") == 4 and base.total("views") == 900
    assert base.total("clicks") == 40
    # CTOR = all orders (Tổng quan) ÷ clicks
    n = funnel.numbers(base, 4)
    assert n.ctor == D(4) / D(40)


def test_views_times_ctr_times_ctor_is_the_orders_exactly():
    rows = FunnelRows(
        W,
        tuple(
            _shop_day(D1, {"the_san_pham_khac": (937, 41, 3, 300_001), "video": (13, 7, 1, 9)})
            + _shop_day(
                D2, {"the_san_pham_khac": (811, 29, 2, 99_999), RESIDUAL: (None, None, 4, 7)}
            )
        ),
    )
    base = base_from_rows(rows, "s")
    orders = base.total("orders")
    n = funnel.numbers(base, orders)
    assert n.views * n.ctr * n.ctor == orders == 10
    assert (
        base.total("views")
        * (base.total("clicks") / base.total("views"))
        * (orders / base.total("clicks"))
        == orders
    )


def test_a_day_without_source_rows_puts_its_orders_on_the_residual():
    rows = FunnelRows(
        W,
        tuple(_shop_day(D1, {"the_san_pham_khac": (500, 20, 2, 200_000)})),
        (ScopeDay(D1, None, 2, D(200_000), D(20_000)), ScopeDay(D2, None, 3, D(90_000), None)),
    )
    base = base_from_rows(rows, "s")
    assert base.total("orders") == 5 and base.total("gmv") == 290_000
    assert _by(base)[RESIDUAL].orders == 3
    # P99: D2's profit is "chưa tính", so it adds nothing; the window keeps D1's known profit
    assert _by(base)[RESIDUAL].profit == 0 and _by(base)[RESIDUAL].profit_orders == 0
    assert base.total("profit_orders") == 2 and (base.profit_days, base.days) == (1, 2)


def test_a_source_with_no_traffic_rows_and_no_orders_is_zero_not_unknown():
    rows = FunnelRows(W, tuple(_shop_day(D1, {"the_san_pham_khac": (500, 20, 2, 200_000)})))
    base = base_from_rows(rows, "s")
    live = _by(base)["live"]
    assert live.views == 0 and live.ctr is None
    assert base.total("views") == 500


def test_a_scope_without_any_traffic_keeps_views_unknown():
    rows = FunnelRows(W, tuple(_shop_day(D1, {RESIDUAL: (None, None, 3, 90_000)})))
    base = base_from_rows(rows, "s")
    assert base.total("views") is None and known_total(base, "views") is None
    assert funnel.numbers(base, 3).ctr is None


def test_products_with_source_rows_on_every_active_day_are_per_source():
    rows = FunnelRows(
        W,
        (
            _src(D1, "the_san_pham_khac", 300, 12, 2, 80_000, item="A"),
            _src(D1, RESIDUAL, None, None, 1, 10_000, item="A"),
        ),
        (),
        (ScopeDay(D1, "A", 3, D(90_000), D(9_000), 300, 12), ScopeDay(D2, "A", 0, D(0), None)),
    )
    base = base_from_rows(rows, "s", item_ids=["A"])
    assert base.source_detail == "per_source" and base.scope == "products"
    assert base.total("orders") == 3 and base.total("views") == 300


def test_products_missing_source_rows_on_an_active_day_use_the_all_source_funnel():
    rows = FunnelRows(
        W,
        (_src(D1, "the_san_pham_khac", 300, 12, 2, 80_000, item="A"),),
        (),
        (
            ScopeDay(D1, "A", 2, D(80_000), D(8_000), 300, 12, D(5_000)),
            ScopeDay(D2, "A", 1, D(40_000), D(4_000), 200, 8, D(1_000)),
        ),
    )
    base = base_from_rows(rows, "s", item_ids=["A"])
    assert base.source_detail == "all_sources"
    (only,) = base.sources
    assert (only.views, only.clicks, only.orders, only.gmv) == (500, 20, 3, 120_000)
    assert only.ads is not None and only.ads.spend == 6_000 and only.ads.views is None
    assert funnel.numbers(base, 3).note == funnel.ALL_SOURCES_NOTE


def test_partial_ad_share_keeps_missing_fields_none_meaning_no_ad_data():
    rows = FunnelRows(
        W,
        (
            _src(
                D1,
                "the_san_pham_khac",
                300,
                12,
                2,
                80_000,
                item="A",
                ads_spend=D(7_000),
                ads_gmv=D(20_000),
            ),
            _src(D2, "the_san_pham_khac", 100, 2, 0, 0, item="A", ads_spend=D(3_000)),
        ),  # fmt: skip
    )
    ads = _by(base_from_rows(rows, "s", item_ids=["A"]))["the_san_pham_khac"].ads
    assert ads is not None
    assert ads.spend == 10_000 and ads.gmv == 20_000
    assert ads.views is None and ads.clicks is None and ads.orders is None
    assert _by(base_from_rows(rows, "s", item_ids=["A"]))["video"].ads is None


def test_the_shop_scope_reads_shop_rows_only():
    rows = FunnelRows(
        W,
        tuple(_shop_day(D1, {"the_san_pham_khac": (500, 20, 2, 200_000)}))
        + (_src(D1, "the_san_pham_khac", 300, 12, 2, 80_000, item="A"),),
    )
    assert base_from_rows(rows, "s").total("views") == 500


def test_no_rows_means_not_available_and_the_fallback_note():
    rows = FunnelRows(W)
    assert not rows.available
    assert funnel.basis_json(rows)["basis"] == funnel.BASIS_FLOWS
    assert funnel.basis_json(rows)["note"] == funnel.FALLBACK_NOTE
    assert funnel.flow_tables(rows, None) is None


# ------------------------------------------------------------------------------- DB


@pytest.fixture
async def built(session):
    seeded = await seed_shopee_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    return seeded


async def test_load_funnel_base_sums_the_stored_rows_to_the_shop_totals(session, built):
    window = await funnel.anchor_window(session, built.shop_id)
    assert window is not None and window.end == CUR_END and window.days == 30
    base = await funnel.load_funnel_base(session, built.shop_id, window=window)
    overview = await queries.overview(session, built.shop_id)
    m = overview["shop_metrics"]
    assert base.scope == "shop" and base.window_start == window.start
    assert base.total("orders") == m["orders"]
    assert base.total("gmv") == Decimal(str(m["gmv"]))
    assert known_total(base, "views") == m["views"]
    assert known_total(base, "clicks") == m["clicks"]


async def test_tong_quan_funnel_holds_exactly_and_names_its_basis(session, built):
    body = await queries.overview(session, built.shop_id)
    chain, m = body["flows"]["chain"], body["shop_metrics"]
    assert body["funnel"]["basis"] == funnel.BASIS_SOURCES
    assert m["funnel_basis"] == funnel.BASIS_SOURCES and m["ctor_note"] == funnel.CTOR_NOTE
    assert body["kpi_strip"]["ctor"]["note"] == funnel.CTOR_NOTE
    assert chain["orders"] == m["orders"] and chain["views"] == m["views"]
    assert chain["ctor"] == pytest.approx(m["orders"] / m["clicks"], abs=1e-6)
    assert chain["views"] * chain["ctr"] * chain["ctor"] == pytest.approx(m["orders"], abs=1e-3)
    rows = body["flows"]["rows"]
    assert sum(r["orders"] for r in rows) == m["orders"]  # sources add up to Tổng quan
    assert all(r["orders"] >= 0 for r in rows)


async def test_without_source_rows_the_screens_keep_the_traffic_tables_with_a_note(session, built):
    with_rows = await queries.overview(session, built.shop_id)
    await session.execute(
        delete(ShopeeSourceMetricsDaily).where(ShopeeSourceMetricsDaily.shop_id == built.shop_id)
    )
    body = await queries.overview(session, built.shop_id)
    assert body["funnel"]["basis"] == funnel.BASIS_FLOWS
    assert body["funnel"]["note"] == funnel.FALLBACK_NOTE
    assert body["shop_metrics"]["funnel_basis"] == funnel.BASIS_FLOWS
    # same traffic either way on the synthetic shop: the funnel's views are the traffic tables'
    assert body["shop_metrics"]["views"] == with_rows["shop_metrics"]["views"]


async def test_product_page_ctor_uses_the_product_orders_and_says_its_basis(session, built):
    page = await queries.product_page(session, built.shop_id, "1001")
    k = page["kpi_by_period"]["30d"]
    assert k["ctor_note"] == funnel.CTOR_NOTE
    assert k["funnel"]["basis"] == funnel.BASIS_SOURCES
    assert k["funnel"]["source_detail"] in ("per_source", "all_sources")
    if k["clicks"]:
        assert k["ctor"] == pytest.approx(k["orders"]["value"] / k["clicks"], abs=1e-6)


async def test_ranking_names_the_funnel_basis(session, built):
    body = await queries.ranking(session, built.shop_id, xep_theo="ctor")
    assert body["funnel"]["basis"] == funnel.BASIS_SOURCES
    assert body["funnel"]["ctor_note"] == funnel.CTOR_NOTE


async def test_contribution_rate_is_none_without_real_costs(session, built):
    window = Window(CUR_END - timedelta(days=29), CUR_END)
    base = await funnel.load_funnel_base(session, built.shop_id, item_ids=["1001"], window=window)
    assert base.scope == "products" and base.item_ids == ("1001",)
    assert base.contribution_rate is None  # the synthetic shop has no giá vốn stated


async def test_contribution_rate_is_contribution_per_dong_of_line_gmv(session):
    seeded = await seed_shopee_shop(session, rules=True)
    await materialize.backfill_shop(session, seeded.shop_id)
    window = Window(CUR_END - timedelta(days=29), CUR_END)
    from dataclasses import replace

    from juli_backend.services.shopee_analytics import loaders, service

    ctx = await loaders.load_context(session, seeded.shop_id)
    ctx = replace(ctx, rules=ctx.rules.for_month(f"{window.end:%Y-%m}"))
    view = await service.load_view(session, seeded.shop_id, ctx, window)
    rate = funnel.contribution_rate(view)
    if any(
        not view.costs.cogs_is_real(ln.sku) for ln, pb in view.pairs if pb.excluded_reason is None
    ):
        assert rate is None
    else:
        lines = [(ln, pb) for ln, pb in view.pairs if pb.excluded_reason is None]
        want = sum((pb.contribution for _, pb in lines), D(0)) / sum(
            (ln.order_value for ln, _ in lines), D(0)
        )
        assert rate == want


# ------------------------------------------------------------------- product page (d.12)


async def test_product_page_skus_carry_orders_and_both_margins(session):
    seeded = await seed_shopee_shop(session, rules=True)
    page = await queries.product_page(session, seeded.shop_id, "1001", period="30d")
    sku = next(s for s in page["cost_and_floor"]["skus"] if s["sku"] == "G1")
    assert 0 < sku["orders"] <= sku["units"]  # distinct orders; units stay in "units"
    assert sku["price_margin_name"] == "Biên ở giá bán" and sku["price_margin_label"] == "chắc chắn"
    assert sku["final_margin_name"] == "Biên cuối" and sku["final_margin_label"] == "ước tính"
    assert sku["price_margin_pct"] is not None and sku["final_margin_basis"] == "variation"
    r = sku["final_margin_rates"]
    want = sku["price_margin_pct"] - (r["voucher_pct"] + r["commission_pct"] + r["ads_pct"])
    assert sku["final_margin_pct"] == pytest.approx(want, abs=0.11)  # 0.1-point rounding each
    assert sku["final_margin_pct"] <= sku["price_margin_pct"]


async def test_product_page_states_no_assumed_cost(session):
    seeded = await seed_shopee_shop(session)  # no giá vốn stated
    page = await queries.product_page(session, seeded.shop_id, "1001", period="30d")
    assert "1/3" not in page["cost_and_floor"]["coverage_label"]
    for sku in page["cost_and_floor"]["skus"]:
        assert sku["cost"]["label"] == "chưa tính" and sku["cost"]["cogs_per_unit"] is None
        assert sku["waterfall_per_unit"]["margin_pct"] is None
        assert sku["price_margin_pct"] is None and sku["price_margin_reason"] == "cost_missing"
        assert sku["final_margin_pct"] is None


def test_a_variation_without_history_takes_its_product_rates():
    from juli_backend.services.shopee_analytics import product as product_mod

    class _Pb:
        def __init__(self, revenue, voucher, commission):
            self.revenue, self.voucher, self.commission = D(revenue), D(voucher), D(commission)
            self.excluded_reason = None

    class _Ln:
        def __init__(self, sku):
            self.product_id, self.sku = "P", sku

    class _Ads:
        product_spend = {"P": D(1_000)}

    class _View:
        pairs = [(_Ln("A"), _Pb(10_000, 500, 1_000))]
        ads = _Ads()

    view = cast(Any, _View())
    own = product_mod._rates(view, "P", "A")
    assert own is not None and own.voucher == D("0.05") and own.ads == D("0.1")
    assert product_mod._rates(view, "P", "B") is None  # → caller uses the product's
    assert product_mod._rates(view, "P", None) == own


# ------------------------------------------------------------------------- Kế hoạch base


def test_plan_base_funnel_reads_the_stored_rows_with_ctor_on_shop_orders():
    from types import SimpleNamespace

    from juli_backend.services.shopee_recommendations import plan_base

    env = cast(Any, SimpleNamespace(metrics=SimpleNamespace(views=1, clicks=1, orders=4)))
    rows = FunnelRows(W, tuple(_shop_day(D1, {"the_san_pham_khac": (900, 40, 2, 170_000)})))
    got = plan_base.funnel_json(env, rows)
    assert got["views"] == 900 and got["clicks"] == 40
    assert got["ctor"] == pytest.approx(4 / 40) and got["ctor_note"] == funnel.CTOR_NOTE
    assert got["funnel_basis"] == funnel.BASIS_SOURCES and got["funnel_note"] is None
    old = plan_base.funnel_json(env, FunnelRows(W))
    assert old["views"] == 1 and old["funnel_basis"] == funnel.BASIS_FLOWS
    assert old["funnel_note"] == funnel.FALLBACK_NOTE
