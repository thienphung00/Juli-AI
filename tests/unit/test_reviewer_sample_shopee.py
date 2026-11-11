"""P100 S2-F -- the reviewer's Shopee routes on the synthetic sample shop ("Dữ liệu mẫu").

Every ``/v1/demo/shopee/*`` route was 403 ``read_only`` for a reviewer. A reviewed list
(``api/reviewer.py`` ``SAMPLE_SHOP_ENDPOINTS``) admits the routes the four screens and Tự tạo's
three strategies need -- ONLY when the selected pin is the ``sample`` shop. Proven here, on a
synthetic Shopee shop with real cards, through the real gate (signed tokens, SQLite):

- each listed route answers on the sample pin and the whole database is unchanged afterwards
  (every table but the audit log and the reviewer's own rows), with TikTok / network / Celery
  tripwires armed;
- the same routes on a masked pin, the sandbox pin and with no pin answer 403 ``read_only`` as
  before;
- Duyệt (``POST …/recommendations/{id}/approve``) is simulated: an approve-shaped answer, one
  audit row, nothing else; a card outside Tiêu đề / Ảnh bìa / Voucher is refused;
- the live LLM / vision drafts answer 403 ``sample_llm_off`` on the sample pin.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from juli_backend.api import reviewer as reviewer_gate
from juli_backend.integrations.tiktok import TikTokCapability
from juli_backend.models.ops import OpsAuditLog
from juli_backend.repositories import TikTokCredentialRepo
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.reviewer import sandbox as reviewer_sandbox
from juli_backend.services.shopee_recommendations import store
from juli_backend.services.shopee_recommendations.cards import build_card
from juli_backend.services.shopee_recommendations.loader import load_env
from juli_backend.services.shopee_recommendations.model import Candidate
from tests.support import reviewer as rv
from tests.support.api import build_app, client_for
from tests.support.builders import utc_now_naive
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_reviewer_no_write import Tripwire, _routes, _snapshot

NOW = datetime(2026, 10, 8, 3, 0)
DEMO = "/v1/demo/shopee"
ITEM = "1001"

#: Each sample-shop endpoint and the URL template it must be served at.
SAMPLE_TEMPLATES: dict[tuple[str, str], str] = {
    ("GET", f"{DEMO}/overview"): "demo_shopee_analytics:shopee_overview",
    ("GET", f"{DEMO}/matrix"): "demo_shopee_analytics:shopee_matrix",
    ("GET", f"{DEMO}/critical"): "demo_shopee_analytics:shopee_critical",
    ("GET", f"{DEMO}/ranking"): "demo_shopee_analytics:shopee_ranking",
    ("GET", f"{DEMO}/products/{{item_id}}"): "demo_shopee_analytics:shopee_product",
    ("GET", f"{DEMO}/kols"): "demo_shopee_analytics:shopee_kols",
    ("GET", f"{DEMO}/products/{{item_id}}/kols"): "demo_shopee_analytics:shopee_product_kols",
    (
        "GET",
        f"{DEMO}/products/{{item_id}}/market-price",
    ): "demo_shopee_market:product_market_price",
    ("GET", f"{DEMO}/recommendations"): "demo_shopee_recommendations:list_recommendations",
    (
        "GET",
        f"{DEMO}/recommendations/{{card_id}}",
    ): "demo_shopee_recommendations:recommendation_detail",
    (
        "POST",
        f"{DEMO}/recommendations/{{card_id}}/approve",
    ): "demo_shopee_recommendations:approve_recommendation",
    ("GET", f"{DEMO}/builder/products"): "demo_shopee_builder:builder_products",
    (
        "GET",
        f"{DEMO}/builder/products/{{item_id}}/variations",
    ): "demo_shopee_builder:builder_variations",
    (
        "GET",
        f"{DEMO}/builder/products/{{item_id}}/keywords",
    ): "demo_shopee_builder:builder_keywords",
    ("POST", f"{DEMO}/builder/evaluate"): "demo_shopee_builder:builder_evaluate",
    ("POST", f"{DEMO}/builder/compare"): "demo_shopee_builder:builder_compare",
}
LLM_TEMPLATES: dict[tuple[str, str], str] = {
    ("POST", f"{DEMO}/builder/drafts/title"): "demo_shopee_builder:builder_title_drafts",
    ("POST", f"{DEMO}/builder/drafts/cover"): "demo_shopee_builder:builder_cover_drafts",
    (
        "POST",
        f"{DEMO}/builder/drafts/description",
    ): "demo_shopee_builder:builder_description_drafts",
}

VOUCHER = {"kind": "voucher", "discount_type": "amount", "value": 5000, "min_spend": 100_000}
TITLE = {"kind": "title", "item_id": ITEM, "title": "Găng tay tự hủy sinh học 100 chiếc"}


@pytest.fixture(autouse=True)
def reviewer_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", rv.JWT_SECRET)
    monkeypatch.setenv("REVIEWER_ACCOUNT_CACHE_SECONDS", "0")
    monkeypatch.setenv("TIKTOK_APP_KEY", "app-key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "app-secret")
    for name in ("REVIEWER_SHOP_ID", "REVIEWER_SHOP_IDS", "REVIEWER_SAMPLE_SHOP_IDS"):
        monkeypatch.delenv(name, raising=False)
    rv.reset_caches()
    reviewer_sandbox.forget_sync_slots()
    yield
    rv.reset_caches()
    reviewer_sandbox.forget_sync_slots()


@pytest.fixture(name="tripwire")
def _tripwire(monkeypatch) -> Tripwire:
    """The no-write proof's tripwires: TikTok clients, real network, Celery."""
    import httpx
    import requests
    from celery import Celery
    from celery.app.task import Task

    from juli_backend.integrations.tiktok import client as tiktok_client
    from juli_backend.integrations.tiktok import factories as tiktok_factories

    wire = Tripwire()
    monkeypatch.setattr(tiktok_client.TikTokClient, "__init__", wire.trip("TikTokClient()"))
    for name in ("ProductionReadClientFactory", "SandboxWriteClientFactory"):
        monkeypatch.setattr(getattr(tiktok_factories, name), "__init__", wire.trip(f"{name}()"))
    monkeypatch.setattr(Task, "apply_async", wire.trip("Celery Task.apply_async"))
    monkeypatch.setattr(Celery, "send_task", wire.trip("Celery.send_task"))
    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", wire.trip("httpx network request")
    )
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", wire.trip("httpx network request"))
    monkeypatch.setattr(requests.Session, "send", wire.trip("requests network request"))
    return wire


