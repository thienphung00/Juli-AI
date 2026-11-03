"""P90 step 9c: card references on the analytics payloads (Demo sees published cards only, Ops
drafts too) and the payload fields the Quyết định / Sản phẩm screens read (per-product numbers
1 and 2, Thẻ sản phẩm children, daily series, ad campaigns, snapshot versions, freshness).
SQLite; synthetic shop."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest

from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.shopee_analytics import queries
from juli_backend.services.shopee_recommendations import store
from juli_backend.services.shopee_recommendations.cards import build_card
from juli_backend.services.shopee_recommendations.loader import load_env
from juli_backend.services.shopee_recommendations.model import Candidate
from tests.support.shopee_analytics import CUR_END, _daily, snapshot
from tests.support.shopee_reco import AS_OF, seed_reco_shop

NOW = datetime(2026, 10, 8, 3, 0)
CRIT = {
    "id": "product:1001:ctor:median",
    "kind": "below_shop_median",
    "kpi": "ctor",
    "level": "product",
    "flow": None,
    "at_stake_per_day": 1000,
    "at_stake_per_month": 30000,
    "deviation_pct": -25.0,
    "money_basis": "confirmed",
    "cause": {"stage": "ctor", "text": ""},
}
REF_KEYS = {"id", "family", "title", "at_stake_per_month"}
P7 = {"period": "7d", "as_of": CUR_END}


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    env = await load_env(session, seeded.shop_id, as_of=AS_OF)
    cands = [
        Candidate(
            "product_discount",
            ("1001",),
            {"discount_pct": 15},
            critical=CRIT,
            wiring_key="ctor",
        ),
        Candidate("bundle_deal", ("1003",), {"tier2_pct": 4, "tier3_pct": 6}, wiring_key="aov"),
        Candidate(
            "ads_budget", (), {"daily_budget": 36_000}, campaign_key="cgroup1", wiring_key="views"
        ),
    ]
    ids = []
    for n, cand in enumerate(cands, 1):
        card = build_card(env, cand, now=NOW)
        card["rank"] = {"position": n, "score": 1, "detail": {}, "mode": "x", "explore": False}
        ids.append(
            await store.save_card(
                session, seeded.shop_id, card, cycle="2026-10", position=n, now=NOW
            )
        )
    await session.commit()
    return seeded, ids


async def _screens(session, sid, audience):
    out = {}
    for screen, body in (
        ("matrix", await queries.matrix(session, sid, **P7)),
        ("critical", await queries.critical(session, sid, **P7)),
        ("ranking", await queries.ranking(session, sid, kind="products", **P7)),
        ("ranking_campaigns", await queries.ranking(session, sid, kind="campaigns", **P7)),
        ("product", await queries.product_page(session, sid, "1001", period="7d", as_of=CUR_END)),
    ):
        kind = "ranking" if screen.startswith("ranking") else screen
        out[screen] = await reco.attach_card_refs(session, sid, kind, body, audience=audience)
    return out


def _rows(body):
    return [*body.get("down", []), *body.get("up", [])]


async def test_the_seller_sees_published_cards_only_and_ops_sees_drafts_too(session, shop):
    seeded, ids = shop
    sid = seeded.shop_id
    seller = await _screens(session, sid, "seller")
    assert all("card" not in r for r in seller["matrix"]["products"])
    assert "card" not in seller["product"] and seller["product"]["cards"] == []
    ops = await _screens(session, sid, "ops")
    row = next(r for r in ops["matrix"]["products"] if r["product_id"] == "1001")
    assert set(row["card"]) == REF_KEYS and row["card"]["id"] == str(ids[0])
    assert row["card"]["family"] == "promotion" and row["card"]["at_stake_per_month"] == 30000
    await reco.publish(session, sid, [ids[0]], now=NOW)
    await session.commit()
    seller = await _screens(session, sid, "seller")
    by_id = {r["product_id"]: r for r in seller["matrix"]["products"]}
    assert by_id["1001"]["card"]["id"] == str(ids[0])
    assert "card" not in by_id["1003"]  # its card is still a draft
    assert seller["product"]["card"]["id"] == str(ids[0])
    assert [c["id"] for c in seller["product"]["cards"]] == [str(ids[0])]


async def test_a_critical_item_matches_its_own_card_by_id_and_a_row_without_one_has_no_key(
    session, shop
):
    seeded, ids = shop
    await reco.publish(session, seeded.shop_id, None, now=NOW)
    await session.commit()
    body = await queries.critical(session, seeded.shop_id, **P7)
    index = await reco.refs.load_index(session, seeded.shop_id, audience="seller")
    own = {"id": CRIT["id"], "product_id": "1001", "kpi": "ctor"}
    assert index.for_critical(own)["id"] == str(ids[0])
    same_metric = {"id": "product:1001:ctor", "product_id": "1001", "kpi": "ctor"}
    assert index.for_critical(same_metric)["id"] == str(ids[0])  # same product x metric
    other = {"id": "product:1001:bien", "product_id": "1001", "kpi": "bien"}
    assert index.for_critical(other) is None
    out = await reco.attach_card_refs(session, seeded.shop_id, "critical", body, audience="seller")
    assert all(
        ("card" in i) == (i.get("product_id") == "1001" and i["kpi"] == "ctor")
        for i in out["items"]
    )


async def test_ranking_rows_and_campaign_rows_carry_their_cards(session, shop):
    seeded, ids = shop
    await reco.publish(session, seeded.shop_id, None, now=NOW)
    await session.commit()
    index = await reco.refs.load_index(session, seeded.shop_id, audience="seller")
    shared = {"id": "1001"}
    payload = {
        "supported": True,
        "kind": "products",
        "source": "all",
        "xep_theo": {"key": "gmv_per_day"},
        "down": [shared, {"id": "1002"}],
        "up": [{"id": "1003"}],
        "views": {"down": {"rows": [shared]}},
    }
    n = reco.refs.attach(index, "ranking", payload)
    assert n == 2 and payload["down"][0]["card"]["id"] == str(ids[0])
    assert "card" not in payload["down"][1] and payload["up"][0]["card"]["id"] == str(ids[1])
    camp = {
        "supported": True,
        "kind": "campaigns",
        "source": "all",
        "xep_theo": {"key": "gmv_per_day"},
        "down": [{"id": "cgroup1"}, {"id": "other"}],
        "up": [],
    }
    assert reco.refs.attach(index, "ranking", camp) == 1
    assert camp["down"][0]["card"]["id"] == str(ids[2]) and "card" not in camp["down"][1]
    refused = {"supported": False, "down": [{"id": "1001"}]}
    assert reco.refs.attach(index, "ranking", refused) == 0
    with pytest.raises(ValueError):
        reco.refs.attach(index, "overview", {})


def test_the_better_matching_card_wins_for_a_product():
    def ref(i, pos, kpi, flow=None, stake=1.0):
        return reco.refs.CardRef(i, "promotion", i, stake, pos, ("1",), None, kpi, flow, None)

    index = reco.refs.CardIndex(
        [ref("a", 1, "aov"), ref("b", 2, "ctor", "video"), ref("c", 3, "ctor")]
    )
    assert index.for_product("1")["id"] == "a"  # best position when nothing narrows it
    assert index.for_product("1", kpi="ctor")["id"] == "b"
    assert index.for_product("1", kpi="ctor", source="video")["id"] == "b"
    assert index.for_product("1", source="video")["id"] == "b"
    assert index.for_product("2") is None


# ------------------------------------------------------------------------ the data gaps


async def test_matrix_rows_carry_numbers_1_and_2_and_the_card_children_when_stored(session):
    seeded = await seed_reco_shop(session)
    sid = seeded.shop_id
    body = await queries.matrix(session, sid, **P7)
    row = next(r for r in body["products"] if r["product_id"] == "1001")
    assert {"discount", "extra_revenue_per_extra_spend", "comparison"} == set(row["five_numbers"])
    assert row["five_numbers"]["discount"]["pct_after"] is not None
    assert row["card_children"] is None  # no per-source day rows stored: nothing is invented
    for i in range(7):
        day = CUR_END - timedelta(days=i)
        for seg, views in (("all", 400), ("search", 250), ("recommend", 150)):
            session.add(
                _daily(
                    sid,
                    day,
                    "product_card",
                    seg,
                    impressions=views,
                    clicks=20,
                    orders=1,
                    gmv=90_000,
                    dataset="item_traffic_sources",
                    item_id="1001",
                )
            )
    await session.commit()
    body = await queries.matrix(session, sid, **P7)
    row = next(r for r in body["products"] if r["product_id"] == "1001")
    kids = {k["key"]: k for k in row["card_children"]}
    assert kids["search"]["views"] == 7 * 250 and kids["search"]["label"] == "Tìm kiếm"
    assert kids["recommend"]["orders"] == 7 and kids["cart"]["views"] is None


async def test_the_product_page_has_daily_series_ad_campaigns_versions_and_freshness(session):
    seeded = await seed_reco_shop(session)
    sid = seeded.shop_id
    session.add(
        snapshot(
            sid,
            "1001",
            captured_at=datetime(2026, 10, 2),
            title="Găng tay cũ",
            image_urls=["https://img.example/old.jpg"],
            current_price=D(95_000),
        )
    )
    session.add(snapshot(sid, "1001", captured_at=datetime(2026, 10, 6)))
    await session.commit()
    page = await queries.product_page(session, sid, "1001", period="7d", as_of=CUR_END)
    versions = page["header"]["versions"]  # newest first
    assert [v["captured_at"][:10] for v in versions] == ["2026-10-06", "2026-10-04", "2026-10-02"]
    assert versions[0]["changes"] == []  # the 6th repeats the 4th
    assert {"title", "price", "images", "cover"} == set(versions[1]["changes"])
    assert versions[2]["first"] is True and versions[2]["changes"] == []
    assert versions[2]["title"] == "Găng tay cũ" and versions[2]["cover_url"].endswith("old.jpg")
    daily = page["daily"]
    assert daily["source"] == "order_lines" and daily["days"]
    assert sum(d["orders"] for d in daily["days"]) > 0 and daily["days"][0]["views"] is None
    ads = page["ads"]["campaigns"]
    assert isinstance(ads, list)
    for c in ads:
        assert {"campaign_key", "name", "spend", "roas_direct"} <= set(c)
    fresh = page["freshness"]
    assert fresh["as_of"] == CUR_END.isoformat()
    assert fresh["datasets"]["shop_overview"]["age_days"] == 0
    assert fresh["datasets"]["order_lines"]["kind"] == "orders"
    # per-source day rows give the real daily series
    for i in range(7):
        session.add(
            _daily(
                sid,
                CUR_END - timedelta(days=i),
                "product_card",
                "all",
                impressions=300,
                clicks=15,
                orders=2,
                gmv=180_000,
                dataset="item_traffic_sources",
                item_id="1001",
            )
        )
    await session.commit()
    page = await queries.product_page(session, sid, "1001", period="7d", as_of=CUR_END)
    assert page["daily"]["source"] == "item_traffic_sources"
    assert len(page["daily"]["days"]) == 7 and page["daily"]["days"][0]["views"] == 300


async def test_the_overview_says_how_fresh_each_dataset_is(session):
    seeded = await seed_reco_shop(session)
    body = await queries.overview(session, seeded.shop_id, **P7)
    f = body["freshness"]
    assert f["as_of"] == CUR_END.isoformat()
    assert f["datasets"]["traffic_overview"]["latest_day"] == CUR_END.isoformat()
    assert f["datasets"]["traffic_overview"]["kind"] == "daily"
    assert "item_snapshots" in f["datasets"]
