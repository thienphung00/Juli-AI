"""P32-A (D42) partner reviewer access: account state, pin, mask, simulation, audit.

Real signed tokens through the real ``get_current_user`` (the reviewer gate lives
there), SQLite. The no-write proof over every route is ``test_reviewer_no_write``.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from juli_backend.core.security.claims import reviewer_platform
from juli_backend.models.ops import OpsAuditLog, OpsReviewerAccount
from juli_backend.services.reviewer import accounts as reviewer_accounts
from juli_backend.services.reviewer.config import shop_alias_id
from juli_backend.services.reviewer.masking import (
    REVIEWER_SHOP_LABEL,
    MaskDictionary,
    mask_payload,
)
from juli_backend.services.reviewer.simulation import PRODUCT_EDIT_PATH, simulate
from tests.support import reviewer as rv
from tests.support.api import build_app, client_for


@pytest.fixture(autouse=True)
def reviewer_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", rv.JWT_SECRET)
    monkeypatch.setenv("REVIEWER_ACCOUNT_CACHE_SECONDS", "0")
    rv.reset_caches()
    yield
    rv.reset_caches()


@pytest.fixture
async def world(session, monkeypatch):
    ref = await rv.seed_reference_shop(session)
    other = await rv.seed_reference_shop(
        session,
        name="Other Seller Shop",
        tiktok_shop_id="7494000000000000777",
        title="Áo thun nữ cotton Mộc Lan",
        product_id="1729000000000000777",
        seller_sku="ML-AO-01",
    )
    await session.commit()
    monkeypatch.setenv("REVIEWER_SHOP_ID", str(ref.shop.id))
    return ref, other


def _headers(user_id, *, shop=None, **kw) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {rv.token(user_id, **kw)}"}
    if shop is not None:
        headers["X-Shop-Id"] = str(shop)
    return headers


#: P74-A (D77): the reviewer mask's labels never say "demo" (Shopee reads it as not live).
_DEMO_LABEL = re.compile(r"Demo (Shop|Product|Video|LIVE|Creator|File)|demo-[a-z]+-[0-9a-f]{8}")


def _assert_no_demo_label(text: str) -> None:
    found = _DEMO_LABEL.search(text)
    assert found is None, f"demo label {found.group(0)!r} in {text[:400]}"


def _assert_masked(text: str) -> None:
    for secret in rv.SECRETS:
        assert secret not in text, f"{secret!r} leaked: {text[:400]}"


async def _audit(session, action: str | None = None) -> list[OpsAuditLog]:
    stmt = select(OpsAuditLog).order_by(OpsAuditLog.at)
    if action:
        stmt = stmt.where(OpsAuditLog.action == action)
    return list((await session.execute(stmt)).scalars().all())


# -- claims ------------------------------------------------------------------------


def test_only_app_metadata_marks_a_reviewer():
    assert (
        reviewer_platform({"app_metadata": {"juli_role": "reviewer", "juli_platform": "Shopee"}})
        == "shopee"
    )
    assert reviewer_platform({"app_metadata": {"juli_role": "reviewer"}}) == "unknown"
    # user_metadata is user-writable: never a mark.
    assert reviewer_platform({"user_metadata": {"juli_role": "reviewer"}}) is None
    assert reviewer_platform({"app_metadata": {"juli_role": "admin"}}) is None
    assert reviewer_platform({}) is None


def test_simulated_request_path_is_the_real_edit_path():
    from juli_backend.integrations.tiktok.constants import product_edit_path

    assert product_edit_path("{product_id}") == PRODUCT_EDIT_PATH


# -- account state ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"expires_in": timedelta(seconds=-1)}, "expired"),
        ({"revoked": True}, "revoked"),
        ({"platform": "lazada"}, "unknown"),
    ],
)
async def test_denied_reviewer_gets_403_everywhere(session, world, kwargs, code):
    ref, _ = world
    user_id = await rv.make_reviewer(session, **kwargs)
    alias = shop_alias_id(ref.shop.id)
    async with client_for(build_app(session)) as client:
        for path in ("/v1/reviewer/me", "/v1/shops", "/v1/demo/decisions", "/v1/demo/analysis"):
            response = await client.get(path, headers=_headers(user_id, shop=alias))
            assert response.status_code == 403, path
            assert response.headers["x-juli-reviewer-denied"] == code


async def test_reviewer_mark_without_account_row_is_refused(session, world):
    async with client_for(build_app(session)) as client:
        response = await client.get("/v1/reviewer/me", headers=_headers(uuid.uuid4()))
    assert response.status_code == 403
    assert response.headers["x-juli-reviewer-denied"] == "unknown"


async def test_no_pin_reviewer_gets_sample_mode(session, world, monkeypatch):
    """D42 amendment (2026-10-15): ``REVIEWER_SHOP_ID`` unset → ``shop: null``, no shop at all."""
    ref, _ = world
    monkeypatch.delenv("REVIEWER_SHOP_ID")
    user_id = await rv.make_reviewer(session)
    async with client_for(build_app(session)) as client:
        me = await client.get("/v1/reviewer/me", headers=_headers(user_id))
        shops = await client.get("/v1/shops", headers=_headers(user_id))
        reads = [
            await client.get(path, headers=_headers(user_id, shop=shop))
            for path in ("/v1/demo/decisions", "/v1/shops/me", "/v1/demo/analysis")
            for shop in (shop_alias_id(ref.shop.id), ref.shop.id)
        ]
        simulate = await client.post(
            f"/v1/reviewer/decisions/{ref.card.id}/simulate",
            json={"step": "execute"},
            headers=_headers(user_id, shop=shop_alias_id(ref.shop.id)),
        )
        approve = await client.post(
            f"/v1/demo/decisions/{ref.card.id}/approve", json={}, headers=_headers(user_id)
        )
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["reviewer"] is True and body["platform"] == "shopee" and body["shop"] is None
    assert body["expires_at"].endswith("Z")
    assert shops.status_code == 200 and shops.json() == []
    for response in [*reads, simulate]:
        assert response.status_code == 403, response.text
        _assert_masked(response.text)
    assert approve.status_code == 403
    assert approve.headers["x-juli-reviewer-denied"] == "sandbox_only"  # P64 (D73.4)
    for response in (me, shops):
        _assert_masked(response.text)
        assert str(ref.shop.id) not in response.text
    refused = await _audit(session, "reviewer_write_refused")
    assert len(refused) == 1 and refused[0].shop_id is None


@pytest.mark.parametrize("kwargs", [{"expires_in": timedelta(seconds=-1)}, {"revoked": True}])
async def test_no_pin_still_refuses_expired_and_revoked(session, world, monkeypatch, kwargs):
    monkeypatch.delenv("REVIEWER_SHOP_ID")
    user_id = await rv.make_reviewer(session, **kwargs)
    async with client_for(build_app(session)) as client:
        response = await client.get("/v1/reviewer/me", headers=_headers(user_id))
        unknown = await client.get("/v1/reviewer/me", headers=_headers(uuid.uuid4()))
    assert response.status_code == 403
    assert unknown.status_code == 403
    assert unknown.headers["x-juli-reviewer-denied"] == "unknown"


async def test_renew_and_revoke_take_effect(session, world):
    ref, _ = world
    user_id = await rv.make_reviewer(session, expires_in=timedelta(seconds=-1))
    async with client_for(build_app(session)) as client:
        assert (await client.get("/v1/reviewer/me", headers=_headers(user_id))).status_code == 403
        await reviewer_accounts.renew_account(
            session, "shopee-review@app-juli.com", by="o@app-juli.com"
        )
        await session.commit()
        assert (await client.get("/v1/reviewer/me", headers=_headers(user_id))).status_code == 200
        await reviewer_accounts.revoke_account(
            session, "shopee-review@app-juli.com", by="o@app-juli.com"
        )
        await session.commit()
        response = await client.get("/v1/reviewer/me", headers=_headers(user_id))
    assert response.status_code == 403
    assert response.headers["x-juli-reviewer-denied"] == "revoked"
    actions = [row.action for row in await _audit(session)]
    assert "reviewer_account_renew" in actions and "reviewer_account_revoke" in actions


# -- who am I, pin ----------------------------------------------------------------------


async def test_reviewer_me_and_shop_list_are_the_aliased_reference_shop(session, world):
    ref, _ = world
    user_id = await rv.make_reviewer(session)
    alias = str(shop_alias_id(ref.shop.id))
    async with client_for(build_app(session)) as client:
        me = await client.get("/v1/reviewer/me", headers=_headers(user_id))
        shops = await client.get("/v1/shops", headers=_headers(user_id))
        shop_me = await client.get("/v1/shops/me", headers=_headers(user_id, shop=alias))
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["reviewer"] is True and body["platform"] == "shopee"
    assert body["shop"]["id"] == alias
    # P74-A (D77): a neutral label, never "Demo …" (Shopee reads "demo" as not live).
    assert body["shop"]["name"] == REVIEWER_SHOP_LABEL
    assert "demo" not in body["shop"]["name"].lower()
    assert [s["id"] for s in shops.json()] == [alias]
    assert shop_me.json()["id"] == alias
    for response in (me, shops, shop_me):
        _assert_masked(response.text)
        assert str(ref.shop.id) not in response.text


async def test_seller_gets_reviewer_false(session, world):
    ref, _ = world
    async with client_for(build_app(session)) as client:
        response = await client.get(
            "/v1/reviewer/me", headers=_headers(ref.owner.id, platform=None)
        )
    assert response.status_code == 200
    assert response.json() == {"reviewer": False}


@pytest.mark.parametrize("which", ["real", "other", "garbage"])
async def test_reviewer_cannot_pick_a_shop(session, world, which):
    ref, other = world
    user_id = await rv.make_reviewer(session)
    shop = {"real": ref.shop.id, "other": other.shop.id, "garbage": "not-a-uuid"}[which]
    async with client_for(build_app(session)) as client:
        for path in ("/v1/demo/decisions", "/v1/shops/me", "/v1/demo/analysis"):
            response = await client.get(path, headers=_headers(user_id, shop=shop))
            assert response.status_code == 403, (path, response.text)


# -- reads: masked, magnitudes real -----------------------------------------------------


async def test_decisions_are_masked_with_real_magnitudes(session, world):
    ref, _ = world
    user_id = await rv.make_reviewer(session)
    alias = shop_alias_id(ref.shop.id)
    app = build_app(session)
    async with client_for(app) as client:
        reviewer = await client.get("/v1/demo/decisions", headers=_headers(user_id, shop=alias))
        seller = await client.get(
            "/v1/demo/decisions", headers=_headers(ref.owner.id, platform=None, shop=ref.shop.id)
        )
    assert reviewer.status_code == 200, reviewer.text
    assert seller.status_code == 200, seller.text
    _assert_masked(reviewer.text)
    assert rv.PRODUCT_TITLE in seller.text  # the seller sees their own shop
    mine, theirs = reviewer.json()["data"], seller.json()["data"]
    assert [c["id"] for c in mine] == [c["id"] for c in theirs]
    diag_r = mine[0]["recommendation"]["diagnosis"]
    diag_s = theirs[0]["recommendation"]["diagnosis"]
    assert diag_r["recoverable_gmv_per_day"] == diag_s["recoverable_gmv_per_day"] == 1250000.0
    assert diag_r["main_kpi"]["raw"] == diag_s["main_kpi"]["raw"]
    assert re.fullmatch(r"Sản phẩm \d{3}", diag_r["product_title"])
    assert re.fullmatch(r"an-product-[0-9a-f]{8}", diag_r["tiktok_product_id"])
    _assert_no_demo_label(reviewer.text)


def test_mask_replaces_titles_in_free_text_brand_words_urls_and_long_ids():
    shop_id = uuid.uuid4()
    dictionary = MaskDictionary(
        shop_id=shop_id,
        alias_id=shop_alias_id(shop_id),
        shop_name=rv.SHOP_NAME,
        titles={rv.PRODUCT_TITLE: "product"},
    )
    payload = {
        "shop_id": str(shop_id),
        "headline": f"Đổi tiêu đề của {rv.PRODUCT_TITLE} ngay",
        "after": "Nồi chiên FUJIWA chính hãng 6L",
        "videos": [
            {"video_id": "7400000000000000001", "title": "Review nồi chiên mới", "views": 12000}
        ],
        "image_url": "https://p16-oec-va.ibyteimg.com/x.jpg",
        "link": "https://shop.tiktok.com/view/product/1729384756102938475",
        "own": "https://demo.app-juli.com/decisions",
        "note": "mã 1729384756102938475",
        "gmv": 98765432.5,
        "ratio": 0.0123,
    }
    masked = mask_payload(payload, dictionary)
    text = json.dumps(masked, ensure_ascii=False)
    _assert_masked(text)
    assert "FUJIWA" not in text
    assert masked["shop_id"] == str(shop_alias_id(shop_id))
    assert masked["after"] == "Nồi chiên Thương hiệu chính hãng 6L"
    assert re.fullmatch(r"Video \d{3}", masked["videos"][0]["title"])
    assert re.fullmatch(r"an-video-[0-9a-f]{8}", masked["videos"][0]["video_id"])
    assert re.fullmatch(r"mã id-[0-9a-f]{8}", masked["note"])
    _assert_no_demo_label(text)
    assert masked["videos"][0]["views"] == 12000
    assert masked["image_url"] is None and masked["link"] is None
    assert masked["own"] == "https://demo.app-juli.com/decisions"
    assert masked["gmv"] == 98765432.5 and masked["ratio"] == 0.0123
    assert "Review nồi chiên mới" not in text


# -- simulated Duyệt → Thực thi ---------------------------------------------------------


@pytest.mark.parametrize("executor", ["juli", "juli_with_photo", "juli_drafts", "seller_center"])
def test_simulation_note_is_one_short_line_without_internals(executor):
    """P41 (D47.7): one short line, no endpoint / method / operation name."""
    item = {
        "id": "c1",
        "recommendation": {
            "card": {
                "lever": {"code": "x", "label": "X", "executor": executor},
                "change_fields": [{"field": "x", "label": "X"}],
            }
        },
    }
    change = simulate(item, "execute")["change"]
    note = change["note"]
    assert len(note) <= 120
    for internal in ("/product/", "PUT", "update_", "upload_", "Tài khoản dùng thử", "Không có"):
        assert internal not in note
    after = change["fields"][0]["after"]
    if executor == "seller_center":
        assert after == "Bạn áp dụng trên Seller Center"


async def test_simulated_approve_then_execute(session, world):
    ref, _ = world
    user_id = await rv.make_reviewer(session)
    alias = shop_alias_id(ref.shop.id)
    path = f"/v1/reviewer/decisions/{ref.card.id}/simulate"
    async with client_for(build_app(session)) as client:
        approve = await client.post(
            path, json={"step": "approve"}, headers=_headers(user_id, shop=alias)
        )
        execute = await client.post(
            path, json={"step": "execute"}, headers=_headers(user_id, shop=alias)
        )
    assert approve.status_code == 200, approve.text
    assert execute.status_code == 200, execute.text
    body = execute.json()
    assert body["simulated"] is True and body["enqueued"] is False and body["tiktok_write"] is False
    assert [s["done"] for s in body["steps"]] == [True, True]
    assert [s["done"] for s in approve.json()["steps"]] == [True, False]
    change = body["change"]
    assert change["request"]["operation"] == "update_product_listing"
    assert change["request"]["path"] == PRODUCT_EDIT_PATH
    assert re.fullmatch(r"Sản phẩm \d{3}", change["product"]["title"])
    _assert_masked(execute.text)
    _assert_no_demo_label(execute.text)
    await session.refresh(ref.card)
    assert ref.card.status == "active"
    actions = [row.action for row in await _audit(session)]
    assert actions.count("reviewer_simulated_approve") == 1
    assert actions.count("reviewer_simulated_execute") == 1


async def test_simulate_is_reviewer_only(session, world):
    ref, _ = world
    async with client_for(build_app(session)) as client:
        response = await client.post(
            f"/v1/reviewer/decisions/{ref.card.id}/simulate",
            json={"step": "execute"},
            headers=_headers(ref.owner.id, platform=None, shop=ref.shop.id),
        )
    assert response.status_code == 403


# -- audit --------------------------------------------------------------------------------


async def test_sign_in_audited_once_per_session_with_platform(session, world):
    ref, _ = world
    user_id = await rv.make_reviewer(session)
    alias = shop_alias_id(ref.shop.id)
    async with client_for(build_app(session)) as client:
        for _ in range(3):
            await client.get("/v1/demo/decisions", headers=_headers(user_id, shop=alias))
        await client.get(
            "/v1/demo/decisions", headers=_headers(user_id, shop=alias, session_id="sess-2")
        )
    rows = await _audit(session, "reviewer_sign_in")
    assert [r.after["session_id"] for r in rows] == ["sess-1", "sess-2"]
    assert all(r.after["platform"] == "shopee" for r in rows)
    assert all(r.actor_email == "reviewer:shopee:shopee-review@app-juli.com" for r in rows)
    assert all(r.shop_id == ref.shop.id for r in rows)
    account = (await session.execute(select(OpsReviewerAccount))).scalar_one()
    assert account.last_session_id == "sess-2"


async def test_refused_write_is_audited(session, world):
    ref, _ = world
    user_id = await rv.make_reviewer(session)
    alias = shop_alias_id(ref.shop.id)
    async with client_for(build_app(session)) as client:
        response = await client.post(
            f"/v1/demo/decisions/{ref.card.id}/approve", headers=_headers(user_id, shop=alias)
        )
    assert response.status_code == 403
    # P64 (D73.4): approve is a sandbox-only run route; on this (non-sandbox) pin it is refused.
    assert response.headers["x-juli-reviewer-denied"] == "sandbox_only"
    rows = await _audit(session, "reviewer_write_refused")
    assert len(rows) == 1
    assert rows[0].after["platform"] == "shopee"
    assert rows[0].after["endpoint"].endswith("demo_execution:approve_demo_decision")


async def test_reviewer_cannot_use_the_ops_console(session, world, monkeypatch):
    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    user_id = await rv.make_reviewer(session)
    async with client_for(build_app(session)) as client:
        for path in ("/v1/ops/me", "/v1/ops/overview"):
            response = await client.get(path, headers=_headers(user_id))
            assert response.status_code == 403


def test_reviewer_labels_are_stable_and_neutral():
    """P74-A (D77): own labels, stable per raw value, no "demo"; ADR-038 analytics unchanged."""
    from juli_backend.services.analytics_kpi_masking.mask import stable_product_title
    from juli_backend.services.reviewer.masking import REVIEWER_SHOP_LABEL, id_alias, title_alias

    assert title_alias("shop", rv.SHOP_NAME) == REVIEWER_SHOP_LABEL
    for kind, label in (("product", "Sản phẩm"), ("video", "Video"), ("live", "LIVE")):
        alias = title_alias(kind, "x")
        assert alias == title_alias(kind, "x") and re.fullmatch(rf"{label} \d{{3}}", alias)
    assert re.fullmatch(r"an-sku-[0-9a-f]{8}", id_alias("sku", rv.SELLER_SKU))
    assert id_alias("sku", rv.SELLER_SKU) == id_alias("sku", rv.SELLER_SKU)
    assert re.fullmatch(r"id-[0-9a-f]{8}", id_alias("id", rv.TIKTOK_PRODUCT_ID))
    for value in (title_alias("product", "x"), id_alias("product", "x"), id_alias("id", "1")):
        assert "demo" not in value.lower()
    # The seller / ops analytics mask is untouched (ADR-038).
    assert stable_product_title("x").startswith("Demo Product ")