def _pin(monkeypatch, *shop_ids: uuid.UUID, sample: tuple[uuid.UUID, ...] = ()) -> None:
    monkeypatch.setenv("REVIEWER_SHOP_IDS", ",".join(str(s) for s in shop_ids))
    monkeypatch.setenv("REVIEWER_SAMPLE_SHOP_IDS", ",".join(str(s) for s in sample))
    rv.reset_caches()


@pytest.fixture
async def world(session, monkeypatch):
    """A masked seller shop, the synthetic Shopee sample shop with cards, the TikTok sandbox."""
    seller = await rv.seed_reference_shop(session)
    sample = await seed_reco_shop(session)
    shop = sample.shop
    shop.shop_name = "Dữ liệu mẫu"
    shop.tiktok_shop_id = None
    shop.tiktok_numeric_shop_id = None
    await session.commit()
    env = await load_env(session, sample.shop_id, as_of=AS_OF)
    ids: dict[str, uuid.UUID] = {}
    for n, cand in enumerate(
        (
            Candidate(
                "min_spend_voucher",
                ("1002",),
                {"value": 3000, "min_spend": 90_000, "quantity": 50, "days": 14},
                wiring_key="aov",
            ),
            Candidate(
                "ads_budget",
                (),
                {"daily_budget": 36_000},
                campaign_key="cgroup1",
                wiring_key="views",
            ),
        ),
        1,
    ):
        card = build_card(env, cand, now=NOW)
        assert card is not None, cand.kind
        card["rank"] = {
            "position": n,
            "score": 1.0 / n,
            "detail": {},
            "mode": "x",
            "explore": False,
        }
        ids[cand.kind] = await store.save_card(
            session, sample.shop_id, card, cycle="2026-10", position=n, now=NOW
        )
    await reco.publish(session, sample.shop_id, None, now=NOW)  # "sent": what a seller sees
    sandbox = await rv.seed_reference_shop(
        session,
        name="Juli Sandbox VN",
        tiktok_shop_id="7600000000000000001",
        title="Sandbox áo thun",
        product_id="1730000000000000001",
        seller_sku="SBX-01",
    )
    for owned, capability, merchant in (
        (sandbox.shop, TikTokCapability.SANDBOX_WRITE, "sandbox-merchant"),
        (seller.shop, TikTokCapability.PRODUCTION_READ, "prod-merchant"),
    ):
        await TikTokCredentialRepo(session).create(
            owned.id,
            f"{merchant}-token",
            f"{merchant}-refresh",
            utc_now_naive() + timedelta(days=30),
            merchant_authorization_id=merchant,
            capability=capability.value,
            shop_cipher=f"cipher-{merchant}",
            scopes="seller.product.basic",
        )
    await session.commit()
    _pin(monkeypatch, seller.shop.id, sample.shop_id, sandbox.shop.id, sample=(sample.shop_id,))
    reviewer_id = await rv.make_reviewer(session)
    return seller, sample, sandbox, reviewer_id, ids


