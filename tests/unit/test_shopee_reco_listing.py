"""P90 step 9c: the listing family (title, keyword, cover_image, price_display) -- the pure
audit and rewrite, the generators on a synthetic shop, the card (no certain layer, a predicted
range), the execution sheet and its read-back through ``card_events.verification``.
SQLite; every figure and title is invented."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from juli_backend.models.market import MarketKeywordMetric
from juli_backend.services.card_events import verification
from juli_backend.services.shopee_analytics.critical import build_critical
from juli_backend.services.shopee_recommendations import config, service
from juli_backend.services.shopee_recommendations import generators as gen
from juli_backend.services.shopee_recommendations import listing as lst
from juli_backend.services.shopee_recommendations.cards import build_card
from juli_backend.services.shopee_recommendations.kinds import KINDS, WIRING, kinds_of
from juli_backend.services.shopee_recommendations.loader import load_env
from juli_backend.services.shopee_recommendations.service import recompute_card
from tests.support.shopee_analytics import _daily, keyword
from tests.support.shopee_reco import AS_OF, rule, seed_reco_shop

NOW = datetime(2026, 10, 8, 3, 0)
CTR_CRIT = {
    "id": "product:1002:ctr:median",
    "kind": "below_shop_median",
    "kpi": "ctr",
    "level": "product",
    "flow": None,
    "deviation_pct": -30.0,
    "at_stake_per_day": 2000,
    "at_stake_per_month": 60000,
    "money_basis": "confirmed",
    "cause": {"stage": "ctr", "text": ""},
}


# ===================================================================== pure: the title audit


def test_the_audit_names_missing_late_and_too_long():
    long_head = "Nước rửa chén " + "rất " * 22  # the keyword starts after the 100th character
    title = long_head + "tinh dầu sả"
    a = lst.audit_title(title, ["nước rửa chén", "tinh dầu sả", "túi đay"])
    assert a.placed == ("nước rửa chén",)
    assert a.late == ("tinh dầu sả",)
    assert a.missing == ("túi đay",)
    assert not a.too_long and a.issue_count == 2
    assert lst.audit_title("a" * 121, []).too_long


def test_a_missing_core_keyword_is_written_as_a_phrase_at_the_head():
    title = "Miếng rửa chén xơ mướp loại lớn tự nhiên"
    p = lst.propose_title(title, ["bàn chải tre", "miếng rửa chén xơ mướp"])
    assert p is not None
    assert p.title.startswith("bàn chải tre")  # missing: written at the head
    assert "Miếng rửa chén xơ mướp" in p.title  # placed: kept as written
    assert p.after.missing == () and p.after.late == () and len(p.title) <= 120
    assert p.inserted == ("bàn chải tre",)


def test_a_late_keyword_is_moved_up_with_the_shops_own_words():
    filler = "chất lượng rất tốt dùng bền lâu ngày không lo bám bẩn "  # 55 chars
    title = filler + filler + "Dầu gội bồ kết"
    p = lst.propose_title(title, ["dầu gội bồ kết"])
    assert p is not None and p.moved == ("dầu gội bồ kết",) and p.inserted == ()
    assert p.title.startswith("Dầu gội bồ kết")
    assert p.after.late == () and len(p.title) <= 120


def test_a_title_over_120_characters_is_cut_at_a_word_boundary_and_keeps_its_keywords():
    title = "Nước rửa chén " + " ".join(f"từ{n}" for n in range(1, 40))
    assert len(title) > 120
    p = lst.propose_title(title, ["nước rửa chén"])
    assert p is not None and 0 < len(p.title) <= 120
    assert p.title.startswith("Nước rửa chén") and not p.title.endswith(" ")
    assert title.startswith(p.title)  # a prefix: only trailing words went


def test_a_proposal_never_exceeds_120_characters_and_never_holds_a_banned_term():
    titles = [
        "Lumi Miếng rửa chén xơ mướp rẻ nhất thị trường " + "loại lớn " * 12,
        "Combo " + "dầu gội thảo dược " * 9,
        "Khăn lau đa năng " + "siêu thấm hút " * 10,
    ]
    cores = [
        ["bàn chải tre", "miếng rửa chén xơ mướp", "lumi rửa chén", "xơ mướp", "rửa chén"],
        ["dầu gội thảo dược", "dầu gội bồ kết", "dầu xả", "tóc mềm", "gội đầu"],
        ["khăn lau", "khăn đa năng", "lau bếp", "thấm hút", "microfiber"],
    ]
    for title, core in zip(titles, cores, strict=True):
        p = lst.propose_title(title, core, seller_banned=["combo"])
        assert p is not None
        assert len(p.title) <= config.MAX_TITLE_CHARS
        assert lst.is_clean(p.title, ["combo"])
        assert "rẻ nhất" not in p.title.lower() and "combo" not in p.title.lower()
        assert p.after.issue_count <= p.before.issue_count


def test_a_keyword_that_cannot_fit_the_visible_characters_is_reported_not_squeezed():
    core = [f"cụm từ khoá số {n} khá dài dòng" for n in range(1, 6)]
    p = lst.propose_title("Sản phẩm thử", core)
    assert p is not None and p.unplaced
    assert len(p.title) <= 120
    for kw in core:
        if kw not in p.unplaced:
            assert lst.fold(kw) in lst.fold(p.title)


def test_a_keyword_with_a_banned_term_is_not_inserted():
    p = lst.propose_title("Khăn lau bếp", ["khăn rẻ nhất", "lau bếp thông minh"])
    assert p is not None and "rẻ nhất" not in p.title and "khăn rẻ nhất" in p.unplaced


def test_a_title_with_nothing_to_fix_gets_no_proposal():
    assert lst.propose_title("Nước rửa chén Lumi 500ml", ["nước rửa chén"]) is None
    assert lst.propose_title("Nước rửa chén Lumi 500ml", []) is None


def test_proposals_are_deterministic():
    args = ("Lumi nước rửa chén tinh dầu", ["bàn chải tre", "tinh dầu sả"])
    assert lst.propose_title(*args) == lst.propose_title(*args)


# =========================================================================== pure: keywords


def _kw(word, role, volume=None, difficulty=None):
    return lst.Keyword(word, role, volume, difficulty)


def test_a_free_chinh_slot_takes_the_phu_keyword_with_the_most_searches():
    li = lst.Listing(
        "1",
        "t",
        keywords=(_kw("a", "chinh", 500), _kw("b", "phu", 900), _kw("c", "phu", 1200)),
    )
    p = lst.propose_keywords(li)
    assert p is not None and p.promote.keyword == "c" and p.demote is None
    assert p.core_after == ("a", "c")


def test_a_full_core_swaps_only_for_clearly_more_searches():
    core = tuple(_kw(f"k{n}", "chinh", 1000 + n) for n in range(5))
    weak = _kw("weak", "chinh", 200)
    core = (*core[:4], weak)
    strong = _kw("strong", "phu", 400)  # 2 x the weakest
    p = lst.propose_keywords(lst.Listing("1", "t", keywords=(*core, strong)))
    assert p is not None and p.promote.keyword == "strong" and p.demote.keyword == "weak"
    assert len(p.core_after) == config.MAX_CORE_KEYWORDS and "weak" not in p.core_after
    close = _kw("close", "phu", 250)  # under 1.5 x
    assert lst.propose_keywords(lst.Listing("1", "t", keywords=(*core, close))) is None


def test_no_volume_no_keyword_proposal():
    core = tuple(_kw(f"k{n}", "chinh", None) for n in range(5))
    assert (
        lst.propose_keywords(lst.Listing("1", "t", keywords=(*core, _kw("x", "phu", 5000)))) is None
    )
    free = lst.Listing("1", "t", keywords=(_kw("x", "phu", None),))
    assert lst.propose_keywords(free) is None
    low = lst.Listing("1", "t", keywords=(_kw("x", "phu", config.KEYWORD_MIN_VOLUME - 1),))
    assert lst.propose_keywords(low) is None


# ========================================================================== pure: unit price


def test_the_unit_price_is_read_from_the_size_in_the_title():
    u = lst.unit_price("Nước rửa chén Ory 500ml", D(90_000))
    assert u is not None and u.per_label == "100ml" and u.per_price == D(18_000)
    assert u.line(D(90_000)) == "90.000đ / 500ml ≈ 18.000đ mỗi 100ml"
    k = lst.unit_price("Bột giặt 2kg", D(100_000))
    assert k is not None and k.per_label == "100g" and k.per_price == D(5_000)
    n = lst.unit_price("Viên rửa chén 30 viên", D(90_000))
    assert n is not None and n.per_label == "viên" and n.per_price == D(3_000)
    assert lst.unit_price("Găng tay tự hủy", D(90_000)) is None
    assert lst.unit_price("Nước 100ml", D(90_000)) is None  # already per 100 ml
    assert lst.unit_price("Nước 500ml", None) is None


# ========================================================================== the vocabulary


def test_the_listing_family_is_wired_to_views_and_ctr():
    assert set(kinds_of("listing")) == {"title", "keyword", "cover_image", "price_display"}
    for kind in kinds_of("listing"):
        s = KINDS[kind]
        assert s.target_metric in ("views", "ctr")
        assert s.sim_kind is None
    assert WIRING["views"][:2] == ("title", "keyword") and WIRING["ctr"][:1] == ("cover_image",)
    assert KINDS["title"].verify_kind == "title"
    assert KINDS["cover_image"].verify_kind == KINDS["price_display"].verify_kind == "images"
    assert KINDS["keyword"].verify_kind is None


# ===================================================================== generators on a shop


def _metric(word: str, volume: int) -> MarketKeywordMetric:
    return MarketKeywordMetric(
        platform="shopee",
        source="shopeeanalytics",
        keyword=word,
        seed=word,
        collected_on=date(2026, 10, 5),
        status="ok",
        volume=volume,
        difficulty=D(40),
        extra={},
    )


@pytest.fixture
async def env(session):
    seeded = await seed_reco_shop(session)
    sid = seeded.shop_id
    session.add_all(
        [
            keyword(sid, "túi rác sinh học", "chinh", "1001"),  # not in the title
            keyword(sid, "găng tay tự hủy", "chinh", "1001"),  # in the title
            keyword(sid, "găng tay nhà bếp", "phu", "1001"),
            keyword(sid, "nước rửa chén", "chinh", "1002"),
            keyword(sid, "rửa chén sinh học", "phu", "1002"),
            _metric("túi rác sinh học", 900),
            _metric("găng tay tự hủy", 400),
            _metric("găng tay nhà bếp", 2000),
            _metric("nước rửa chén", 300),
            _metric("rửa chén sinh học", 800),
        ]
    )
    await session.commit()
    e = await load_env(session, sid, as_of=AS_OF)
    assert e is not None
    return e


def _card(env, cand):
    card = build_card(env, cand, now=NOW)
    assert card is not None
    return card


async def test_the_env_reads_the_listing_keyword_list_and_market_numbers(env):
    li = env.listings["1001"]
    assert li.title.startswith("Găng tay") and li.cover_url == "https://img.example/synthetic.jpg"
    assert li.price == D(90_000)
    assert [(k.keyword, k.volume) for k in li.core()] == [
        ("túi rác sinh học", 900),
        ("găng tay tự hủy", 400),
    ]


async def test_a_title_card_is_a_traffic_lever_with_a_predicted_range_only(env):
    (cand,) = gen.gen_title(env, None, "1001")
    new = cand.inputs["title"]
    assert len(new) <= 120 and new.startswith("túi rác sinh học")
    assert lst.audit_title(new, ["túi rác sinh học", "găng tay tự hủy"]).issue_count == 0
    card = _card(env, cand)
    assert card["family"] == "listing" and card["change_kind"] == "title"
    assert card["wiring"]["critical_metric"] == "views"
    assert card["metric"]["key"] == "views"
    assert card["certain"]["traffic_lever"] is True and card["five_numbers"] is None
    assert card["floor"]["ok"] and card["spend"]["card_dchi_per_day"] == 0
    money = card["predicted"]["money_per_month"]
    assert money["certain"] == {"dgmv": 0.0, "dprofit": 0.0, "dchi": 0.0}
    p10, p90 = money["predicted"]["p10"]["dgmv"], money["predicted"]["p90"]["dgmv"]
    assert 0 < p10 < p90  # a lift on the Thẻ sản phẩm GMV of the product
    assert card["predicted"]["base"] == "gmv_the_san_pham"
    assert card["whatif"]["text_fields"][0]["key"] == "title"
    assert card["change"]["before"]["title"] == env.listings["1001"].title
    assert card["change"]["after"]["title"] == new and card["change"]["after"]["chars"] == len(new)


async def test_the_title_sheet_carries_the_read_back_through_platform_items_name(env):
    (cand,) = gen.gen_title(env, None, "1001")
    sheet = _card(env, cand)["execution_sheet"]
    (change,) = sheet["changes"]
    assert change == {
        "change_kind": "title",
        "target": {"item_id": "1001"},
        "expected": {"title": cand.inputs["title"]},
    }
    assert change["change_kind"] in verification.CHANGE_KINDS
    assert (
        sheet["steps"][0]["field"] == "Tên sản phẩm"
        and sheet["steps"][0]["copy"] == change["expected"]["title"]
    )
    assert sheet["revert_steps"][0]["after"] == env.listings["1001"].title
    assert sheet["page"]["verified"] is True and "banhang.shopee.vn" in sheet["page"]["deep_link"]
    t0 = datetime(2026, 10, 9, 8, 0, tzinfo=UTC)
    ex = verification.ExecutedChange(
        shop_id=uuid.uuid4(),
        card_id=uuid.uuid4(),
        execution_ref="x",
        change_kind=change["change_kind"],
        target=change["target"],
        expected=change["expected"],
        executed_at=t0,
    )
    seen = verification.Observation({"title": cand.inputs["title"]}, t0 + timedelta(hours=3))
    assert verification.evaluate(ex, [seen], t0 + timedelta(hours=4)).outcome == "verified"
    stale = verification.Observation({"title": env.listings["1001"].title}, t0 + timedelta(hours=3))
    assert verification.evaluate(ex, [stale], t0 + timedelta(hours=49)).outcome == "mismatch"


async def test_an_edited_title_is_recomputed_and_a_bad_one_is_refused(env):
    (cand,) = gen.gen_title(env, None, "1001")
    card = {**_card(env, cand), "id": "c1"}
    ok = recompute_card(env, card, {"title": "Túi rác sinh học găng tay tự hủy STAHAUS"}, now=NOW)
    assert ok is not None and ok["certain"]["audit_after"]["core_missing"] == []
    assert recompute_card(env, card, {"title": "x" * 121}, now=NOW) is None
    assert recompute_card(env, card, {"title": "   "}, now=NOW) is None
    assert recompute_card(env, card, {"title": "Găng tay chữa khỏi mọi bệnh"}, now=NOW) is None


async def test_the_sellers_banned_terms_are_stripped_and_never_proposed(session):
    seeded = await seed_reco_shop(session)
    sid = seeded.shop_id
    session.add(rule(sid, "banned_terms", "", ["sinh học"]))
    session.add(keyword(sid, "túi rác", "chinh", "1001"))
    await session.commit()
    env = await load_env(session, sid, as_of=AS_OF)
    assert env.banned_terms == ("sinh học",)
    (cand,) = gen.gen_title(env, None, "1001")
    assert "sinh học" not in cand.inputs["title"].lower()
    assert cand.extra["proposal"]["banned_removed"] == ["sinh học"]
    assert _card(env, cand)["certain"]["banned_terms_in_title"] == 0


async def test_a_keyword_card_promotes_within_the_five_and_is_advisory(env):
    (cand,) = gen.gen_keyword(env, None, "1001")
    assert cand.inputs == {"promote": "găng tay nhà bếp", "demote": None}
    card = _card(env, cand)
    assert card["family"] == "listing" and card["change_kind"] == "keyword"
    assert card["change"]["after"]["core"][-1] == "găng tay nhà bếp"
    assert len(card["change"]["after"]["core"]) <= config.MAX_CORE_KEYWORDS
    sheet = card["execution_sheet"]
    assert sheet["page"]["verified"] is False and sheet["page"]["deep_link"] is None
    assert sheet["changes"][0]["change_kind"] == "keyword"
    assert sheet["changes"][0]["change_kind"] not in verification.CHANGE_KINDS
    assert "không có bước đọc lại" in sheet["readback"]["note"]


async def test_cover_and_price_display_are_advisory_and_verified_by_the_cover_url(env):
    (cover,) = gen.gen_cover_image(env, CTR_CRIT, "1002")
    (price,) = gen.gen_price_display(env, CTR_CRIT, "1002")
    assert gen.gen_cover_image(env, None, "1002") == []  # needs the low-CTR evidence
    for cand, label in ((cover, "Ảnh bìa mới"), (price, "Ghi thêm lên ảnh bìa")):
        card = _card(env, cand)
        assert card["wiring"]["critical_metric"] == "ctr" and card["metric"]["key"] == "ctr"
        assert card["predicted"]["money_per_month"]["certain"]["dgmv"] == 0.0
        assert label in card["change"]["after"]["text"]
        (change,) = card["execution_sheet"]["changes"]
        assert change["change_kind"] == "images"
        assert change["expected"] == {
            "image_urls": {"changed_from": ["https://img.example/synthetic.jpg"]}
        }
    assert "90.000đ / 500ml ≈ 18.000đ mỗi 100ml" in price.extra["line"]
    sheet = _card(env, price)["execution_sheet"]
    assert sheet["steps"][0]["copy"] == price.extra["line"]


async def test_price_display_needs_a_size_in_the_title(env):
    assert gen.gen_price_display(env, CTR_CRIT, "1003") == []  # "Túi rác tự hủy sinh học"


def test_a_new_cover_is_read_back_when_the_first_image_url_changes():
    t0 = datetime(2026, 10, 9, 8, 0, tzinfo=UTC)
    expected = {"image_urls": {"changed_from": ["https://img.example/a.jpg"]}}
    ex = verification.ExecutedChange(
        shop_id=uuid.uuid4(),
        card_id=uuid.uuid4(),
        execution_ref="y",
        change_kind="images",
        target={"item_id": "1"},
        expected=expected,
        executed_at=t0,
    )
    later = t0 + timedelta(hours=2)
    same = verification.Observation({"image_urls": ["https://img.example/a.jpg"]}, later)
    new = verification.Observation({"image_urls": ["https://img.example/b.jpg", "x"]}, later)
    assert verification.evaluate(ex, [new], later).outcome == "verified"
    assert verification.evaluate(ex, [same], later).outcome is None  # pending
    assert verification.evaluate(ex, [same], t0 + timedelta(hours=49)).outcome == "mismatch"
    assert verification.evaluate(ex, [], t0 + timedelta(hours=49)).outcome == "not_seen"
    assert not verification.same_value({"changed_from": ["a"]}, [])
    assert verification.same_value({"changed_from": ["a"]}, ["b"])


# ====================================================================== in the whole flow


async def test_listing_cards_are_generated_ranked_and_persisted_with_the_other_families(
    session,
):
    seeded = await seed_reco_shop(session)
    sid = seeded.shop_id
    session.add_all(
        [
            keyword(sid, "túi rác sinh học", "chinh", "1001"),
            keyword(sid, "găng tay nhà bếp", "phu", "1001"),
            _metric("túi rác sinh học", 900),
            _metric("găng tay nhà bếp", 2000),
        ]
    )
    await session.commit()
    report = await service.generate_cards(session, sid, now=NOW, as_of=AS_OF)
    assert report.by_kind["title"] >= 1
    assert report.by_family["listing"] >= 1
    rows = await service.list_cards(session, sid, audience="ops", family="listing")
    assert rows["cards"] and all(c["family"] == "listing" for c in rows["cards"])
    assert all(c["certain_summary"]["dgmv_month"] == 0 for c in rows["cards"])
    # one change per product per window: a product has at most one listing card in the ranking
    items = [tuple(c["scope"]["product_ids"]) for c in rows["cards"]]
    assert len(items) == len(set(items))


# ============================================================ Lượt xem (search) critical item


async def test_a_product_low_on_search_views_is_a_critical_item_wired_to_title_and_keyword(
    session,
):
    seeded = await seed_reco_shop(session)
    sid = seeded.shop_id
    per_day = {"1001": 600, "1002": 500, "1003": 40}  # 1003 has far fewer search views
    for item, views in per_day.items():
        for i in range(30):
            day = date(2026, 9, 8) + timedelta(days=i)
            session.add(
                _daily(
                    sid,
                    day,
                    "product_card",
                    "all",
                    impressions=views * 2,
                    clicks=40,
                    orders=1,
                    gmv=90_000,
                    dataset="item_traffic_sources",
                    item_id=item,
                )
            )
            session.add(
                _daily(
                    sid,
                    day,
                    "product_card",
                    "search",
                    impressions=views,
                    clicks=30,
                    orders=1,
                    gmv=90_000,
                    dataset="item_traffic_sources",
                    item_id=item,
                )
            )
    await session.commit()
    env = await load_env(session, sid, as_of=AS_OF)
    crit = build_critical(env.ctx, env.view, {})
    items = [i for i in crit["items"] if i["kpi"] == "views"]
    assert [i["product_id"] for i in items] == ["1003"]
    item = items[0]
    assert item["id"] == "product:1003:views:median" and item["at_stake_per_day"] > 0
    assert item["change_kinds"][:2] == ["title", "keyword"]
    assert item["ranking_link"]["sub"] == "search"
    # the generator answers it with kinds section 8 allows for Lượt xem
    answered = {c.kind for c in gen.generate(env, crit) if c.wiring_key == "views"}
    assert answered <= set(WIRING["views"])
