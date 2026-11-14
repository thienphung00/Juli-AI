"""Part S: the Sản phẩm stock list, the "Theo dõi" switch, unsubscribe, and the card effects."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

import pytest
from sqlalchemy import select

from juli_backend.models.stock_alert import ShopeeSkuTracking, ShopeeStockAlertUnsubscribe
from juli_backend.services.shopee_analytics.catalog import Catalog, ItemInfo, Variation
from juli_backend.services.stock_alert import cards, links
from tests.support.api import authenticate, build_app, client_for
from tests.unit.test_stock_alert_job import NOW, _seed_selling, _shop

pytestmark = pytest.mark.usefixtures("_secret")


@pytest.fixture
def _secret(monkeypatch):
    monkeypatch.setenv("STOCK_ALERT_LINK_SECRET", "test-secret")


@pytest.fixture
def fixed_now(monkeypatch):
    from juli_backend.api.routes import demo_stock_alert

    monkeypatch.setattr(demo_stock_alert, "_now", lambda: NOW)


async def test_stock_list_and_switch(session, fixed_now):
    owner, shop = await _shop(session, status=None)
    await _seed_selling(session, shop.id, stock=10)
    app = build_app(session)
    authenticate(app, user=owner, shop=shop)
    async with client_for(app) as client:
        got = await client.get("/v1/demo/shopee/stock")
        assert got.status_code == 200, got.text
        data = got.json()["data"]
        assert data["enabled"] is True
        [row] = data["rows"]
        assert (row["key"], row["product_name"], row["variation_name"]) == ("1:11", "Áo thun", "Đỏ")
        assert (row["stock"], row["tracked"], row["eligible"]) == (10, True, True)
        assert row["sku_code"] == "AT-DO"
        assert row["days_left"] == 5 and row["runs_out_on"] == "2026-11-20"
        put = await client.put("/v1/demo/shopee/stock/1:11/tracking", json={"tracked": False})
        assert put.status_code == 200, put.text
        assert put.json()["data"]["tracked"] is False
        again = (await client.get("/v1/demo/shopee/stock")).json()["data"]["rows"][0]
        assert again["tracked"] is False
        bad = await client.put("/v1/demo/shopee/stock/abc/tracking", json={"tracked": False})
        assert bad.status_code == 422
    stored = await session.get(ShopeeSkuTracking, (shop.id, "1", "11"))
    assert stored.set_by == str(owner.id)


async def test_sample_shop_has_no_stock_ui(session, fixed_now):
    owner, shop = await _shop(session, status=None, shopee_shop_id="990000000001")
    app = build_app(session)
    authenticate(app, user=owner, shop=shop)
    async with client_for(app) as client:
        assert (await client.get("/v1/demo/shopee/stock")).json()["data"]["enabled"] is False
        put = await client.put("/v1/demo/shopee/stock/1:11/tracking", json={"tracked": False})
        assert put.status_code == 403


async def test_unsubscribe_needs_a_valid_token_and_is_idempotent(session):
    owner, shop = await _shop(session, status=None)
    app = build_app(session)
    async with client_for(app) as client:
        bad = await client.post("/v1/stock-alert/unsubscribe", json={"token": "x" * 20})
        assert bad.status_code == 400
        token = links.sign(shop.id, owner.id)
        for _ in range(2):
            ok = await client.post("/v1/stock-alert/unsubscribe", json={"token": token})
            assert ok.status_code == 200, ok.text
        assert (await client.get("/v1/stock-alert/unsubscribe")).status_code == 405
    rows = (await session.execute(select(ShopeeStockAlertUnsubscribe))).scalars().all()
    assert [(r.shop_id, r.user_id) for r in rows] == [(shop.id, owner.id)]


# --------------------------------------------------------------------------- card effects

CATALOG = Catalog(
    items={
        "1": ItemInfo(
            "1",
            "Áo",
            variations=(Variation("11", "Đỏ", "SKU-R"), Variation("12", "Xanh", "SKU-B")),
        )
    }
)
KEYS = {"1": {"1:11", "1:12"}}


def test_targets_of_named_variations_and_whole_product():
    named = {"scope": {"product_ids": ["1"]}, "inputs": {"variations": [{"sku": "SKU-R"}]}}
    assert cards.targets_of(named, KEYS, CATALOG) == {"1:11"}
    whole = {"scope": {"product_ids": ["1"]}, "inputs": {}}
    assert cards.targets_of(whole, KEYS, CATALOG) == {"1:11", "1:12"}
    unknown = {"scope": {"product_ids": ["1"]}, "inputs": {"variations": [{"sku": "?"}]}}
    assert cards.targets_of(unknown, KEYS, CATALOG) is None
    assert cards.stopped_items({"1:11"}, KEYS) == frozenset()
    assert cards.stopped_items({"1:11", "1:12"}, KEYS) == frozenset({"1"})
    assert cards.stock_warnings(frozenset({"1"}), ["1", "2"])[0]["items"] == ["1"]
    assert cards.stock_warnings(frozenset(), ["1"]) == []


@dataclass
class _P:
    id: uuid.UUID
    status: str


async def test_apply_withdraws_open_cards_and_tags_running_ones(monkeypatch):
    from juli_backend.services.shopee_recommendations import service, store

    named_r = {"scope": {"product_ids": ["1"]}, "inputs": {"variations": [{"sku": "SKU-R"}]}}
    whole = {"scope": {"product_ids": ["1"]}, "inputs": {}}
    sent, running, whole_sent = (
        _P(uuid.uuid4(), "sent"),
        _P(uuid.uuid4(), "executed"),
        _P(uuid.uuid4(), "sent"),
    )
    rows = [(sent, named_r), (running, named_r), (whole_sent, whole)]
    meta: dict[uuid.UUID, dict] = {}
    withdrawn: list[uuid.UUID] = []

    async def list_cards(session, shop_id, *, statuses=None, cycle=None):
        return rows

    async def card_meta(session, shop_id, cid):
        return dict(meta.get(cid, {}))

    async def set_meta(session, shop_id, cid, patch):
        meta.setdefault(cid, {}).update(patch)

    async def withdraw(session, shop_id, cid, **kw):
        assert kw["by"] == "stock_alert"
        withdrawn.append(cid)

    async def stopped(session, shop_id):
        return {"1:11"}

    async def keys(session, shop_id, catalog=None):
        return KEYS

    monkeypatch.setattr(store, "list_cards", list_cards)
    monkeypatch.setattr(store, "card_meta", card_meta)
    monkeypatch.setattr(store, "set_meta", set_meta)
    monkeypatch.setattr(service, "withdraw", withdraw)
    monkeypatch.setattr(cards, "untracked_keys", stopped)
    monkeypatch.setattr(cards, "variation_keys", keys)
    counts = await cards.apply(None, uuid.uuid4(), now=NOW, catalog=CATALOG)
    # the card naming only the stopped red variation is withdrawn; the running one is tagged; the
    # whole-product card stays (blue is still tracked)
    assert withdrawn == [sent.id]
    assert counts == {"withdrawn": 1, "tagged": 1, "untagged": 0}
    assert meta[running.id][cards.TAG_KEY]["label"] == "Đã ngừng theo dõi"
    assert whole_sent.id not in meta

    async def none_stopped(session, shop_id):
        return set()

    monkeypatch.setattr(cards, "untracked_keys", none_stopped)
    rows[:] = [(running, named_r)]
    counts = await cards.apply(None, uuid.uuid4(), now=NOW + timedelta(days=1), catalog=CATALOG)
    assert counts["untagged"] == 1 and meta[running.id][cards.TAG_KEY] is None
