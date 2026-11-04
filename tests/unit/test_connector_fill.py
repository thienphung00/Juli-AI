"""P91 D-13: the Connector's fill request (``GET /v1/ingest/fill/{code}``) and the flag routes.
The Connector fills the title / first description line of an APPROVED card of its own shop and
never saves; this is the server half. SQLite; synthetic."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.services import ingest as ingest_service
from juli_backend.services import planned_changes as pc
from juli_backend.services.ingest import pairing
from tests.support.api import authenticate, build_app, client_for
from tests.support.shopee_reco import seed_reco_shop
from tests.unit.test_ingest_gateway import _shopee_tenant
from tests.unit.test_ops_shopee_dashboards import _ops_client
from tests.unit.test_planned_changes import NOW, VARIATION_TEXT, _row, _xlsx

FILL = "/v1/ingest/fill"


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setenv("CONNECTOR_FILL_LISTING", "1")


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await session.commit()
    return seeded


def _approved(ref, **over):
    return _row(ref=ref, decision="đồng ý", **over)


async def _import(session, shop, *rows) -> dict[str, str]:
    """``{ref: card code}`` of the cards the file made."""
    await pc.apply_import(
        session,
        shop.shop_id,
        _xlsx(*rows),
        actor=pc.Actor("seller", user_id=shop.user.id),
        reason="x",
        now=NOW,
    )
    await session.commit()
    from juli_backend.models.planned_changes import PlannedChangeRef

    out = {}
    for ref in list(await session.scalars(select(PlannedChangeRef))):
        out[ref.external_ref] = await session.scalar(
            select(ShopProposal.code).where(ShopProposal.id == ref.card_id)
        )
    return out


async def _token(session, shop) -> dict[str, str]:
    created = await ingest_service.create_pairing_code(
        session, shop=shop.shop, user_id=shop.user.id, now=NOW
    )
    issued = await ingest_service.redeem_pairing_code(
        session, code=created.code, platform="shopee", platform_shop_id="998877",
        client_label="Juli Connector test", now=NOW,
    )  # fmt: skip
    await session.commit()
    assert pairing.token_hash(issued.token)
    return {"Authorization": f"Bearer {issued.token}"}


@pytest.fixture
async def ext(session, shop):
    headers = await _token(session, shop)
    app = build_app(session)
    async with client_for(app) as client:
        client.headers.update(headers)
        yield client
    app.dependency_overrides.clear()


async def test_an_approved_title_card_returns_the_text_and_the_page(session, shop, ext):
    cards = await _import(session, shop, _approved("TD1", after="Găng tay tự hủy loại mới"))
    code = cards["TD1"]
    r = await ext.get(f"{FILL}/{code}")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["code"] == code and out["item_id"] == "1001" and out["change_kind"] == "title"
    assert out["fields"] == [
        {
            "key": "title",
            "label": "Tên sản phẩm",
            "mode": "replace",
            "max_chars": 100,
            "value": "Găng tay tự hủy loại mới",
        }
    ]
    assert out["page_only"] is False and out["downloads"] == [] and out["checklist"] == []
    assert out["steps"][0]["copy"] == "Găng tay tự hủy loại mới"


async def test_a_description_card_fills_the_first_line_only(session, shop, ext):
    cards = await _import(
        session, shop, _approved("MT1", kind="mô tả", after="Gói 5 cái, dùng một lần")
    )
    out = (await ext.get(f"{FILL}/{cards['MT1']}")).json()
    (field,) = out["fields"]
    assert (field["key"], field["mode"], field["label"]) == (
        "description_first_line",
        "first_line",
        "Mô tả sản phẩm",
    )
    assert field["value"] == "Gói 5 cái, dùng một lần"


async def test_cover_variation_hide_and_relist_are_offered_without_a_field(session, shop, ext):
    cards = await _import(
        session,
        shop,
        _approved("AB1", kind="ảnh bìa", after="https://img.example/new-cover.jpg"),
        _approved("AB2", item_id="1002", kind="ảnh bìa", after="anh-bia-moi.png"),
        _approved("PL1", item_id="1002", kind="gom phân loại", after=VARIATION_TEXT),
        _approved("AN1", item_id="1003", kind="ẩn", after=""),
        _approved("NH1", item_id="1003", kind="nhập hàng", after="80"),
    )
    cover = (await ext.get(f"{FILL}/{cards['AB1']}")).json()
    assert cover["fields"] == [] and cover["downloads"] == [
        {"label": "Tải ảnh bìa mới", "url": "https://img.example/new-cover.jpg"}
    ]
    by_name = (await ext.get(f"{FILL}/{cards['AB2']}")).json()
    assert by_name["downloads"] == []  # a file name is not an address: nothing to download
    variation = (await ext.get(f"{FILL}/{cards['PL1']}")).json()
    assert variation["fields"] == [] and len(variation["checklist"]) == 3
    assert variation["checklist"][0]["after"].startswith("Hộp 5 cái")
    for ref in ("AN1", "NH1"):
        page = (await ext.get(f"{FILL}/{cards[ref]}")).json()
        assert page["page_only"] is True and page["fields"] == []


async def test_only_an_approved_card_of_the_own_shop_is_served(session, shop, ext):
    cards = await _import(
        session,
        shop,
        _approved("TD1"),
        _row(ref="TD2", item_id="1002", after="Tên mới hai"),  # no decision: sent
        _approved(
            "TD3", item_id="1003", after="Tên mới ba", date="10/10/2026", status="hoàn thành"
        ),
    )
    assert (await ext.get(f"{FILL}/{cards['TD2']}")).json()["detail"]["code"] == "fill_not_approved"
    done = await ext.get(f"{FILL}/{cards['TD3']}")
    assert done.status_code == 409 and done.json()["detail"]["code"] == "fill_not_approved"
    assert (await ext.get(f"{FILL}/JC-2611-9999")).json()["detail"]["code"] == "fill_unknown_card"
    assert (await ext.get(f"{FILL}/{cards['TD1']}-V2")).status_code == 422
    assert (await ext.get(f"{FILL}/nonsense")).json()["detail"]["code"] == "fill_bad_code"


async def test_another_shops_card_is_not_found(session, shop, ext):
    cards = await _import(session, shop, _approved("TD1"))
    _, other = await _shopee_tenant(session)
    other_headers = await _token_for(session, other)
    app = build_app(session)
    async with client_for(app) as client:
        r = await client.get(f"{FILL}/{cards['TD1']}", headers=other_headers)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "fill_unknown_card"


async def _token_for(session, shop_row) -> dict[str, str]:
    created = await ingest_service.create_pairing_code(
        session, shop=shop_row, user_id=shop_row.user_id, now=NOW
    )
    issued = await ingest_service.redeem_pairing_code(
        session, code=created.code, platform="shopee", platform_shop_id="55",
        client_label="other", now=NOW,
    )  # fmt: skip
    await session.commit()
    return {"Authorization": f"Bearer {issued.token}"}


async def test_the_server_flag_and_the_token_gate_the_route(session, shop, ext, monkeypatch):
    cards = await _import(session, shop, _approved("TD1"))
    code = cards["TD1"]
    monkeypatch.setenv("CONNECTOR_FILL_LISTING", "0")
    off = await ext.get(f"{FILL}/{code}")
    assert off.status_code == 404 and off.json()["detail"]["code"] == "fill_disabled"
    assert (await ext.get(FILL)).json() == {"enabled": False, "platform": "shopee"}
    monkeypatch.setenv("CONNECTOR_FILL_LISTING", "1")
    assert (await ext.get(FILL)).json()["enabled"] is True
    app = build_app(session)
    async with client_for(app) as anonymous:
        assert (await anonymous.get(f"{FILL}/{code}")).status_code == 401


async def test_a_card_that_is_not_a_listing_change_is_not_filled(session, shop, ext):
    from juli_backend.services.shopee_recommendations import fill

    cards = await _import(session, shop, _approved("TD1"))
    from juli_backend.models.card_events import CardEvent

    pid = await session.scalar(select(ShopProposal.id).where(ShopProposal.code == cards["TD1"]))
    ev = await session.scalar(
        select(CardEvent).where(CardEvent.card_id == pid, CardEvent.event_type == "proposed")
    )
    ev.payload = {**ev.payload, "change_kind": "product_discount"}
    await session.commit()
    with pytest.raises(Exception) as err:
        await fill.fill_request(session, shop.shop_id, cards["TD1"])
    assert getattr(err.value, "code", "") == "fill_not_supported"


async def test_the_screens_ask_whether_the_button_shows(session, shop, monkeypatch):
    app = build_app(session)
    authenticate(app, user=shop.user, shop=shop.shop)
    async with client_for(app) as client:
        assert (await client.get("/v1/demo/connector-fill")).json()["data"]["enabled"] is True
    app.dependency_overrides.clear()
    monkeypatch.setenv("CONNECTOR_FILL_LISTING", "")
    viewer = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(viewer) as client:
        assert (await client.get("/v1/ops/connector-fill")).json()["data"]["enabled"] is False
