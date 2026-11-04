"""P91 D-9 / D-11: the KOL read model, its commission rule, the Mẫu KOL cost, and the KOL cards.

SQLite flows on the synthetic reco shop (seven days of orders, three products with giá vốn
30.000 / 20.000 / 15.000 and 1.000 đóng gói) plus invented creators ``kol_alpha``, ``kol_beta``,
``kol_gamma``. Every figure is invented; no real handle, client or buyer.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from juli_backend.models.platform_data import PlatformPeriodMetric
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.ingest.kol_key import kol_key
from juli_backend.services.shopee_analytics import kol, kol_rates, queries
from juli_backend.services.shopee_recommendations import kol_cards, service, versions
from juli_backend.services.shopee_recommendations.cards import build_card
from juli_backend.services.shopee_recommendations.loader import load_env
from tests.support.shopee_analytics import CUR_START, _line, period_row
from tests.support.shopee_reco import AS_OF, NOW, rule, seed_reco_shop

ALPHA, BETA, GAMMA = "kol_alpha", "kol_beta", "kol_gamma"
WINDOW = (date(2026, 9, 8), date(2026, 10, 7))  # the 30 days the reco env reads
OPEN = "Chiến dịch mở rộng"
TARGETED = "Chiến dịch mục tiêu"


def _kol_line(shop_id, n, day, sku, handle, channel, *, campaign=OPEN, **kw):
    line = _line(shop_id, n, day, sku, original=kw.pop("original", 100_000), **kw)
    line.affiliate = True
    line.kol_key = kol_key(handle)
    line.kol_handle = handle
    line.affiliate_channel = channel
    line.affiliate_campaign_type = campaign
    line.traffic_source = "affiliate"
    return line


def _partner(shop_id, handle, clicks, orders, roi):
    return period_row(
        shop_id,
        "affiliate_partner_period",
        *WINDOW,
        order_type="none",
        stream="affiliate",
        segment=kol_key(handle),
        platform_source=handle,
        clicks=Decimal(clicks),
        orders=Decimal(orders),
        gmv=Decimal(orders * 90_000),
        extra={"est_commission": orders * 4_500, "roi": roi},
    )


async def _seed(session):
    seeded = await seed_reco_shop(session)
    sid = seeded.shop_id
    day = CUR_START
    n = 200
    # alpha x G1: 12 orders, the report's own commission 4.500 each
    for i in range(12):
        n += 1
        session.add(
            _kol_line(sid, n, day, "G1", ALPHA, "Shopee Video", deal=90_000, commission=4_500)
        )
    # alpha x N1: 2 orders, no reported commission, open campaign -> open rate (8 %)
    for _ in range(2):
        n += 1
        session.add(
            _kol_line(sid, n, day, "N1", ALPHA, "Shopee Video", original=60_000, deal=54_000)
        )
    # beta x N1: 3 orders, targeted campaign -> targeted rate (10 %), no reported commission
    for _ in range(3):
        n += 1
        session.add(
            _kol_line(
                sid, n, day, "N1", BETA, "Facebook", original=60_000, deal=54_000, campaign=TARGETED
            )
        )
    # samples: alpha got 3 of G1, beta got 2 of N1
    ak, bk = kol_key(ALPHA), kol_key(BETA)
    session.add(
        rule(
            sid,
            "kol_sample",
            f"kol:{ak}:1001",
            [{"handle": ALPHA, "qty": 3, "sent_on": "2026-09-20", "ship_fee": 30_000}],
        )
    )
    session.add(
        rule(
            sid,
            "kol_sample",
            f"kol:{bk}:1002",
            [{"handle": BETA, "qty": 2, "sent_on": "2026-09-25", "ship_fee": 25_000}],
        )
    )
    # Shopee's creator export (30 days) and the product / campaign exports
    session.add(_partner(sid, ALPHA, 600, 14, 9.8))
    session.add(_partner(sid, BETA, 300, 3, 7.4))
    session.add(_partner(sid, GAMMA, 200, 8, 6.1))
    for item, orders, clicks in (("1001", 14, 700), ("1002", 5, 400), ("1003", 2, 100)):
        session.add(
            period_row(
                sid,
                "affiliate_product_period",
                *WINDOW,
                order_type="none",
                stream="affiliate",
                item_id=item,
                orders=Decimal(orders),
                clicks=Decimal(clicks),
                gmv=Decimal(orders * 90_000),
                extra={"est_commission": 0},
            )
        )
    session.add(
        period_row(
            sid,
            "affiliate_open_campaign_period",
            *WINDOW,
            order_type="none",
            stream="affiliate",
            item_id="1002",
            gmv=Decimal(1_000_000),
            extra={"est_commission": 80_000},
        )
    )
    session.add(
        period_row(
            sid,
            "affiliate_campaign_terms",
            date(2026, 10, 2),
            date(2026, 10, 2),
            order_type="none",
            stream="affiliate",
            segment="tcampaign001",
            item_id="1002",
            platform_source="Chiến dịch mẫu",
            extra={"commission_rate": 0.10, "running": True},
        )
    )
    await session.commit()
    return seeded


@pytest.fixture
async def shop(session):
    return await _seed(session)


def _row(body, handle, item):
    return next(r for r in body["rows"] if r["handle"] == handle and r["item_id"] == item)


# ===================================================================== commission (pure)


def test_the_report_wins_then_the_campaign_type_orders_targeted_and_open():
    book = kol_rates.RateBook(
        targeted={
            "1": [
                kol_rates.TermsRow(date(2026, 9, 1), Decimal("0.05"), True, "a"),
                kol_rates.TermsRow(date(2026, 10, 1), Decimal("0.12"), True, "a"),
                kol_rates.TermsRow(date(2026, 10, 1), Decimal("0.30"), False, "b"),
            ]
        },
        open_rate={"1": Decimal("0.08"), "2": Decimal("0.07")},
    )
    base = Decimal(100_000)
    common = {"base": base, "item_id": "1", "campaign_type": None, "book": book}
    day = date(2026, 10, 3)
    assert kol_rates.resolve_line_commission(reported=Decimal(777), on=day, **common) == (
        Decimal(777),
        "report",
    )
    # the snapshot at or before the day, the running campaign only
    assert kol_rates.resolve_line_commission(reported=None, on=day, **common) == (
        Decimal(12_000),
        "targeted",
    )
    early = date(2026, 9, 10)
    assert kol_rates.resolve_line_commission(reported=None, on=early, **common)[0] == Decimal(5_000)
    # an open campaign tries the open rate first
    got = kol_rates.resolve_line_commission(
        reported=None, on=day, **{**common, "campaign_type": OPEN}
    )
    assert got == (Decimal(8_000), "open")
    # a product with only an open rate; a product with nothing
    only_open = {**common, "item_id": "2"}
    assert kol_rates.resolve_line_commission(reported=None, on=day, **only_open)[1] == "open"
    none = {**common, "item_id": "9"}
    assert kol_rates.resolve_line_commission(reported=None, on=day, **none) == (None, "none")
    assert book.current("1") == (Decimal("0.12"), "targeted")


# ===================================================================== read model


async def test_the_table_has_the_row_math_the_artboard_defines(shop, session):
    body = await queries.kol_table(session, shop.shop_id, as_of=AS_OF)
    assert body["window"]["days"] == 30
    a = _row(body, ALPHA, "1001")
    # 12 orders x (90.000 - fees 18.900 - giá vốn 30.000 - đóng gói 1.000 - commission 4.500)
    assert (a["orders"], a["units"], a["gmv"], a["commission"]) == (12, 12, 1_080_000, 54_000)
    assert a["net_profit"] == 12 * 35_600
    assert a["commission_sources"] == {"report": 12}
    # sample = 3 x (30.000 + 1.000) + ship 30.000
    assert (a["sample_qty"], a["sample_cost"]) == (3, 123_000)
    assert a["profit_after_samples"] == 12 * 35_600 - 123_000
    assert a["roi_incl_samples"] == pytest.approx(
        (12 * 35_600 - 123_000) / (54_000 + 123_000), abs=1e-4
    )
    assert a["roi_shopee"] == 9.8  # as exported
    assert a["payback_orders"] == 4  # ceil(123.000 / 35.600)
    assert a["low_data"] is False and a["pair_orders"] == 12
    assert a["kol_clicks"] == 600 and a["kol_conversion"] == pytest.approx(14 / 600, abs=1e-6)
    assert a["clicks"] is None  # the creator export has no per-product clicks
    assert a["channel"] == "Shopee Video"
    # no order-ref or buyer field anywhere
    assert "order_ref" not in json.dumps(body)


async def test_commission_comes_from_the_rate_that_applied_to_the_product(shop, session):
    body = await queries.kol_table(session, shop.shop_id, as_of=AS_OF)
    b = _row(body, BETA, "1002")  # targeted 10 % of 54.000 = 5.400 per order
    assert b["commission"] == 3 * 5_400 and b["commission_sources"] == {"targeted": 3}
    assert b["commission_rate"] == pytest.approx(0.10)
    assert b["net_profit"] == 3 * (54_000 - 18_900 - 20_000 - 1_000 - 5_400)
    a2 = _row(body, ALPHA, "1002")  # open campaign: the product's open rate 8 %
    assert a2["commission"] == 2 * 4_320 and a2["commission_sources"] == {"open": 2}
    # beta's sample: 2 x (20.000 + 1.000) + 25.000; negative so far: ROI < 0, payback in orders
    assert b["sample_cost"] == 67_000
    assert b["roi_incl_samples"] == pytest.approx((26_100 - 67_000) / (16_200 + 67_000), abs=1e-4)
    assert b["payback_orders"] == 8  # ceil(67.000 / 8.700)
    assert b["roi_shopee"] == 7.4


async def test_ít_dữ_liệu_starts_below_ten_orders_for_the_pair(shop, session):
    body = await queries.kol_table(session, shop.shop_id, as_of=AS_OF)
    assert _row(body, ALPHA, "1001")["low_data"] is False  # 12 orders
    low = _row(body, ALPHA, "1002")
    assert low["low_data"] is True and low["low_data_label"] == "Ít dữ liệu"
    assert kol.ORDERS_THRESHOLD == 10
    rows = [kol.KolRow("k", "h", "c", "i", "p", pair_orders=n) for n in (9, 10)]
    assert [r.low_data for r in rows] == [True, False]


async def test_filters_sort_and_totals(shop, session):
    sid = shop.shop_id
    fb = await queries.kol_table(session, sid, as_of=AS_OF, channel="Facebook")
    assert [r["handle"] for r in fb["rows"]] == [BETA]
    assert fb["totals"]["orders"] == 3 and fb["totals"]["commission"] == 16_200
    only = await queries.kol_table(session, sid, as_of=AS_OF, item_id="1002")
    assert {r["handle"] for r in only["rows"]} == {ALPHA, BETA}
    by_orders = await queries.kol_table(session, sid, as_of=AS_OF, sort="orders")
    assert by_orders["rows"][0]["orders"] == 12
    assert set(by_orders["filters"]["channels"]) == {"Shopee Video", "Facebook"}
    assert by_orders["totals"]["orders"] == 17
    one = await queries.kol_table(session, sid, as_of=AS_OF, kol_key=kol_key(BETA))
    assert [r["handle"] for r in one["rows"]] == [BETA]
    with pytest.raises(ValueError):
        await queries.kol_table(session, sid, as_of=AS_OF, sort="bogus")


async def test_the_product_tab_names_the_current_rate_and_lists_only_its_kols(shop, session):
    tab = await queries.kol_product_tab(session, shop.shop_id, "1002", as_of=AS_OF)
    assert {r["handle"] for r in tab["rows"]} == {ALPHA, BETA}
    assert tab["product"]["commission_rate"] == pytest.approx(0.10)  # the targeted snapshot
    assert tab["product"]["commission_rate_source"] == "targeted"


async def test_a_sample_with_no_order_yet_still_has_a_row_and_no_cost_without_samples(
    shop, session
):
    sid = shop.shop_id
    session.add(
        rule(
            sid,
            "kol_sample",
            f"kol:{kol_key(GAMMA)}:1003",
            [{"handle": GAMMA, "qty": 1, "sent_on": "2026-10-01", "ship_fee": 10_000}],
        )
    )
    await session.commit()
    body = await queries.kol_table(session, sid, as_of=AS_OF, kol_key=kol_key(GAMMA))
    (row,) = body["rows"]
    assert row["orders"] == 0 and row["channel"] == "Chưa có đơn" and row["low_data"]
    assert row["sample_cost"] == 1 * (15_000 + 1_000) + 10_000
    assert row["payback_orders"] is None and row["net_profit"] == 0


async def test_without_a_creator_export_the_roi_shopee_is_absent_not_zero(shop, session):
    sid = shop.shop_id
    found = await session.scalars(
        select(PlatformPeriodMetric).where(
            PlatformPeriodMetric.dataset == "affiliate_partner_period"
        )
    )
    for p in found.all():
        await session.delete(p)
    await session.commit()
    body = await queries.kol_table(session, sid, as_of=AS_OF)
    assert all(r["roi_shopee"] is None and r["kol_clicks"] is None for r in body["rows"])


# ===================================================================== forecast (pure)


def _pool(**over):
    prod = kol.ProductStat(
        item_id="p1",
        name="SP 1",
        orders=20,
        aff_orders=10,
        basis="affiliate",
        units_per_order=Decimal(1),
        aov=Decimal(100_000),
        base_per_order=Decimal(100_000),
        precommission_per_order=Decimal(40_000),
        rate=Decimal("0.08"),
        rate_source="open",
        aff_clicks=Decimal(500),
        aff_conv=Decimal("0.02"),
        unit_cost=kol.UnitCost(Decimal(30_000), Decimal(1_000), "real", "real"),
        in_stock=True,
    )
    pool = kol.KolPool(window_days=30)
    pool.products["p1"] = prod
    pool.shop_conv = Decimal("0.02")
    pool.kols["k1"] = kol.KolStat(
        "k1",
        "kol_x",
        "Facebook",
        0,
        Decimal(over.get("orders", 2)),
        Decimal(100),
        Decimal(over.get("clicks30", 300)),
        None,
        0,
        None,
        Decimal(20_000),
    )
    return pool


def test_few_orders_pull_the_creator_toward_the_shop_average():
    # 2 orders / 100 clicks = 2 % ... a creator at 8 % with 2 orders is pulled to the shop's 2 %
    hot = _pool(orders=8)  # raw 8 %, n = 8 -> w = 8/18
    f = kol_cards.forecast(hot, "k1", "p1", qty=2, rate_pct=8, invite=False)
    assert f is not None
    w = 8 / 18
    assert f.shrink["kol_weight"] == pytest.approx(w, abs=1e-4)
    assert f.shrink["conv_used"] == pytest.approx(w * 0.08 + (1 - w) * 0.02)
    many = _pool(orders=80)
    g = kol_cards.forecast(many, "k1", "p1", qty=2, rate_pct=8, invite=False)
    assert (
        g is not None and g.shrink["conv_used"] > f.shrink["conv_used"]
    )  # more orders, more trust


def test_the_range_is_wide_below_ten_pair_orders_and_the_label_follows():
    assert kol_cards.spread_for(0) == (0.3, 2.2)
    assert kol_cards.spread_for(3) == (0.3, 2.2)
    assert kol_cards.spread_for(4) == (0.4, 1.9)
    assert kol_cards.spread_for(9) == (0.4, 1.9)
    assert kol_cards.spread_for(10) == (0.6, 1.4)
    pool = _pool()
    f = kol_cards.forecast(pool, "k1", "p1", qty=2, rate_pct=8, invite=False)
    assert f is not None and f.low_data
    assert (f.orders_lo, f.orders_hi) == pytest.approx((f.orders_mid * 0.3, f.orders_mid * 2.2))
    pool.pairs[("k1", "p1")] = kol.PairStat(12, 12, Decimal(0), Decimal(0), Decimal(0))
    g = kol_cards.forecast(pool, "k1", "p1", qty=2, rate_pct=8, invite=False)
    assert g is not None and not g.low_data
    assert g.orders_hi / g.orders_mid == pytest.approx(1.4)


def test_sample_cost_roi_payback_and_the_invite_have_the_documented_formulas():
    pool = _pool()
    f = kol_cards.forecast(pool, "k1", "p1", qty=3, rate_pct=8, invite=False)
    assert f is not None and f.sample is not None
    assert f.sample.cost == 3 * 31_000 + 20_000  # the creator's last shipping fee
    # per order: 40.000 net before commission - 8 % of 100.000 = 32.000
    assert f.net_per_order == pytest.approx(32_000) and f.commission_per_order == pytest.approx(
        8_000
    )
    at = f.at(10)
    assert at["net_profit"] == pytest.approx(320_000)
    assert at["roi_incl_samples"] == pytest.approx((320_000 - 113_000) / (80_000 + 113_000))
    assert f.payback_orders == 4  # ceil(113.000 / 32.000)
    inv = kol_cards.forecast(pool, "k1", "p1", qty=3, rate_pct=8, invite=True)
    assert inv is not None and inv.sample is None and inv.qty == 0
    assert inv.orders_mid == pytest.approx(f.orders_mid * kol_cards.INVITE_FACTOR)
    assert inv.at(10)["roi_incl_samples"] == pytest.approx(320_000 / 80_000)
    assert inv.payback_orders is None
    # a higher rate: more orders (sqrt), less net per order
    hi = kol_cards.forecast(pool, "k1", "p1", qty=3, rate_pct=18, invite=False)
    assert hi is not None and hi.orders_mid == pytest.approx(f.orders_mid * (18 / 8) ** 0.5)
    assert hi.net_per_order < f.net_per_order


def test_a_creator_without_an_export_row_or_a_product_without_cost_gives_no_forecast():
    pool = _pool()
    assert kol_cards.forecast(pool, "nobody", "p1", qty=1, rate_pct=8, invite=False) is None
    assert kol_cards.forecast(pool, "k1", "zzz", qty=1, rate_pct=8, invite=False) is None
    pool.products["p1"] = kol.ProductStat(**{**pool.products["p1"].__dict__, "unit_cost": None})
    assert kol_cards.forecast(pool, "k1", "p1", qty=1, rate_pct=8, invite=False) is None
    assert kol_cards.forecast(pool, "k1", "p1", qty=1, rate_pct=8, invite=True) is not None


# ===================================================================== cards


async def test_one_card_per_creator_gửi_mẫu_or_mời_and_flowing_through_build_card(shop, session):
    env = await load_env(session, shop.shop_id, as_of=AS_OF)
    assert env is not None and env.kol is not None
    cands = kol_cards.generate(env)
    kinds = {c.extra["kol"]["key"]: c.kind for c in cands}
    assert kinds[kol_key(GAMMA)] == "affiliate_invite"  # no sample on record
    assert kinds[kol_key(ALPHA)] == "affiliate_sample"
    assert len({c.campaign_key for c in cands}) == len(cands)  # the dedupe key is the creator
    sent = {(kol_key(ALPHA), "1001"), (kol_key(BETA), "1002")}
    for c in cands:  # never a sample for a pair that already got one
        assert (c.extra["kol"]["key"], c.item) not in sent
    cand = next(c for c in cands if c.kind == "affiliate_sample")
    card = build_card(env, cand, now=NOW)
    assert card is not None
    assert card["family"] == "affiliate" and card["change_kind"] == "affiliate_sample"
    block = card["kol"]
    assert block["sample"]["cost"] > 0 and block["sample"]["label"]
    assert block["measurement"] == {
        **block["measurement"],
        "kind": "kol_pair",
        "kol_key": cand.extra["kol"]["key"],
        "item_id": cand.item,
    }
    for key in (
        "certain",
        "predicted",
        "measurement_plan",
        "execution_sheet",
        "rank_inputs",
        "scope",
        "whatif",
        "floor",
        "spend",
        "change",
        "inputs",
    ):
        assert key in card
    assert card["predicted"]["money_per_month"]["certain"]["dprofit"] == pytest.approx(
        -block["sample"]["cost"]
    )
    assert {s["key"] for s in card["whatif"]["sliders"]} == {"qty", "commission_pct"}
    assert card["whatif"]["choices"][0]["key"] == "item_id"
    assert card["rank_inputs"]["items"] == [cand.item]
    invite = next(c for c in cands if c.kind == "affiliate_invite")
    inv_card = build_card(env, invite, now=NOW)
    assert inv_card is not None and inv_card["kol"]["sample"] is None
    assert {s["key"] for s in inv_card["whatif"]["sliders"]} == {"commission_pct"}
    assert inv_card["certain"]["sample_cost"] is None or inv_card["certain"]["sample_cost"] == 0


async def test_versions_vary_the_product_and_the_sample_count(shop, session):
    env = await load_env(session, shop.shop_id, as_of=AS_OF)
    cand = next(c for c in kol_cards.generate(env) if c.kind == "affiliate_sample")
    card = build_card(env, cand, now=NOW)
    vs = versions.build_versions(env, cand, card, now=NOW)
    assert 2 <= len(vs) <= 4 and vs[0]["label"] == versions.DEFAULT_LABEL and vs[0]["ranked"]
    items = {v["inputs"]["item_id"] for v in vs if v["status"] != "refused"}
    assert len(items) >= 2  # another product is a version
    assert any(v["label"].startswith("Sản phẩm: ") for v in vs[1:])
    assert any("Số lượng mẫu" in v["label"] for v in vs[1:]) or len(vs) == 4
    for v in vs:
        if v["status"] != "refused":
            assert set(versions.EVAL_FIELDS) <= set(v)
    qtys = {v["inputs"]["qty"] for v in vs if v["status"] != "refused"}
    assert len(qtys) >= 1


async def test_what_if_moves_the_product_the_sample_count_and_the_rate(shop, session):
    env = await load_env(session, shop.shop_id, as_of=AS_OF)
    cand = next(c for c in kol_cards.generate(env) if c.kind == "affiliate_sample")
    card = build_card(env, cand, now=NOW)
    card["versions"] = versions.build_versions(env, cand, card, now=NOW)
    card["id"] = "card-1"
    more = service.recompute_card(env, card, {"qty": cand.inputs["qty"] + 2}, now=NOW)
    assert more is not None
    assert more["kol"]["sample"]["cost"] > card["kol"]["sample"]["cost"]
    assert more["kol"]["qty"] == cand.inputs["qty"] + 2
    assert [v["version"] for v in more["versions"]] == [v["version"] for v in card["versions"]]
    rate = service.recompute_card(env, card, {"commission_pct": 20}, now=NOW)
    assert rate is not None and rate["kol"]["commission_pct"] == 20
    assert rate["kol"]["expected"]["orders"]["p50"] > card["kol"]["expected"]["orders"]["p50"]
    other = next(c["value"] for c in card["whatif"]["choices"][0]["options"] if not c["selected"])
    moved = service.recompute_card(env, card, {"item_id": other}, now=NOW)
    assert moved is not None and moved["kol"]["product"]["item_id"] == other
    assert moved["scope"]["product_ids"] == [other]
    assert service.recompute_card(env, card, {"qty": 0}, now=NOW) is None  # not evaluable


async def test_cards_persist_with_codes_a_queue_and_a_row_reference(shop, session):
    sid = shop.shop_id
    report = await reco.generate_cards(session, sid, now=NOW, as_of=AS_OF)
    await session.commit()
    assert (
        report.by_kind.get("affiliate_invite", 0) + report.by_kind.get("affiliate_sample", 0) >= 1
    )
    from juli_backend.services.shopee_recommendations import store

    rows = await store.list_cards(session, sid)
    mine = [(p, c) for p, c in rows if c["change_kind"] in kol_cards.KOL_KINDS]
    assert mine
    for p, card in mine:
        assert p.code and card["code"] == p.code and p.product_queue is not None
        assert [v["code"] for v in card["versions"]] == [
            f"{p.code}-V{v['version']}" for v in card["versions"]
        ]
    await reco.publish(session, sid, None, now=NOW)
    await session.commit()
    body = await queries.kol_table(session, sid, as_of=AS_OF)
    body = await reco.attach_kol_cards(session, sid, body, audience="seller")
    carded = [r for r in body["rows"] if r["card"]]
    assert carded and carded[0]["card"]["kind_label"] in ("Gửi mẫu cho KOL", "Mời KOL")
    assert carded[0]["card"]["code"].startswith("JC-")


async def test_the_pair_series_for_measurement_counts_distinct_orders_per_day(shop, session):
    # the stored lines carry the unresolved ``sku:`` item id (the analytics resolve it on read)
    series = await kol.pair_daily(
        session, shop.shop_id, kol_key(ALPHA), "sku:G1", date(2026, 10, 1), date(2026, 10, 7)
    )
    assert list(series) == [date(2026, 10, 1)]
    assert series[date(2026, 10, 1)] == {"orders": 12, "units": 12, "gmv": Decimal(1_080_000)}
    other = await kol.pair_daily(
        session, shop.shop_id, kol_key(BETA), "sku:G1", date(2026, 10, 1), date(2026, 10, 7)
    )
    assert other == {}
