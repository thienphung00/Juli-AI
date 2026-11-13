"""P92: the Demo and Ops routes of the builder, the picker, the drafts, Loại trừ sản phẩm and the
B-8 seller pages (``/v1/demo/shopee``, ``/v1/ops/shops/{id}/shopee``). Fake model; SQLite."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from juli_backend.api.routes import shopee_builder_common as common
from juli_backend.models.ops import OpsAuditLog
from juli_backend.models.shop_proposals import ShopProposal
from tests.support.api import authenticate, build_app, client_for
from tests.support.shopee_analytics import CUR_END, _line
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_ops_shopee_dashboards import _ops_client
from tests.unit.test_shopee_builder_drafts import FakeLLM

B = "/v1/demo/shopee/builder"
EX = "/v1/demo/shopee/exclusions"
VOUCHER = {"kind": "voucher", "discount_type": "amount", "value": 5000, "min_spend": 100_000}
GIFT = {
    "kind": "gift",
    "gift": {"unit_cost": 5000},
    "trigger": {"type": "min_spend", "amount": 150_000},
}
DEEP = {
    "kind": "product_discount",
    "item_id": "1001",
    "variations": [{"variation_id": "", "final_price": 30_000}],
}


@pytest.fixture
async def reco(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    return seeded


@pytest.fixture
async def seller(session, reco):
    app = build_app(session)
    authenticate(app, user=reco.user, shop=reco.shop)
    async with client_for(app) as client:
        yield client
    app.dependency_overrides.clear()


async def renew(session, reco):
    """A committing route expires the test's shop / user objects; the next request needs them."""
    await session.refresh(reco.shop)
    await session.refresh(reco.user)


def body(*versions, **kw):
    return {"versions": list(versions), "as_of": AS_OF.isoformat(), **kw}


# ==================== Cài đặt › Loại trừ


async def test_demo_exclusions_add_list_undo(session, reco, seller):
    assert (await seller.get(EX)).json() == {
        "excluded": [],
        "count": 0,
        "reasons": [
            {"key": "ngung_ban", "label": "Ngừng bán"},
            {"key": "qua_tang", "label": "Quà tặng"},
            {"key": "phan_phoi", "label": "Hàng phân phối"},
            {"key": "khac", "label": "Khác"},
        ],
    }
    put = await seller.put(f"{EX}/1001", json={"reason": "qua_tang", "note": "quà kèm"})
    assert put.status_code == 200, put.text
    assert put.json()["item_id"] == "1001" and put.json()["reason_label"] == "Quà tặng"
    assert put.json()["note"] == "quà kèm" and put.json()["set_by"] == "seller"
    listing = (await seller.get(EX)).json()
    assert [e["item_id"] for e in listing["excluded"]] == ["1001"] and listing["count"] == 1
    products = (await seller.get(f"{B}/products?as_of={AS_OF}")).json()
    assert "1001" not in {p["item_id"] for p in products["products"]}
    assert products["excluded_hidden"] == 1
    shown = (await seller.get(f"{B}/products?as_of={AS_OF}&include_excluded=true")).json()
    assert next(p for p in shown["products"] if p["item_id"] == "1001")["excluded"] is True
    assert (await seller.delete(f"{EX}/1001")).status_code == 204
    assert (await seller.get(EX)).json()["count"] == 0
    missing = await seller.delete(f"{EX}/1001")
    assert missing.status_code == 404 and missing.json()["detail"]["code"] == "exclusion_not_found"


async def test_demo_exclusion_input_is_validated(seller):
    assert (await seller.put(f"{EX}/1001", json={"reason": "nope"})).status_code == 422
    assert (await seller.put(f"{EX}/1001", json={})).status_code == 422
    assert (await seller.put(f"{EX}/1001", json={"reason": "khac", "x": 1})).status_code == 422


