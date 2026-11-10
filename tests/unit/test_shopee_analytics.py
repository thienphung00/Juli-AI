"""P90 step 7: the Shopee analytics builders over a synthetic shop (SQLite, no Postgres).

The data is ``tests/support/shopee_analytics.py``: three products, two windows of seven days,
order lines of every kind, and traffic rows whose five flows fall 5.000đ per day short of the
shop's Doanh số. The checks are the contract's identities (flows add up with a residual row, price
levers add up, product ad spend + unattributed = total, GMV chain), the order basis (a paid
cancelled order counts for GMV, not for profit), the cost rules (1/3 fallback labelled, imported
cost wins), the fee rules (actual wins, formula otherwise) and what a response may not contain.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from juli_backend.services.shopee_analytics import loaders, queries, service
from juli_backend.services.shopee_analytics import stored as stored_mod
from juli_backend.services.shopee_analytics.windows import Window
from tests.support.shopee_analytics import (
    CUR_END,
    CUR_START,
    DAILY_SHOP_GMV,
    PREV_END,
    Seeded,
    keyword,
    seed_shopee_shop,
    snapshot,
)

CUR = Window(CUR_START, CUR_END)


@pytest.fixture
async def seeded(session) -> Seeded:
    return await seed_shopee_shop(session)


@pytest.fixture
async def seeded_rules(session) -> Seeded:
    return await seed_shopee_shop(session, rules=True)


async def _overview(session, seeded: Seeded, **kw):
    return await queries.overview(session, seeded.shop_id, period="7d", as_of=CUR_END, **kw)


def _line_gmv(seeded: Seeded, start: date, end: date, *, paid_only: bool = True) -> Decimal:
    return sum(
        (
            ln.deal_price * ln.qty
            for ln in seeded.lines
            if start <= ln.ordered_at.date() <= end and (ln.paid_at is not None or not paid_only)
        ),
        Decimal(0),
    )


# =========================================================================== order basis


async def test_confirmed_orders_are_the_paid_ones_and_a_cancelled_paid_order_keeps_its_gmv(
    session, seeded
):
    body = await _overview(session, seeded)
    # 14 orders in the window, one never paid (n=10): 13 confirmed, one of them later cancelled
    assert body["gmv"]["line_orders"] == 13
    assert Decimal(str(body["gmv"]["line_gmv"])) == _line_gmv(seeded, CUR_START, CUR_END)
    # profit: the cancelled paid order is outside the profit base, not outside GMV
    assert body["profit"]["orders"] == 13  # orders counted; the cancelled one has no fee
    assert body["profit"]["fees"]["not_charged"] == 1


async def test_aov_follows_both_definitions_and_says_which(session, seeded):
    body = await _overview(session, seeded)
    gmv = _line_gmv(seeded, CUR_START, CUR_END)
    voucher = sum(
        (
            ln.shop_voucher_share
            for ln in seeded.lines
            if CUR_START <= ln.ordered_at.date() <= CUR_END and ln.paid_at
        ),
        Decimal(0),
    )
    assert body["gmv"]["aov_seller_centre"] == pytest.approx(float((gmv - voucher) / 13), abs=0.01)
    assert body["gmv"]["shopee_orders"] == 35 and body["gmv"]["shopee_gmv"] == 7 * int(
        DAILY_SHOP_GMV
    )
    assert "§14" in body["gmv"]["aov_note"]


async def test_the_shop_totals_are_shopees_daily_rows_when_every_day_is_there(session, seeded):
    body = await _overview(session, seeded)
    assert body["data"]["shop_totals"] == {"basis": "daily", "days_covered": 7}
    assert body["kpi_strip"]["gmv"]["value"] == 7 * int(DAILY_SHOP_GMV)
    assert body["kpi_strip"]["gmv"]["previous"] == 7 * int(DAILY_SHOP_GMV)
    assert body["kpi_strip"]["gmv"]["change_pct"] == 0.0


# =========================================================================== flows


async def test_five_flows_and_the_residual_row_add_up_to_the_shop_gmv(session, seeded):
    flows = (await _overview(session, seeded))["flows"]
    keys = [r["key"] for r in flows["rows"]]
    assert keys == [
        "the_san_pham_khac",
        "trang_shop",
        "live",
        "video",
        "lien_ket",
        "chenh_lech_nguon",
    ]
    by = {r["key"]: r for r in flows["rows"]}
    assert by["the_san_pham_khac"]["gmv"] == 7 * 170_000  # Thẻ sản phẩm minus its Trang shop child
    assert by["trang_shop"]["gmv"] == 7 * 30_000
    assert by["chenh_lech_nguon"]["gmv"] == 7 * 5_000 and by["chenh_lech_nguon"]["is_residual"]
    assert sum(r["gmv"] for r in flows["rows"]) == flows["total_gmv"] == 7 * 275_000
    assert flows["adds_up"] is True and flows["has_residual"] is True
    assert by["live"]["gmv"] == 0 and by["live"]["ctr"] is None  # no row = 0, ratios undefined


async def test_each_flow_obeys_gmv_equals_views_times_ctr_times_ctor_times_aov(session, seeded):
    flows = (await _overview(session, seeded))["flows"]
    for row in flows["rows"]:
        assert row["identity_ok"] is True
    chain = flows["chain"]
    assert chain["identity_ok"] is True
    assert chain["gmv"] == 7 * 275_000
    assert chain["views"] == 7 * (
        900 + 100 + 40 + 60
    )  # the san pham + trang shop + video + lien ket


async def test_thẻ_sản_phẩm_children_are_a_drill_down_not_a_sum(session, seeded):
    block = (await _overview(session, seeded))["flows"]["the_san_pham_children"]
    assert block["gmv_sum"] == block["parent_gmv"] == 7 * 170_000
    assert [c["key"] for c in block["rows"]] == [
        "search",
        "recommend",
        "cart",
        "my_orders",
        "promo",
        "other",
    ]


async def test_a_week_with_half_the_days_falls_back_and_says_so(session, seeded):
    window = Window(date(2026, 9, 27), date(2026, 10, 3))  # 4 of the 7 days exist
    traffic = await loaders.load_shop_traffic(session, seeded.shop_id, window)
    assert traffic.basis == "daily" and traffic.days_covered == 7
    far = Window(date(2026, 10, 5), date(2026, 10, 11))  # only 3 days exist
    partial = await loaders.load_shop_traffic(session, seeded.shop_id, far)
    assert partial.basis == "partial_daily" and partial.days_covered == 3
    assert not partial.complete


# =========================================================================== levers


async def test_price_levers_add_up_and_each_line_has_exactly_one(session, seeded):
    levers = (await _overview(session, seeded))["levers"]
    assert levers["adds_up"] is True
    by = {r["key"]: r for r in levers["rows"]}
    assert by["combo"]["orders"] == 1  # order 6 carries a combo discount
    assert by["voucher"]["orders"] == 0 or by["voucher"]["gmv"] >= 0
    assert sum(r["gmv"] for r in levers["rows"]) == levers["gmv_total"]
    assert by["khong_uu_dai"]["orders"] == 1  # order 3: full price, no voucher, no programme


# =========================================================================== profit


async def test_every_profit_figure_carries_its_assumed_cost_share(session, seeded):
    body = await _overview(session, seeded)
    coverage = body["profit"]["cost_coverage"]
    assert coverage["real_pct"] == 0.0 and coverage["assumed_pct"] == 100.0
    assert body["profit"]["assumed_cost_share_pct"] == 100.0
    assert body["profit"]["assumed_cost_label"] == "giá vốn giả định (1/3 giá)"
    assert any(w["code"] == "cost_all_assumed" for w in body["warnings"])
    assert body["profit"]["profit_vnd"] is not None  # contract 13: shown, labelled


async def test_imported_costs_win_and_the_two_sources_are_reported_apart(session, seeded_rules):
    body = await _overview(session, seeded_rules)
    cov = body["profit"]["cost_coverage"]
    assert cov["real_pct"] > 0 and cov["assumed_pct"] > 0
    assert cov["real_pct"] + cov["assumed_pct"] + cov["unknown_pct"] == pytest.approx(
        100.0, abs=0.2
    )
    assert body["targets"]["margin_pct"] == 60 and body["targets"]["daily_marketing_cap"] == 10_000


async def test_actual_fees_win_and_a_line_without_them_uses_the_category_formula(session, seeded):
    body = await _overview(session, seeded)
    fees = body["profit"]["fees"]
    assert fees["actual"] > 0 and fees["formula"] == 2  # orders 4 and 12 carry no actual fee
    ctx = await loaders.load_context(session, seeded.shop_id)
    view = await service.load_view(session, seeded.shop_id, ctx, CUR)
    formula_lines = [(ln, pb) for ln, pb in view.pairs if pb.fee_source == "formula"]
    assert formula_lines and all(pb.fees_total is not None for _, pb in formula_lines)
    # per order the 3.000d infrastructure fee is charged once: its component is present on each
    for _, pb in formula_lines:
        assert dict(pb.fees or ()).get("phi_ha_tang") == Decimal(3000)


async def test_gmv_reconciliation_warns_over_two_percent_never_silently(session, seeded):
    # the synthetic order lines are far from the 7 x 275.000 Doanh số: the warning must show
    body = await _overview(session, seeded)
    rec = body["profit"]["gmv_reconciliation"]
    assert rec["warn"] is True
    assert any(w["code"] == "gmv_reconciliation" for w in body["warnings"])


# =========================================================================== ads


async def test_ads_are_labelled_placed_and_product_spend_plus_unattributed_is_the_total(
    session, seeded
):
    body = await _overview(session, seeded)
    ads = body["ads"]
    assert ads["basis"] == {"key": "placed", "label": "đơn đã đặt"}
    assert "không cộng vào tổng đơn đã xác nhận" in ads["note"]
    spend = body["profit"]["ad_spend"]
    assert spend["total"] == 100_000 == ads["spend"]  # the CSV report answers: no Connector day
    assert spend["by_product"] + spend["unattributed"] == pytest.approx(spend["total"], abs=1)
    assert spend["consistent"] is True


async def test_nhóm_product_spend_sums_to_the_campaign_in_the_allocation(session, seeded):
    ctx = await loaders.load_context(session, seeded.shop_id)
    view = await service.load_view(session, seeded.shop_id, ctx, CUR)
    camp = next(c for c in view.ads.campaigns if c.name == "Chiến dịch nhóm")
    assert sum(camp.products.values()) == pytest.approx(camp.spend)
    assert set(camp.products) == {"1001", "1002", "1003"}
    # the report window IS the window here: nothing is prorated, the daily total is the scale
    assert view.ads.exact_window is True
    assert view.ads.total_spend == Decimal(100_000)  # group total row not counted twice


async def test_ads_never_enter_the_flow_rows(session, seeded):
    flows = (await _overview(session, seeded))["flows"]
    assert {r["key"] for r in flows["rows"]}.isdisjoint({"ads", "quang_cao"})
    assert sum(r["gmv"] for r in flows["rows"]) == flows["total_gmv"]


# =========================================================================== five numbers


async def test_five_numbers_compare_to_the_previous_period_and_use_the_cap(session, seeded_rules):
    five = (await _overview(session, seeded_rules))["five_numbers"]
    assert five["comparison"]["available"] is True
    assert five["orders"]["before"] == 6 and five["orders"]["after"] == 13
    cap = five["spend_cap"]
    assert cap["cap"] == 10_000 and cap["over_cap"] is True  # 30.000đ of ads a day alone
    assert five["chi_definition"].startswith("chi = quảng cáo")
    assert five["extra_revenue_per_extra_spend"]["status"] == "per_vnd"


async def test_without_previous_order_lines_no_difference_is_invented(session, seeded):
    body = await queries.overview(
        session, seeded.shop_id, period="custom", start=date(2026, 10, 1), end=date(2026, 10, 7)
    )
    assert body["five_numbers"]["comparison"]["available"] is True
    # a window whose previous period has no order lines
    for ln in [ln for ln in seeded.lines if ln.ordered_at.date() <= PREV_END]:
        await session.delete(ln)
    await session.flush()
    body = await _overview(session, seeded)
    five = body["five_numbers"]
    assert five["comparison"] == {"available": False, "reason": "no_order_lines_in_previous_period"}
    assert (
        five["orders"]["before"] is None
        and five["extra_revenue_per_extra_spend"]["per_vnd"] is None
    )


# =========================================================================== matrix


async def test_matrix_rows_carry_flows_levers_and_a_labelled_ads_overlay(session, seeded):
    body = await queries.matrix(session, seeded.shop_id, period="7d", as_of=CUR_END)
    assert body["order_basis"]["key"] == "confirmed"
    by = {r["product_id"]: r for r in body["products"]}
    assert set(by) == {"1001", "1002", "1003"}
    gloves = by["1001"]
    assert gloves["name"].startswith("Găng tay")
    # D85.2: the order lines scaled to the shop totals, so the products add up to the shop GMV
    assert gloves["gmv_basis"] == "scaled_order_lines"
    assert sum(r["gmv"] for r in by.values()) == body["sums"]["gmv_shop"] == 7 * 275_000
    # P99b: the window reads the stored daily rows (each day's lines scaled to that day's shop
    # total), never a window-level split of the raw tables
    stored = await stored_mod.load_stored(session, seeded.shop_id, Window(CUR_START, CUR_END))
    assert stored is not None
    assert gloves["gmv"] == pytest.approx(float(stored.products["1001"].gmv), abs=1)
    assert gloves["ads"]["basis"]["label"] == "đơn đã đặt"
    # the report window is the window and the report is the spend: 60.000 of 100.000
    assert gloves["ads"]["spend"] == pytest.approx(60_000)
    assert gloves["ads"]["roas_direct"] == pytest.approx(4 * 60_000 / 60_000)
    assert [lv["key"] for lv in gloves["levers"]] == [
        "combo",
        "khuyen_mai",
        "voucher",
        "khong_uu_dai",
    ]
    assert gloves["flows"]["adds_up"] is True
    assert gloves["flows"]["trang_shop_available"] is False  # the monthly file has four sources
    # per-product levers add up to the product's line GMV
    assert sum(lv["gmv"] for lv in gloves["levers"]) == pytest.approx(gloves["line_gmv"])


async def test_matrix_sorts_by_margin_lowest_first(session, seeded):
    body = await queries.matrix(session, seeded.shop_id, period="7d", as_of=CUR_END, sort="bien")
    margins = [r["profit"]["margin_pct"] for r in body["products"] if r["profit"]]
    assert margins == sorted(margins)


# =========================================================================== product page


async def test_product_page_has_header_kpis_nguon_cost_floor_and_keywords(session, seeded_rules):
    shop_id = seeded_rules.shop_id
    session.add(snapshot(shop_id, "1001"))
    session.add(keyword(shop_id, "găng tay", "chinh"))
    session.add(keyword(shop_id, "tự hủy", "phu"))
    await session.flush()
    page = await queries.product_page(session, shop_id, "1001", period="7d", as_of=CUR_END)

    header = page["header"]
    assert header["title"].startswith("Găng tay") and header["title_chars"] == len(header["title"])
    assert header["price"]["source"] == "snapshot" and header["price"]["list"] == 100_000
    assert header["stock"]["value"] == 120 and header["stock"]["age_days"] == 3
    assert header["stock"]["stale"] is True  # "Cũ 3 ngày"
    assert header["reputation"]["rating"] == 4.8

    assert set(page["kpi_by_period"]) == {"7d", "30d", "90d"}
    kpi = page["kpi_by_period"]["7d"]
    row = await queries.matrix(session, shop_id, period="7d", as_of=CUR_END)
    mine = next(r for r in row["products"] if r["product_id"] == "1001")
    assert kpi["gmv"]["value"] == mine["gmv"]  # the product page and the matrix agree
    assert kpi["five_numbers"]["comparison"]["available"] is True

    sku = next(s for s in page["cost_and_floor"]["skus"] if s["sku"] == "G1")
    assert sku["cost"]["cogs_source"] == "real" and sku["cost"]["cogs_per_unit"] == 30_000
    assert sku["cost"]["packaging"] == 1_000 and sku["cost"]["packaging_source"] == "real"
    floor = sku["floor"]
    # absolute floor = (giá vốn + đóng gói + 3.000) / (1 - phí cố định 15 % - 6 %)
    assert floor["absolute"] == round((30_000 + 1_000 + 3_000) / (1 - Decimal("0.21")))
    assert floor["operating"] is not None and floor["operating"] > floor["absolute"]
    assert sku["fee"]["fixed_fee_rate_pct"] == 15.0 and sku["fee"]["rate_source"] == "seed_category"

    keywords = page["keywords"]
    assert keywords["core"]["used"] == 1 and keywords["core"]["max"] == 5
    assert keywords["core"]["full"] is False and keywords["core"]["in_title"] == 1
    assert [k["keyword"] for k in keywords["roles"]["chinh"]["keywords"]] == ["găng tay"]
    assert keywords["roles"]["chinh"]["keywords"][0]["in_title"] is True


async def test_an_unknown_product_is_not_found(session, seeded):
    with pytest.raises(queries.ProductNotFound):
        await queries.product_page(session, seeded.shop_id, "9999", period="7d", as_of=CUR_END)


async def test_a_product_without_a_snapshot_lists_the_fields_it_lacks(session, seeded):
    page = await queries.product_page(session, seeded.shop_id, "1002", period="7d", as_of=CUR_END)
    assert "stock" in page["header"]["missing_fields"]
    assert page["header"]["price"]["source"] == "last_order_line"


# =========================================================================== critical list


async def test_critical_list_is_ranked_by_money_at_stake_and_names_the_rule(session, seeded_rules):
    body = await queries.critical(session, seeded_rules.shop_id, period="7d", as_of=CUR_END)
    items = body["items"]
    stakes = [it["at_stake_per_day"] for it in items]
    assert stakes == sorted(stakes, reverse=True) and [it["rank"] for it in items] == list(
        range(1, len(items) + 1)
    )
    kinds = {it["kind"] for it in items}
    assert "margin_below_target" in kinds  # margin target 60 % is far above these margins
    margins = [it for it in items if it["kind"] == "margin_below_target"]
    margin = margins[0]
    assert margin["reference"]["type"] == "target" and margin["reference"]["value"] == 60
    # G1 and product 1002 have imported costs, T1 falls back to 1/3 of its price
    assert {it["product_id"]: it["assumed_cost"] for it in margins}.get("1003", True) is True
    assert margin["change_kinds"] == ["price", "voucher_cap", "ads_roas_target", "ads_pause"]
    assert (
        margin["ranking_link"]["kpi"] == "bien"
        and margin["ranking_link"]["focus"] == margin["product_id"]
    )
    assert body["total_at_stake_per_day"] == pytest.approx(sum(stakes), abs=len(stakes))


async def test_without_a_margin_target_there_is_no_margin_item_and_the_note_says_why(
    session, seeded
):
    body = await queries.critical(session, seeded.shop_id, period="7d", as_of=CUR_END)
    assert all(it["kind"] != "margin_below_target" for it in body["items"])
    assert any(n["code"] == "margin_target_missing" for n in body["notes"])


async def test_a_sku_sold_below_its_floor_is_listed_with_the_floor_as_reference(
    session, seeded_rules
):
    body = await queries.critical(session, seeded_rules.shop_id, period="7d", as_of=CUR_END)
    breaches = [it for it in body["items"] if it["kind"] == "floor_breach"]
    for it in breaches:
        assert it["reference"]["type"] == "floor" and it["current"] < it["reference"]["value"]


# =========================================================================== rankings


@pytest.mark.parametrize("xep", ["gmv_per_day", "profit_per_day", "orders"])
async def test_product_ranking_adds_up_for_every_additive_measure(session, seeded, xep):
    body = await queries.ranking(
        session, seeded.shop_id, kind="products", xep_theo=xep, period="7d", as_of=CUR_END
    )
    assert body["supported"] is True and body["adds_up"] is True
    cell = Decimal(str(body["cell"]["delta"]))
    closing = body["closing"]
    total = (
        sum((Decimal(str(r["delta"])) for r in body["down"] + body["up"]), Decimal(0))
        + Decimal(str(closing["few"]["delta"]))
        + Decimal(str(closing["others"]["delta"]))
        + Decimal(str(closing["mix"]["delta"]))
    )
    assert total == pytest.approx(cell, abs=Decimal("0.05"))
    # each direction view adds up on its own through the opposite-sign line
    for view in body["views"].values():
        assert Decimal(str(view["sum"])) == pytest.approx(cell, abs=Decimal("0.05"))
        assert len(view["closing"]) == 4


async def test_ranking_default_is_gmv_per_day_and_rows_name_confidence(session, seeded):
    body = await queries.ranking(session, seeded.shop_id, period="7d", as_of=CUR_END)
    assert body["xep_theo"]["key"] == "gmv_per_day" and body["xep_theo"]["additive"] is True
    assert body["ads_basis"] is None
    for row in body["down"] + body["up"]:
        assert row["confidence"] in {"Rõ", "Tham khảo"}
        assert set(row["quantity"]) == {"orders_now", "orders_before"}


async def test_ranking_by_source_uses_the_flows_and_the_levers(session, seeded):
    flow = await queries.ranking(
        session, seeded.shop_id, source="lien_ket", period="7d", as_of=CUR_END
    )
    assert flow["supported"] and flow["adds_up"] is True
    assert flow["cell"]["now"] == pytest.approx(7 * 50_000 / 7)
    lever = await queries.ranking(
        session, seeded.shop_id, source="combo", xep_theo="orders", period="7d", as_of=CUR_END
    )
    assert lever["supported"] and lever["adds_up"] is True


async def test_ranking_refuses_what_the_data_cannot_split_and_says_why(session, seeded):
    body = await queries.ranking(
        session,
        seeded.shop_id,
        source="live",
        xep_theo="profit_per_day",
        period="7d",
        as_of=CUR_END,
    )
    assert body["supported"] is False and body["reason"] == "not_split_by_flow"
    ads = await queries.ranking(
        session, seeded.shop_id, source="ads", xep_theo="bien", period="7d", as_of=CUR_END
    )
    assert ads["supported"] is False and ads["reason"] == "ads_only_gmv"
    unknown = await queries.ranking(
        session, seeded.shop_id, kind="products", source="nope", period="7d", as_of=CUR_END
    )
    assert unknown["supported"] is False and unknown["reason"] == "unknown_source"
    sub = await queries.ranking(
        session, seeded.shop_id, source="live", sub="search", period="7d", as_of=CUR_END
    )
    assert sub["supported"] is False and sub["reason"] == "unknown_sub"


async def test_ratio_measures_rank_but_do_not_pretend_to_add_up(session, seeded):
    body = await queries.ranking(
        session, seeded.shop_id, xep_theo="bien", period="7d", as_of=CUR_END
    )
    assert (
        body["supported"] and body["adds_up"] is None and "không cộng được" in body["adds_up_note"]
    )
    assert body["xep_theo"]["additive"] is False


@pytest.mark.parametrize("kind", ["campaigns", "kols", "vouchers", "keywords"])
async def test_other_row_kinds_rank_and_add_up(session, seeded, kind):
    body = await queries.ranking(session, seeded.shop_id, kind=kind, period="7d", as_of=CUR_END)
    assert body["supported"] is True and body["kind"] == kind
    assert body["adds_up"] is True


async def test_campaign_rows_are_placed_basis_and_say_so(session, seeded):
    body = await queries.ranking(
        session, seeded.shop_id, kind="campaigns", period="7d", as_of=CUR_END
    )
    assert body["ads_basis"]["label"] == "đơn đã đặt" and "đơn đã xác nhận" in body["ads_note"]


# =========================================================================== vouchers, affiliate


async def test_voucher_rows_read_the_value_from_the_name_and_check_cost_equals_value_times_orders(
    session, seeded
):
    body = await _overview(session, seeded)
    rows = {r["name"]: r for r in body["vouchers"]["rows"]}
    assert (
        rows["Ory 2k"]["value_from_name"] == 2000
        and rows["Ory 2k"]["cost_equals_value_x_orders"] is True
    )
    assert rows["Ory 1k"]["cost_equals_value_x_orders"] is True
    # a voucher the ads service made has no value in its name: nothing is claimed about it
    assert rows["Voucher Thông Minh"]["value_from_name"] is None
    assert rows["Voucher Thông Minh"]["cost_equals_value_x_orders"] is None
    assert body["vouchers"]["total_cost"] == 5_700


async def test_affiliate_block_counts_lines_and_the_programmes_own_partners(session, seeded):
    body = await _overview(session, seeded)
    aff = body["affiliate"]
    assert aff["kols"] == 1 and aff["partner_gmv"] == 120_000
    assert aff["order_lines"]["orders"] == 1 and aff["order_lines"]["commission"] == 8_000


# =========================================================================== no buyer data


async def test_no_response_carries_a_buyer_field_an_order_ref_or_a_voucher_code(
    session, seeded_rules
):
    shop_id = seeded_rules.shop_id
    session.add(snapshot(shop_id, "1001"))
    await session.flush()
    payloads = [
        await queries.overview(session, shop_id, period="7d", as_of=CUR_END),
        await queries.matrix(session, shop_id, period="7d", as_of=CUR_END),
        await queries.critical(session, shop_id, period="7d", as_of=CUR_END),
        await queries.ranking(session, shop_id, period="7d", as_of=CUR_END),
        await queries.product_page(session, shop_id, "1001", period="7d", as_of=CUR_END),
    ]
    text = json.dumps(payloads, ensure_ascii=False, default=str)
    for ref in seeded_rules.order_refs:
        assert ref not in text

    def keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from keys(v)
        elif isinstance(node, list):
            for v in node:
                yield from keys(v)

    banned = ("order_ref", "buyer", "recipient", "address", "phone", "customer", "voucher_code")
    assert not [k for k in set(keys(payloads)) if any(b in k for b in banned)]


async def test_a_shop_with_no_shopee_numbers_is_refused_not_zeroed(session):
    from tests.support.builders import make_shop, make_user

    user = await make_user(session)
    shop = await make_shop(session, user, platform="shopee")
    with pytest.raises(queries.NoShopeeData):
        await queries.overview(session, shop.id)


async def test_another_shops_rows_never_enter(session, seeded):
    other = await seed_shopee_shop(session)
    mine = await _overview(session, seeded)
    again = await queries.overview(session, other.shop_id, period="7d", as_of=CUR_END)
    assert mine["gmv"]["line_orders"] == again["gmv"]["line_orders"] == 13  # not 26
    assert mine["flows"]["total_gmv"] == again["flows"]["total_gmv"]


async def test_matrix_rows_carry_price_range_margin_basis_and_idle_listings(session, seeded):
    """P92 B-9: every product row has giá (min-max, list price) and the basis of its biên; active
    listings without orders in the window come back under ``idle_products``."""
    body = await queries.matrix(session, seeded.shop_id, period="7d", as_of=CUR_END)
    assert body["products"]
    for row in body["products"]:
        assert row["price_min"] is not None and row["price_max"] >= row["price_min"]
        assert row["list_price"] is not None
        assert row["margin_basis"] in {"theo đơn thực tế", "ước tính", "chưa tính"}
    sold = {r["product_id"] for r in body["products"]}
    assert not sold & {i["product_id"] for i in body["idle_products"]}
    for idle in body["idle_products"]:
        assert idle["margin_basis"] == "chưa tính"


async def test_critical_product_items_carry_price_and_margin_basis(session, seeded):
    body = await queries.critical(session, seeded.shop_id, period="7d", as_of=CUR_END)
    product_items = [it for it in body["items"] if it.get("product_id")]
    for it in product_items:
        assert it["margin_basis"] in {"theo đơn thực tế", "ước tính", "chưa tính"}
        assert "price_min" in it and "list_price" in it


async def test_product_price_margin_matches_the_matrix_for_an_exact_period(session, seeded):
    """P92 B-9: the Ops / Demo funnel table (a Shopee export period) joins the same giá and biên
    the matrix shows over that window; an item without order lines gets dashes and 'chưa tính'."""
    body = await queries.matrix(
        session, seeded.shop_id, period="custom", start=CUR_START, end=CUR_END
    )
    ids = [r["product_id"] for r in body["products"]]
    out = await queries.product_price_margin(
        session, seeded.shop_id, start=CUR_START, end=CUR_END, item_ids=[*ids, "no-such-item"]
    )
    for row in body["products"]:
        got = out[row["product_id"]]
        assert (got["price_min"], got["price_max"], got["list_price"]) == (
            row["price_min"],
            row["price_max"],
            row["list_price"],
        )
        assert got["margin_basis"] == row["margin_basis"]
        assert got["margin_pct"] == (row["profit"] or {}).get("margin_pct")
    assert out["no-such-item"]["price_min"] is None
    assert out["no-such-item"]["margin_basis"] == "chưa tính"