def _headers(user_id, shop_id) -> dict[str, str]:
    return {"Authorization": f"Bearer {rv.token(user_id)}", "X-Shop-Id": str(shop_id)}


def _fill(template: str, card_id: uuid.UUID) -> str:
    return template.replace("{item_id}", ITEM).replace("{card_id}", str(card_id))


def _body(method: str, template: str) -> dict[str, Any] | None:
    if method == "GET":
        return None
    if template.endswith("/approve"):
        return {"chosen_version": 1, "acknowledge_breaches": True}
    if template.endswith("/compare"):
        return {"versions": [VOUCHER, TITLE], "as_of": AS_OF.isoformat()}
    if template.endswith("/evaluate"):
        return {"versions": [VOUCHER], "as_of": AS_OF.isoformat()}
    return {"item_id": ITEM, "count": 3}


async def _refusals(session, action: str) -> list[OpsAuditLog]:
    rows = await session.execute(select(OpsAuditLog).where(OpsAuditLog.action == action))
    return list(rows.scalars().all())


# -- the list itself ------------------------------------------------------------------------------


def test_the_sample_list_is_pinned_to_real_routes_and_kept_apart():
    from juli_backend.api.app import create_app

    served: dict[tuple[str, str], str] = {}
    for route in _routes(create_app()):
        for method in route.methods:
            endpoint = getattr(route, "endpoint", None) or route.original_route.endpoint
            served[(method, route.path)] = (
                f"{endpoint.__module__}:{endpoint.__qualname__}"
            ).removeprefix("juli_backend.api.routes.")
    for key, endpoint in {**SAMPLE_TEMPLATES, **LLM_TEMPLATES}.items():
        assert served.get(key) == endpoint, (key, served.get(key))
    strip = "juli_backend.api.routes."
    assert {(m, e.removeprefix(strip)) for m, e in reviewer_gate.SAMPLE_SHOP_ENDPOINTS} == {
        (m, e) for (m, _), e in SAMPLE_TEMPLATES.items()
    }
    assert {(m, e.removeprefix(strip)) for m, e in reviewer_gate.SAMPLE_SHOP_LLM_ENDPOINTS} == {
        (m, e) for (m, _), e in LLM_TEMPLATES.items()
    }
    # Never on the every-pin allowlist: a masked / sandbox pin keeps refusing them.
    assert not reviewer_gate.SAMPLE_SHOP_ENDPOINTS & reviewer_gate.ALLOWED_ENDPOINTS
    assert not reviewer_gate.SAMPLE_SHOP_LLM_ENDPOINTS & reviewer_gate.ALLOWED_ENDPOINTS
    assert not reviewer_gate.SAMPLE_SHOP_LLM_ENDPOINTS & reviewer_gate.SAMPLE_SHOP_ENDPOINTS
    # The only POSTs: two pure computations and the simulated Duyệt.
    assert sorted(t for m, t in SAMPLE_TEMPLATES if m == "POST") == [
        f"{DEMO}/builder/compare",
        f"{DEMO}/builder/evaluate",
        f"{DEMO}/recommendations/{{card_id}}/approve",
    ]
    # The known writers stay off.
    for writer in (
        "seller_keywords",
        "seller_fill_jobs",
        "builder_choose",
        "recommendation_whatif",
    ):
        assert not any(e.endswith(f":{writer}") for _, e in reviewer_gate.SAMPLE_SHOP_ENDPOINTS)


# -- the sample pin: every listed route answers and writes nothing -------------------------------