async def test_ops_exclusions_read_as_viewer_write_as_operator_and_audit(
    session, reco, monkeypatch
):
    base = f"/v1/ops/shops/{reco.shop_id}/shopee/exclusions"
    viewer = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(viewer) as client:
        assert (await client.get(base)).status_code == 200
        assert (await client.put(f"{base}/1001", json={"reason": "khac"})).status_code == 403
    viewer.dependency_overrides.clear()
    operator = await _ops_client(session, monkeypatch, "operator")
    async with client_for(operator) as client:
        ok = await client.put(f"{base}/1002", json={"reason": "phan_phoi"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["set_by"] == "team" and ok.json()["reason"] == "phan_phoi"
        assert (await client.delete(f"{base}/1002")).status_code == 204
        assert (await client.delete(f"{base}/1002")).status_code == 404
    operator.dependency_overrides.clear()
    actions = [r.action for r in (await session.scalars(select(OpsAuditLog))).all()]
    assert actions == ["exclusion_add", "exclusion_undo"]


# ==================== reads


async def test_demo_picker_variations_co_purchase_and_campaigns(session, reco, seller):
    for n in range(3):
        a = _line(reco.shop_id, 500 + n, CUR_END, "G1", deal=90_000)
        b = _line(reco.shop_id, 500 + n, CUR_END, "N1", original=60_000, deal=54_000)
        b.line_no = 1
        session.add_all([a, b])
    await session.commit()
    picker = (await seller.get(f"{B}/products?as_of={AS_OF}&sort=orders_90d&limit=2")).json()
    assert len(picker["products"]) == 2 and picker["count"] == 3
    assert (await seller.get(f"{B}/products?sort=bogus")).status_code == 422
    var = await seller.get(f"{B}/products/1001/variations?as_of={AS_OF}")
    assert var.status_code == 200, var.text
    v = var.json()
    row = v["variations"][0]
    assert v["item_id"] == "1001" and v["columns"] == [
        "list_price", "selling_price", "price_per_unit", "margin_pct", "final_margin_pct",
    ]  # fmt: skip
    # ADR-122 d.12: So sánh phân loại shows Biên cuối beside Biên ở giá bán
    assert "final_margin_pct" in v["variations"][0]
    assert (row["list_price"], row["selling_price"], row["pack_count"]) == (100_000, 90_000, 1)
    assert row["margin_pct"] is not None and row["margin_label"] is None
    assert v["excluded"] is False and v["vat"]["basis"] == "before_vat"
    assert (await seller.get(f"{B}/products/nope/variations")).status_code == 404
    co = (await seller.get(f"{B}/products/1001/co-purchase?as_of={AS_OF}")).json()
    assert co["anchor"]["item_id"] == "1001" and co["window"]["days"] == 90
    assert [(s["item_id"], s["together"]) for s in co["suggestions"]] == [("1002", 3)]
    camps = (await seller.get(f"{B}/ads/campaigns?as_of={AS_OF}")).json()
    assert camps["campaigns"] and camps["cap_rule"] == "daily_marketing_cap"
    kw = (await seller.get(f"{B}/products/1001/keywords?as_of={AS_OF}")).json()
    assert kw["item_id"] == "1001" and kw["keywords"] == [] and len(kw["sources"]) == 4
    assert (await seller.get(f"{B}/products/nope/keywords")).status_code == 404


async def test_a_shop_without_shopee_numbers_answers_409(session):
    from tests.support.builders import make_tenant

    user, shop = await make_tenant(session, platform="shopee")
    await session.commit()
    app = build_app(session)
    authenticate(app, user=user, shop=shop)
    async with client_for(app) as client:
        for path in (f"{B}/products", f"{B}/ads/campaigns"):
            r = await client.get(path)
            assert r.status_code == 409 and r.json()["detail"]["code"] == "reco_no_data", path
        r = await client.post(f"{B}/evaluate", json={"versions": [VOUCHER]})
        assert r.status_code == 409
    app.dependency_overrides.clear()


# ==================== evaluate / compare / choose


async def test_evaluate_and_compare_save_nothing_and_validate_the_versions(session, reco, seller):
    one = await seller.post(f"{B}/evaluate", json=body(VOUCHER))
    assert one.status_code == 200, one.text
    assert one.json()["saved"] is False and len(one.json()["versions"]) == 1
    cmp = await seller.post(f"{B}/compare", json=body(VOUCHER, GIFT))
    assert cmp.status_code == 200 and [v["kind"] for v in cmp.json()["versions"]] == [
        "voucher",
        "gift",
    ]
    assert (await session.scalars(select(ShopProposal))).first() is None
    assert "card" not in cmp.json()["versions"][0]  # an outcome carries no model internals
    assert (await seller.post(f"{B}/compare", json=body(VOUCHER))).status_code == 422
    assert (await seller.post(f"{B}/evaluate", json=body(*[VOUCHER] * 5))).status_code == 422
    assert (await seller.post(f"{B}/evaluate", json=body({"kind": "voucher"}))).status_code == 422
    bad = {**VOUCHER, "value": 99_999_999_999}
    assert (await seller.post(f"{B}/evaluate", json=body(bad))).status_code == 422
    unknown = {"kind": "magic"}
    assert (await seller.post(f"{B}/evaluate", json=body(unknown))).status_code == 422


async def test_choose_creates_the_manual_card_and_a_breach_needs_the_acknowledgement(
    session, reco, seller
):
    ok = await seller.post(
        f"{B}/choose", json=body({**VOUCHER, "label": "5k/100k"}, GIFT, chosen=0, primary=True)
    )
    assert ok.status_code == 201, ok.text
    out = ok.json()
    assert out["origin"] == "manual" and out["status"] == "sent" and out["code"].startswith("JC-")
    assert "rank_inputs" not in out["card"] and all("card" not in v for v in out["versions"])
    assert out["outcome"]["label"] == "5k/100k" and out["versions"][0]["chosen"] is True
    await renew(session, reco)
    refused = await seller.post(f"{B}/choose", json=body(DEEP, VOUCHER, chosen=0))
    detail = refused.json()["detail"]
    assert refused.status_code == 422 and detail["code"] == "reco_breach_not_acknowledged"
    assert detail["breaches"][0]["type"] == "floor"
    await renew(session, reco)
    again = await seller.post(
        f"{B}/choose", json=body(DEEP, VOUCHER, chosen=0, acknowledge_breaches=True)
    )
    assert again.status_code == 201, again.text
    cards = (await session.scalars(select(ShopProposal))).all()
    assert len(cards) == 2
    await renew(session, reco)
    over = await seller.post(f"{B}/choose", json=body(VOUCHER, chosen=1))
    assert over.status_code == 422 and over.json()["detail"]["code"] == "reco_manual_invalid"
    await renew(session, reco)
    cant = await seller.post(
        f"{B}/choose", json=body({"kind": "product_discount", "item_id": "1001", "variations": []})
    )
    assert cant.status_code == 422 and cant.json()["detail"]["code"] == "reco_manual_invalid"


async def test_ops_builder_reads_and_compares_as_viewer_and_saves_as_operator_audited(
    session, reco, monkeypatch
):
    base = f"/v1/ops/shops/{reco.shop_id}/shopee/builder"
    viewer = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(viewer) as client:
        assert (await client.get(f"{base}/products?as_of={AS_OF}")).status_code == 200
        assert (
            await client.get(f"{base}/products/1001/variations?as_of={AS_OF}")
        ).status_code == 200
        assert (await client.post(f"{base}/compare", json=body(VOUCHER, GIFT))).status_code == 200
        assert (await client.post(f"{base}/choose", json=body(VOUCHER))).status_code == 403
        denied = await client.post(f"{base}/drafts/title", json={"item_id": "1001"})
        assert denied.status_code == 403
    viewer.dependency_overrides.clear()
    assert (await session.scalars(select(OpsAuditLog))).first() is None
    operator = await _ops_client(session, monkeypatch, "operator")
    async with client_for(operator) as client:
        r = await client.post(f"{base}/choose", json=body(VOUCHER, GIFT, chosen=1))
        assert r.status_code == 201, r.text
    operator.dependency_overrides.clear()
    out = r.json()
    assert out["status"] == "draft" and "rank_inputs" in out["card"]  # Ops sees the full card
    (row,) = (await session.scalars(select(OpsAuditLog))).all()
    assert row.action == "builder_choose" and row.after["kinds"] == ["voucher", "gift"]
    assert row.after["card_id"] == out["id"]


# ==================== P97 D85.14: "Chạy cùng nhau" -> one group of the plan

PRICE_15 = {
    "kind": "product_discount",
    "item_id": "1001",
    "variations": [{"variation_id": "", "discount_pct": 15}],
}
PRICE_20 = {
    "kind": "product_discount",
    "item_id": "1001",
    "variations": [{"variation_id": "", "discount_pct": 20}],
}
PLAN = "/v1/demo/shopee/recommendations/plan"


async def test_run_together_saves_the_cards_and_one_group_and_the_second_price_goes_next(
    session, reco, seller
):
    voucher_b = {**VOUCHER, "value": 8000}
    r = await seller.post(
        f"{B}/group",
        json=body(VOUCHER, voucher_b, PRICE_15, PRICE_20, members=[0, 1, 2, 3], days=4)
        | {"acknowledge_breaches": True},
    )
    assert r.status_code == 201, r.text
    out = r.json()
    # two vouchers are two versions of ONE card; the two prices are two versions of another
    assert len(out["saved"]) == 2 and [c["indexes"] for c in out["saved"]] == [[0, 1], [2, 3]]
    by = {g["letter"]: g for g in out["groups"]}
    assert sorted(by) == ["A", "B"]
    members_a = {(m["code"], m["version"]) for m in by["A"]["members"]}
    voucher_code, price_code = out["saved"][0]["code"], out["saved"][1]["code"]
    assert members_a == {(voucher_code, 1), (voucher_code, 2), (price_code, 1)}
    assert [(m["code"], m["version"]) for m in by["B"]["members"]] == [(price_code, 2)]
    assert by["A"]["days"] == 4 and by["B"]["start"] > by["A"]["end"]
    assert out["notice"]["type"] == "moved_to_group" and "giá bán" in out["notice"]["message"]
    assert "alpha" not in str(out["groups"][0]["aggregate"]["products"])  # seller view
    await renew(session, reco)
    got = (await seller.get(PLAN)).json()
    assert [g["letter"] for g in got["groups"]] == ["A", "B"]
    assert {tuple(x.values()) for c in got["cards"] for x in c["groups"]} >= {("A", 1), ("B", 2)}
    export = await seller.get(f"{PLAN}/export")
    assert export.status_code == 200 and export.content[:2] == b"PK"
    assert "spreadsheetml" in export.headers["content-type"]
    gid = by["A"]["id"]
    await renew(session, reco)
    shorter = await seller.post(f"{PLAN}/groups/{gid}/period", json={"days": 2})
    assert shorter.status_code == 422 and "ít nhất 3 ngày" in shorter.json()["detail"]["message"]
    await renew(session, reco)
    longer = await seller.post(f"{PLAN}/groups/{gid}/period", json={"days": 9})
    assert longer.status_code == 200 and longer.json()["groups"][0]["days"] == 9
    await renew(session, reco)
    cancel = await seller.post(f"{PLAN}/groups/{by['B']['id']}/cancel")
    assert cancel.status_code == 200 and [g["letter"] for g in cancel.json()["groups"]] == ["A"]


async def test_run_together_rejects_a_bad_pick_and_a_breach_needs_the_acknowledgement(
    session, reco, seller
):
    bad = await seller.post(f"{B}/group", json=body(VOUCHER, members=[3]))
    assert bad.status_code == 422
    await renew(session, reco)
    breach = await seller.post(f"{B}/group", json=body(DEEP, VOUCHER, members=[0, 1]))
    detail = breach.json()["detail"]
    assert breach.status_code == 422 and detail["code"] == "reco_breach_not_acknowledged"
    assert detail["breaches"][0]["type"] == "floor"


async def test_ops_run_together_sends_the_cards_audited_and_reads_as_viewer(
    session, reco, monkeypatch
):
    base = f"/v1/ops/shops/{reco.shop_id}/shopee"
    viewer = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(viewer) as client:
        denied = await client.post(f"{base}/builder/group", json=body(VOUCHER, members=[0]))
        assert denied.status_code == 403
    viewer.dependency_overrides.clear()
    operator = await _ops_client(session, monkeypatch, "operator")
    async with client_for(operator) as client:
        r = await client.post(f"{base}/builder/group", json=body(VOUCHER, GIFT, members=[0, 1]))
        assert r.status_code == 201, r.text
        plan = await client.get(f"{base}/recommendations/plan")
        assert [g["letter"] for g in plan.json()["groups"]] == ["A"]
        export = await client.get(f"{base}/recommendations/plan/export")
        assert export.status_code == 200 and export.content[:2] == b"PK"
    operator.dependency_overrides.clear()
    out = r.json()
    assert len(out["saved"]) == 2 and len(out["groups"][0]["members"]) == 2
    rows = [
        x for x in (await session.scalars(select(OpsAuditLog))).all() if x.action == "builder_group"
    ]
    assert len(rows) == 1 and rows[0].after["kinds"] == ["voucher", "gift"]
    cards = (await session.scalars(select(ShopProposal))).all()
    assert {c.status for c in cards} == {"planned"}  # sent by Ops, then planned in the group


# ==================== the drafts


@pytest.fixture
def fake_llm(monkeypatch):
    client = FakeLLM()

    async def get_client(session, shop_id):
        return client

    monkeypatch.setattr(common, "get_client", get_client)
    return client


async def test_title_drafts_use_the_ticked_keywords_and_the_100_character_rule(seller, fake_llm):
    fake_llm.answers.append(
        {
            "drafts": [
                {"title": "Găng tay tự hủy sinh học STAHAUS hộp 100 chiếc", "note": "gọn"},
                {"title": "STAHAUS găng tay tự hủy sinh học dùng một lần", "note": "rõ"},
                {"title": "Găng tay " + "x" * 120, "note": "dài"},
            ]
        }
    )
    r = await seller.post(
        f"{B}/drafts/title",
        json={"item_id": "1001", "keywords": ["găng tay"], "count": 3, "as_of": AS_OF.isoformat()},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert [d["title"] for d in out["drafts"]] == [
        "Găng tay tự hủy sinh học STAHAUS hộp 100 chiếc",
        "STAHAUS găng tay tự hủy sinh học dùng một lần",
    ]
    assert (
        out["current_title"] == "Găng tay tự hủy sinh học STAHAUS" and out["model"] == "fake-model"
    )
    assert out["dropped"][0]["reason"].startswith("dài") and out["max_chars"] == 100
    too_many = await seller.post(f"{B}/drafts/title", json={"item_id": "1001", "count": 9})
    assert too_many.status_code == 422
    unknown = await seller.post(f"{B}/drafts/title", json={"item_id": "nope"})
    assert unknown.status_code == 404


async def test_cover_and_description_drafts(seller, fake_llm):
    fake_llm.answers.append(
        {
            "concepts": [
                {
                    "layout": "banner_bottom",
                    "variation_id": "",
                    "use_voucher": False,
                    "use_unit_price": False,
                    "hook_text": "Dùng một lần",
                    "pack_text": "",
                    "rationale": "gọn",
                },
                {
                    "layout": "corner_tag",
                    "variation_id": "",
                    "use_voucher": False,
                    "use_unit_price": False,
                    "hook_text": "",
                    "pack_text": "",
                    "rationale": "giá",
                },
            ]
        }
    )
    cover = await seller.post(
        f"{B}/drafts/cover", json={"item_id": "1001", "as_of": AS_OF.isoformat()}
    )
    assert cover.status_code == 200, cover.text
    first = cover.json()["concepts"][0]["overlay"]
    assert first["price_vnd"] == 90_000 and first["original_price_vnd"] == 100_000
    assert first["discount_pct"] == 10 and first["layout"] == "banner_bottom"
    fake_llm.answers.append(
        {"drafts": [{"first_line": "Găng tay tự hủy sinh học, giá 90.000đ.", "note": ""}] * 2}
    )
    desc = await seller.post(
        f"{B}/drafts/description", json={"item_id": "1001", "as_of": AS_OF.isoformat()}
    )
    assert desc.status_code == 200 and len(desc.json()["drafts"]) == 1  # the duplicate is dropped
    fake_llm.answers.append({"drafts": [{"first_line": "Cam kết chữa khỏi", "note": ""}]})
    none = await seller.post(
        f"{B}/drafts/description", json={"item_id": "1001", "as_of": AS_OF.isoformat()}
    )
    detail = none.json()["detail"]
    assert none.status_code == 422 and detail["code"] == "llm_no_valid_draft" and detail["dropped"]


async def test_without_a_model_the_drafts_answer_llm_tat_and_fail_closed(
    seller, session, monkeypatch
):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SHOPEE_BUILDER_LLM", raising=False)
    for path, payload in (
        ("title", {"item_id": "1001", "keywords": ["găng tay"]}),
        ("cover", {"item_id": "1001"}),
        ("description", {"item_id": "1001"}),
    ):
        r = await seller.post(f"{B}/drafts/{path}", json=payload)
        detail = r.json()["detail"]
        assert r.status_code == 503, (path, r.text)
        assert detail["code"] == "llm_off" and detail["message"] == "LLM tắt"
        assert detail["reason"] == "not_configured"
    monkeypatch.setenv("SHOPEE_BUILDER_LLM", "off")
    off = await seller.post(f"{B}/drafts/title", json={"item_id": "1001"})
    assert off.json()["detail"]["reason"] == "switch_off"


async def test_a_provider_failure_is_llm_tat_too(seller, fake_llm):
    from juli_backend.services.shopee_builder import llm

    fake_llm.answers.append(llm.LLMUnavailable(llm.REASON_PROVIDER, "timeout"))
    r = await seller.post(f"{B}/drafts/title", json={"item_id": "1001", "keywords": []})
    assert r.status_code == 503 and r.json()["detail"]["reason"] == "provider"
    assert uuid.UUID(int=0)  # (the fake never reached a network)


# ==================== B-8 seller parity pages

PAGES = "/v1/demo/shopee"


async def test_seller_orders_are_hashed_levers_and_no_buyer_data(
    session, reco, seller, monkeypatch
):
    r = await seller.get(f"{PAGES}/orders?period=7d&as_of={CUR_END}")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["count"] == 13 and out["order_basis"]["key"] == "confirmed"
    row = out["orders"][0]
    assert len(row["order_key"]) == 12 and set(row["order_key"]) <= set("0123456789abcdef")
    text = r.text
    assert not any(ln.order_ref in text for ln in reco.lines)  # no full hashed ref, no buyer
    assert "buyer" not in text
    # the amount the customer paid must survive the Ops masking layer (a `buyer_*` key is "•••")
    assert all(isinstance(o["paid_amount"], (int, float)) for o in out["orders"])
    from juli_backend.services.ops.masking import mask_pii

    assert mask_pii(row)["paid_amount"] == row["paid_amount"]
    assert set(out["by_status"]) <= {"delivered", "cancelled", "refunded_accepted", "in_transit"}
    assert any("voucher" in o["levers"] for o in out["orders"])
    assert any("combo" in o["levers"] for o in out["orders"])
    only = (await seller.get(f"{PAGES}/orders?period=7d&as_of={CUR_END}&lever=voucher")).json()
    assert 0 < only["count"] < out["count"] and all(
        "voucher" in o["levers"] for o in only["orders"]
    )
    cancelled = (
        await seller.get(f"{PAGES}/orders?period=7d&as_of={CUR_END}&status=cancelled")
    ).json()
    assert cancelled["count"] == 1 and cancelled["orders"][0]["contribution"] is None
    by_gmv = (await seller.get(f"{PAGES}/orders?period=7d&as_of={CUR_END}&sort=gmv&limit=2")).json()
    assert len(by_gmv["orders"]) == 2 and by_gmv["orders"][0]["gmv"] >= by_gmv["orders"][1]["gmv"]
    assert (await seller.get(f"{PAGES}/orders?sort=buyer")).status_code == 422
    assert (await seller.get(f"{PAGES}/orders?status=nope")).status_code == 422


async def test_ops_reads_the_same_orders_as_a_viewer(session, reco, monkeypatch):
    app = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(app) as client:
        r = await client.get(
            f"/v1/ops/shops/{reco.shop_id}/shopee/orders?period=7d&as_of={CUR_END}"
        )
    app.dependency_overrides.clear()
    assert r.status_code == 200 and r.json()["count"] == 13


async def test_seller_keywords_and_dashboards_are_the_ops_services_scoped_to_the_shop(
    session, reco, seller, monkeypatch
):
    from datetime import date

    from juli_backend.services.ops import shopee_dashboards as dash

    calls = []

    async def fake(name):
        async def inner(session, shop_id, *a, **kw):
            calls.append((name, shop_id))
            return {"has_data": False, "name": name}

        return inner

    for name in ("products", "flows", "ads", "promotions"):
        monkeypatch.setattr(dash, name, await fake(name))

    async def latest_day(session, shop_id, dataset):
        return date(2026, 10, 28)

    monkeypatch.setattr(dash, "latest_day", latest_day)
    for name in ("products", "flows", "ads", "promotions"):
        r = await seller.get(f"{PAGES}/dashboard/{name}")
        assert r.status_code == 200 and r.json()["name"] == name, (name, r.text)
    assert {shop for _, shop in calls} == {reco.shop_id}  # always the seller's own shop
    bad = await seller.get(f"{PAGES}/dashboard/products?period_from=2026-10-05")
    assert bad.status_code == 422
    assert (
        await seller.get(f"{PAGES}/dashboard/flows?from=2026-10-09&to=2026-10-01")
    ).status_code == 422
    kw = await seller.get(f"{PAGES}/keywords")
    assert kw.status_code == 200, kw.text
    assert (await seller.get(f"{PAGES}/keywords?min_volume=-1")).status_code == 422