async def test_every_sample_route_answers_and_writes_nothing(session, world, tripwire):
    _seller, sample, _sandbox, reviewer_id, ids = world
    card_id = ids["min_spend_voucher"]
    before = await _snapshot(session, reviewer_id=reviewer_id)
    seen: dict[str, int] = {}
    async with client_for(build_app(session)) as client:
        for method, template in SAMPLE_TEMPLATES:
            response = await client.request(
                method,
                _fill(template, card_id),
                headers=_headers(reviewer_id, sample.shop_id),
                json=_body(method, template),
            )
            seen[f"{method} {template}"] = response.status_code
            assert response.status_code == 200, (template, response.text)
            assert "x-juli-reviewer-denied" not in response.headers
    after = await _snapshot(session, reviewer_id=reviewer_id)
    changed = [name for name in before if before[name] != after[name]]
    assert not changed, f"tables changed by a sample-shop reviewer: {changed}"
    assert not tripwire.hits, tripwire.hits
    assert len(seen) == len(SAMPLE_TEMPLATES)
    # Unmasked: the synthetic names are served as they are.
    async with client_for(build_app(session)) as client:
        listed = await client.get(
            f"{DEMO}/builder/products", headers=_headers(reviewer_id, sample.shop_id)
        )
    assert "Găng tay tự hủy sinh học STAHAUS" in listed.text


@pytest.mark.parametrize("which", ["masked", "sandbox", "no_pin"])
async def test_other_pins_keep_refusing_the_shopee_routes(
    session, world, tripwire, which, monkeypatch
):
    seller, sample, sandbox, reviewer_id, ids = world
    if which == "no_pin":
        _pin(monkeypatch)
        shop_header: Any = sample.shop_id
    elif which == "masked":
        from juli_backend.services.reviewer.config import shop_alias_id

        shop_header = shop_alias_id(seller.shop.id)
    else:
        shop_header = sandbox.shop.id
    before = await _snapshot(session, reviewer_id=reviewer_id)
    async with client_for(build_app(session)) as client:
        for method, template in {**SAMPLE_TEMPLATES, **LLM_TEMPLATES}:
            response = await client.request(
                method,
                _fill(template, ids["min_spend_voucher"]),
                headers=_headers(reviewer_id, shop_header),
                json=_body(method, template),
            )
            assert response.status_code == 403, (which, template, response.text)
            assert response.headers["x-juli-reviewer-denied"] == "read_only", (which, template)
    after = await _snapshot(session, reviewer_id=reviewer_id)
    assert [n for n in before if before[n] != after[n]] == []
    assert not tripwire.hits


async def test_the_shop_entry_refuses_a_sample_route_when_the_pin_is_not_sample(session, world):
    """Second layer: the gate admitted the route, but the entered pin is not the sample shop."""
    seller, _sample, _sandbox, _reviewer_id, _ids = world
    from juli_backend.services.reviewer.sandbox import MODE_MASKED, PinMode

    context = reviewer_gate.ReviewerContext(
        account=await _account(session),
        platform="shopee",
        shop_id=seller.shop.id,
        alias_id=None,
        sample_only=True,
        method="GET",
        endpoint="juli_backend.api.routes.demo_shopee_analytics:shopee_overview",
    )
    context.pin = PinMode(MODE_MASKED, writes_enabled=False)
    context.shop = seller.shop
    with pytest.raises(Exception) as refused:
        await reviewer_gate.enter_reviewer_shop(session, context, None)
    assert getattr(refused.value, "status_code", None) == 403
    assert refused.value.headers["X-Juli-Reviewer-Denied"] == "read_only"  # type: ignore[attr-defined]


async def _account(session):
    from juli_backend.services.reviewer import accounts

    (row,) = (await session.execute(select(accounts.OpsReviewerAccount))).scalars().all()
    return accounts._snapshot(row)


# -- Duyệt is simulated ---------------------------------------------------------------------------


async def test_approve_on_the_sample_shop_is_simulated(session, world, tripwire):
    _seller, sample, _sandbox, reviewer_id, ids = world
    card_id = ids["min_spend_voucher"]
    before = await _snapshot(session, reviewer_id=reviewer_id)
    async with client_for(build_app(session)) as client:
        first = await client.post(
            f"{DEMO}/recommendations/{card_id}/approve",
            json={"chosen_version": 1, "acknowledge_breaches": True},
            headers=_headers(reviewer_id, sample.shop_id),
        )
        again = await client.post(
            f"{DEMO}/recommendations/{card_id}/approve",
            json={"chosen_version": 1, "acknowledge_breaches": True},
            headers=_headers(reviewer_id, sample.shop_id),
        )
        detail = await client.get(
            f"{DEMO}/recommendations/{card_id}", headers=_headers(reviewer_id, sample.shop_id)
        )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["id"] == str(card_id) and body["status"] == "approved"
    assert body["chosen_version"] == 1 and uuid.UUID(body["approval_id"])
    assert body["simulated"] is True and body["shopee_write"] is False
    assert again.json()["approval_id"] == body["approval_id"]  # stable, never stored
    assert detail.json()["status"] != "approved"  # nothing was written
    after = await _snapshot(session, reviewer_id=reviewer_id)
    assert [n for n in before if before[n] != after[n]] == []
    assert not tripwire.hits
    rows = await _refusals(session, "reviewer_simulated_approve")
    assert len(rows) == 2
    assert rows[0].after["card_id"] == str(card_id) and rows[0].after["shopee"] is True


async def test_approve_refuses_a_card_outside_the_three_strategies(session, world):
    _seller, sample, _sandbox, reviewer_id, ids = world
    before = await _snapshot(session, reviewer_id=reviewer_id)
    async with client_for(build_app(session)) as client:
        ads = await client.post(
            f"{DEMO}/recommendations/{ids['ads_budget']}/approve",
            json={"chosen_version": 1},
            headers=_headers(reviewer_id, sample.shop_id),
        )
        unknown = await client.post(
            f"{DEMO}/recommendations/{uuid.uuid4()}/approve",
            json={"chosen_version": 1},
            headers=_headers(reviewer_id, sample.shop_id),
        )
    assert ads.status_code == 403 and ads.headers["x-juli-reviewer-denied"] == "read_only"
    assert unknown.status_code == 404
    after = await _snapshot(session, reviewer_id=reviewer_id)
    assert [n for n in before if before[n] != after[n]] == []
    assert await _refusals(session, "reviewer_simulated_approve") == []


async def test_the_other_card_writes_stay_refused_on_the_sample_shop(session, world):
    _seller, sample, _sandbox, reviewer_id, ids = world
    card_id = ids["min_spend_voucher"]
    async with client_for(build_app(session)) as client:
        for path, body in (
            (f"{DEMO}/recommendations/{card_id}/whatif", {"inputs": {}}),
            (f"{DEMO}/recommendations/{card_id}/dismiss", {}),
            (f"{DEMO}/recommendations/{card_id}/executed", {}),
            (f"{DEMO}/builder/choose", {"versions": [VOUCHER], "chosen": [0]}),
        ):
            response = await client.post(
                path, json=body, headers=_headers(reviewer_id, sample.shop_id)
            )
            assert response.status_code == 403, (path, response.text)
            assert response.headers["x-juli-reviewer-denied"] == "read_only"
        for path in (f"{DEMO}/keywords", f"{DEMO}/orders", f"{DEMO}/fill-jobs?card_id={card_id}"):
            response = await client.get(path, headers=_headers(reviewer_id, sample.shop_id))
            assert response.status_code == 403, (path, response.text)


# -- live LLM / vision ---------------------------------------------------------------------------


async def test_llm_drafts_are_unavailable_on_the_sample_shop(session, world, tripwire):
    _seller, sample, _sandbox, reviewer_id, _ids = world
    before = await _snapshot(session, reviewer_id=reviewer_id)
    async with client_for(build_app(session)) as client:
        for method, template in LLM_TEMPLATES:
            response = await client.request(
                method,
                template,
                json={"item_id": ITEM, "count": 3},
                headers=_headers(reviewer_id, sample.shop_id),
            )
            assert response.status_code == 403, (template, response.text)
            assert response.headers["x-juli-reviewer-denied"] == "sample_llm_off"
            assert response.json()["detail"] == "Chưa dùng được với dữ liệu mẫu"
    after = await _snapshot(session, reviewer_id=reviewer_id)
    assert [n for n in before if before[n] != after[n]] == []
    assert not tripwire.hits
    refused = await _refusals(session, "reviewer_write_refused")
    assert len(refused) == 3 and {r.after["reason"] for r in refused} == {"sample_llm_off"}
