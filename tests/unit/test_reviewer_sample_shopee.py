"""P100 S2-F / S2-G -- the reviewer's Shopee routes on the synthetic sample shop ("Dữ liệu mẫu").

Every ``/v1/demo/shopee/*`` route was 403 ``read_only`` for a reviewer. A reviewed table
(``api/reviewer.py`` ``SAMPLE_SHOP_ROUTES``: route -> read / write, with why) admits the routes the
four screens and Tự tạo's three strategies need -- ONLY when the selected pin is the ``sample``
shop. Proven here, on a synthetic Shopee shop with real cards, through the real gate (signed
tokens, SQLite), with TikTok / network / Celery / LLM tripwires armed:

- each READ route answers on the sample pin and the whole database is unchanged afterwards;
- each WRITE route (S2-G, owner Option A) writes ONLY the sample shop's own rows -- no other
  shop's row changes, no fill job is queued even with the Connector switch on, nothing outbound
  is called -- and leaves one ``reviewer_sample_write`` audit row;
- Duyệt is the REAL approve: the card moves to Đang thực hiện; a card outside Tiêu đề / Ảnh bìa /
  Voucher is refused;
- the same routes on a masked pin, the sandbox pin and with no pin answer 403 ``read_only``;
- the live cover / description drafts answer 403 ``sample_llm_off`` (P100 S2-D: the title drafts
  are a sample write -- the seeded titles, then one live draft per product,
  the S2-D tests at the end); the Connector's fill-job routes and the hidden
  screens' routes stay refused.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, cast

import pytest
from sqlalchemy import func, select

from juli_backend.api import reviewer as reviewer_gate
from juli_backend.api.routes import shopee_builder_common
from juli_backend.integrations.tiktok import TikTokCapability
from juli_backend.models.card_content_specs import SOURCE_LLM, CardContentSpec
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
from tests.support.sample_content import passing_titles, seed_title_spec
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_reviewer_no_write import Tripwire, _routes, _snapshot

NOW = datetime(2026, 10, 8, 3, 0)
DEMO = "/v1/demo/shopee"
ITEM = "1001"

REC = f"{DEMO}/recommendations"
#: Each sample-shop READ endpoint and the URL template it must be served at.
READ_TEMPLATES: dict[tuple[str, str], str] = {
    ("GET", f"{DEMO}/overview"): "demo_shopee_analytics:shopee_overview",
    ("GET", f"{DEMO}/matrix"): "demo_shopee_analytics:shopee_matrix",
    ("GET", f"{DEMO}/critical"): "demo_shopee_analytics:shopee_critical",
    ("GET", f"{DEMO}/channel-split"): "demo_shopee_analytics:shopee_channel_split",
    (
        "GET",
        f"{DEMO}/channel-split/products",
    ): "demo_shopee_analytics:shopee_channel_split_products",
    ("GET", f"{DEMO}/metric-view"): "demo_shopee_analytics:shopee_metric_view",
    ("GET", f"{DEMO}/kol-section"): "demo_shopee_analytics:shopee_kol_section",
    ("GET", f"{DEMO}/ranking"): "demo_shopee_analytics:shopee_ranking",
    ("GET", f"{DEMO}/products/{{item_id}}"): "demo_shopee_analytics:shopee_product",
    ("GET", f"{DEMO}/kols"): "demo_shopee_analytics:shopee_kols",
    ("GET", f"{DEMO}/products/{{item_id}}/kols"): "demo_shopee_analytics:shopee_product_kols",
    (
        "GET",
        f"{DEMO}/products/{{item_id}}/market-price",
    ): "demo_shopee_market:product_market_price",
    ("GET", REC): "demo_shopee_recommendations:list_recommendations",
    ("GET", f"{REC}/{{card_id}}"): "demo_shopee_recommendations:recommendation_detail",
    ("POST", f"{REC}/compare"): "demo_shopee_reco_manual:compare_variants",
    ("GET", f"{REC}/plan"): "demo_shopee_reco_plan:get_plan",
    ("GET", f"{REC}/plan/aggregate"): "demo_shopee_reco_plan:get_aggregate",
    ("GET", f"{REC}/plans"): "demo_shopee_reco_plan:list_plans",
    ("GET", f"{REC}/plans/code/{{code}}"): "demo_shopee_reco_plan:plan_by_code",
    ("GET", f"{REC}/plans/{{plan_id}}"): "demo_shopee_reco_plan:get_plan_by_id",
    ("GET", f"{REC}/plan/export"): "demo_shopee_reco_plan:export_plan",
    ("GET", f"{REC}/change-sets"): "demo_shopee_reco_plan:list_change_sets",
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
    ("GET", f"{DEMO}/exclusions"): "demo_shopee_builder:list_exclusions",
}
#: P100 S2-G: each sample-shop WRITE endpoint (Juli's own rows of the sample shop only).
WRITE_TEMPLATES: dict[tuple[str, str], str] = {
    ("POST", f"{REC}/{{card_id}}/approve"): "demo_shopee_recommendations:approve_recommendation",
    ("POST", f"{REC}/{{card_id}}/whatif"): "demo_shopee_recommendations:recommendation_whatif",
    ("POST", f"{REC}/{{card_id}}/request-change"): "demo_shopee_recommendations:request_change",
    ("POST", f"{REC}/{{card_id}}/dismiss"): "demo_shopee_recommendations:dismiss_recommendation",
    (
        "POST",
        f"{REC}/{{card_id}}/executed",
    ): "demo_shopee_recommendations:recommendation_executed",
    ("POST", f"{REC}/manual"): "demo_shopee_reco_manual:create_manual_card",
    ("POST", f"{DEMO}/builder/choose"): "demo_shopee_builder:builder_choose",
    ("POST", f"{DEMO}/builder/drafts/title"): "demo_shopee_builder:builder_title_drafts",
    ("POST", f"{DEMO}/builder/group"): "demo_shopee_builder:builder_group",
    ("PUT", f"{DEMO}/exclusions/{{item_id}}"): "demo_shopee_builder:add_exclusion",
    ("DELETE", f"{DEMO}/exclusions/{{item_id}}"): "demo_shopee_builder:undo_exclusion",
    ("POST", f"{REC}/plan/cards"): "demo_shopee_reco_plan:add_card",
    ("POST", f"{REC}/plan/refresh-base"): "demo_shopee_reco_plan:refresh_base",
    ("POST", f"{REC}/plan/cards/{{card_id}}/remove"): "demo_shopee_reco_plan:remove_card",
    ("POST", f"{REC}/plan/cards/{{card_id}}/move"): "demo_shopee_reco_plan:move_card",
    ("POST", f"{REC}/plan/cards/{{card_id}}/version"): "demo_shopee_reco_plan:switch_version",
    ("POST", f"{REC}/plan/cards/{{card_id}}/whatif"): "demo_shopee_reco_plan:plan_whatif",
    ("POST", f"{REC}/plan/groups"): "demo_shopee_reco_plan:create_group",
    ("POST", f"{REC}/plan/groups/{{group_id}}/period"): "demo_shopee_reco_plan:group_period",
    (
        "POST",
        f"{REC}/plan/groups/{{group_id}}/members/remove",
    ): "demo_shopee_reco_plan:group_remove_member",
    ("POST", f"{REC}/plan/groups/{{group_id}}/cancel"): "demo_shopee_reco_plan:group_cancel",
    ("POST", f"{REC}/plan/confirm"): "demo_shopee_reco_plan:confirm_plan",
    ("POST", f"{REC}/plan/window"): "demo_shopee_reco_plan:plan_window",
    ("POST", f"{DEMO}/recommendations/change-sets/{{set_id}}/window"): (
        "demo_shopee_reco_plan:change_set_window"
    ),
}
SAMPLE_TEMPLATES = {**READ_TEMPLATES, **WRITE_TEMPLATES}
#: Reviewed and refused on the sample pin: the Connector's fill queue and the hidden screens.
REFUSED_TEMPLATES: dict[tuple[str, str], str] = {
    ("GET", f"{DEMO}/fill-jobs"): "ingest_fill:seller_fill_jobs",
    ("POST", f"{DEMO}/fill-jobs/{{job_id}}/cancel"): "ingest_fill:seller_cancel_fill_job",
    ("GET", f"{DEMO}/keywords"): "demo_shopee_pages:seller_keywords",
    ("GET", f"{DEMO}/dashboard/products"): "demo_shopee_pages:seller_products",
    ("GET", f"{DEMO}/dashboard/flows"): "demo_shopee_pages:seller_flows",
    ("GET", f"{DEMO}/dashboard/ads"): "demo_shopee_pages:seller_ads",
    ("GET", f"{DEMO}/dashboard/promotions"): "demo_shopee_pages:seller_promotions",
    ("GET", f"{DEMO}/orders"): "demo_shopee_pages:seller_orders",
    (
        "GET",
        f"{DEMO}/builder/products/{{item_id}}/co-purchase",
    ): "demo_shopee_builder:builder_co_purchase",
    ("GET", f"{DEMO}/builder/ads/campaigns"): "demo_shopee_builder:builder_campaigns",
    (
        "GET",
        f"{DEMO}/builder/products/{{item_id}}/market-range",
    ): "demo_shopee_market:builder_market_range",
    ("POST", f"{DEMO}/builder/combo/options"): "demo_shopee_builder_p98:combo_options",
    ("POST", f"{DEMO}/builder/kol/setup"): "demo_shopee_builder_p98:kol_setup",
    ("POST", f"{DEMO}/builder/ads/setup"): "demo_shopee_builder_p98:ads_setup",
}
LLM_TEMPLATES: dict[tuple[str, str], str] = {
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
    # P100 S2-G: no live LLM / vision client is ever built for a sample-shop reviewer.
    from juli_backend.api.routes import shopee_builder_common

    monkeypatch.setattr(shopee_builder_common, "get_client", wire.trip("LLM get_client()"))
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
    return (
        template.replace("{item_id}", ITEM)
        .replace("{card_id}", str(card_id))
        .replace("{plan_id}", str(uuid.uuid4()))
        .replace("{group_id}", str(uuid.uuid4()))
        .replace("{set_id}", str(uuid.uuid4()))
        .replace("{job_id}", str(uuid.uuid4()))
        .replace("{code}", "KH-0000-0000")
    )


def _body(method: str, template: str) -> dict[str, Any] | None:
    if method in ("GET", "DELETE"):
        return None
    if template.endswith("/approve"):
        return {"chosen_version": 1, "acknowledge_breaches": True}
    if template.endswith("/builder/compare"):
        return {"versions": [VOUCHER, TITLE], "as_of": AS_OF.isoformat()}
    if template.endswith("/evaluate"):
        return {"versions": [VOUCHER], "as_of": AS_OF.isoformat()}
    if template.endswith("/recommendations/compare"):
        second = {**MANUAL_VOUCHER, "inputs": {**MANUAL_VOUCHER["inputs"], "value": 5000}}
        return {"variants": [MANUAL_VOUCHER, second], "as_of": AS_OF.isoformat()}
    return {"item_id": ITEM, "count": 3}


MANUAL_VOUCHER = {
    "change_kind": "min_spend_voucher",
    "items": ["1002"],
    "inputs": {"value": 3000, "min_spend": 90_000, "quantity": 50, "days": 14},
}


async def _audits(session, action: str) -> list[OpsAuditLog]:
    rows = await session.execute(select(OpsAuditLog).where(OpsAuditLog.action == action))
    return list(rows.scalars().all())


_refusals = _audits


async def _rows(session, *, reviewer_id: uuid.UUID) -> dict[str, dict[tuple, Any]]:
    """Every row of every table, keyed by its content, valued by its ``shop_id`` (or None)."""
    from juli_backend.database import Base
    from tests.unit.test_reviewer_no_write import _MAY_CHANGE, _jsonable

    out: dict[str, dict[tuple, Any]] = {}
    for table in Base.metadata.sorted_tables:
        if table.name in _MAY_CHANGE:
            continue
        rows: dict[tuple, Any] = {}
        for row in (await session.execute(select(table))).all():
            mapping = dict(row._mapping)
            if table.name == "users" and mapping.get("id") == reviewer_id:
                continue
            key = tuple(sorted((k, repr(_jsonable(v))) for k, v in mapping.items()))
            rows[key] = mapping.get("shop_id", "no-shop-column")
        out[table.key] = rows
    return out


def _foreign_changes(before, after, shop_id: uuid.UUID) -> list[str]:
    """Tables where a row that is NOT the sample shop's was added, changed or removed."""
    bad = []
    for name in before:
        moved = set(before[name]) ^ set(after[name])
        owners = {before[name].get(k, after[name].get(k)) for k in moved}
        if owners - {shop_id}:
            bad.append(f"{name}: {owners - {shop_id}}")
    return bad


# -- the list itself ------------------------------------------------------------------------------


def test_the_sample_table_is_pinned_to_real_routes_and_kept_apart():
    from juli_backend.api.app import create_app

    served: dict[tuple[str, str], str] = {}
    for route in _routes(create_app()):
        for method in route.methods:
            endpoint = getattr(route, "endpoint", None) or route.original_route.endpoint
            served[(method, route.path)] = (
                f"{endpoint.__module__}:{endpoint.__qualname__}"
            ).removeprefix("juli_backend.api.routes.")
    for key, endpoint in {**SAMPLE_TEMPLATES, **LLM_TEMPLATES, **REFUSED_TEMPLATES}.items():
        assert served.get(key) == endpoint, (key, served.get(key))
    strip = "juli_backend.api.routes."

    def names(keys) -> set[tuple[str, str]]:
        return {(m, e.removeprefix(strip)) for m, e in keys}

    routes = reviewer_gate.SAMPLE_SHOP_ROUTES
    assert names(k for k, (kind, _) in routes.items() if kind == "read") == {
        (m, e) for (m, _), e in READ_TEMPLATES.items()
    }
    assert names(reviewer_gate.SAMPLE_SHOP_WRITE_ENDPOINTS) == {
        (m, e) for (m, _), e in WRITE_TEMPLATES.items()
    }
    assert all(reason for _, reason in routes.values())  # every entry says why
    assert names(reviewer_gate.SAMPLE_SHOP_LLM_ENDPOINTS) == {
        (m, e) for (m, _), e in LLM_TEMPLATES.items()
    }
    assert names(reviewer_gate.SAMPLE_SHOP_REFUSED) == {
        (m, e) for (m, _), e in REFUSED_TEMPLATES.items()
    }
    # Never on the every-pin allowlist: a masked / sandbox pin keeps refusing them.
    sample, llm = reviewer_gate.SAMPLE_SHOP_ENDPOINTS, reviewer_gate.SAMPLE_SHOP_LLM_ENDPOINTS
    refused = frozenset(reviewer_gate.SAMPLE_SHOP_REFUSED)
    assert not sample & reviewer_gate.ALLOWED_ENDPOINTS
    assert not llm & reviewer_gate.ALLOWED_ENDPOINTS
    assert not (sample & llm) and not (sample & refused) and not (refused & llm)
    # A read is a GET or one of the three pure computations.
    assert sorted(t for m, t in READ_TEMPLATES if m != "GET") == [
        f"{DEMO}/builder/compare",
        f"{DEMO}/builder/evaluate",
        f"{REC}/compare",
    ]


# -- the sample pin: reads write nothing ----------------------------------------------------------


async def test_every_sample_read_answers_and_writes_nothing(session, world, tripwire):
    _seller, sample, _sandbox, reviewer_id, ids = world
    card_id = ids["min_spend_voucher"]
    before = await _snapshot(session, reviewer_id=reviewer_id)
    async with client_for(build_app(session)) as client:
        for method, template in READ_TEMPLATES:
            response = await client.request(
                method,
                _fill(template, card_id),
                headers=_headers(reviewer_id, sample.shop_id),
                json=_body(method, template),
            )
            assert "x-juli-reviewer-denied" not in response.headers, (template, response.text)
            if "{plan_id}" in template or "{code}" in template or template.endswith("/export"):
                # unknown id / no draft plan yet: the route answered (a domain 404, not the gate)
                assert response.status_code == 404, (template, response.text)
            else:
                assert response.status_code == 200, (template, response.text)
    after = await _snapshot(session, reviewer_id=reviewer_id)
    changed = [name for name in before if before[name] != after[name]]
    assert not changed, f"tables changed by a sample-shop reviewer's read: {changed}"
    assert not tripwire.hits, tripwire.hits
    assert await _audits(session, "reviewer_sample_write") == []
    # Unmasked: the synthetic names are served as they are.
    async with client_for(build_app(session)) as client:
        listed = await client.get(
            f"{DEMO}/builder/products", headers=_headers(reviewer_id, sample.shop_id)
        )
    assert "Găng tay tự hủy sinh học STAHAUS" in listed.text


# -- the sample pin: writes reach the sample shop's own rows only (S2-G) --------------------------


async def test_every_sample_write_changes_only_the_sample_shops_rows(
    session, world, tripwire, monkeypatch
):
    """The whole write table, in the order a reviewer would use it, one request at a time:
    after each, every row that moved belongs to the sample shop; no fill job is queued although
    the Connector switch is on; one audit row per admitted write."""
    from juli_backend.models.shopee_fill import ShopeeFillJob

    monkeypatch.setenv("CONNECTOR_FILL_LISTING", "1")
    _seller, sample, _sandbox, reviewer_id, ids = world
    sid, voucher, ads = sample.shop_id, ids["min_spend_voucher"], ids["ads_budget"]
    hit: dict[str, int] = {}

    async def send(client, method: str, template: str, path: str, body: Any = None) -> Any:
        before = await _rows(session, reviewer_id=reviewer_id)
        response = await client.request(method, path, headers=_headers(reviewer_id, sid), json=body)
        assert "x-juli-reviewer-denied" not in response.headers, (path, response.text)
        assert response.status_code < 300, (path, response.status_code, response.text)
        after = await _rows(session, reviewer_id=reviewer_id)
        assert _foreign_changes(before, after, sid) == [], path
        hit[WRITE_TEMPLATES[(method, template)]] = response.status_code
        return response.json() if response.content else None

    async with client_for(build_app(session)) as client:
        # Quyết định: what-if, Duyệt (real), Đã làm, the measurement window
        await send(client, "POST", f"{REC}/{{card_id}}/whatif", f"{REC}/{voucher}/whatif", {})
        approved = await send(
            client,
            "POST",
            f"{REC}/{{card_id}}/approve",
            f"{REC}/{voucher}/approve",
            {"chosen_version": 1, "acknowledge_breaches": True},
        )
        assert approved["status"] == "approved" and "simulated" not in approved
        done = await send(
            client,
            "POST",
            f"{REC}/{{card_id}}/executed",
            f"{REC}/{voucher}/executed",
            {"voucher_id": "9300000000009"},
        )
        set_id = done["change_set"]["id"]
        await send(
            client,
            "POST",
            f"{REC}/change-sets/{{set_id}}/window",
            f"{REC}/change-sets/{set_id}/window",
            {"days": 7},
        )
        # Tự tạo: "Chọn" (both paths) and "Chạy cùng nhau"
        made = await send(
            client, "POST", f"{REC}/manual", f"{REC}/manual", {"variants": [MANUAL_VOUCHER]}
        )
        manual_id = made["id"]
        await send(
            client,
            "POST",
            f"{DEMO}/builder/choose",
            f"{DEMO}/builder/choose",
            {"versions": [TITLE], "chosen": 0, "acknowledge_breaches": True},
        )
        await send(
            client,
            "POST",
            f"{DEMO}/builder/group",
            f"{DEMO}/builder/group",
            {"versions": [VOUCHER, TITLE], "members": [0, 1], "acknowledge_breaches": True},
        )
        # Kế hoạch
        plan_card = f"{REC}/plan/cards/{manual_id}"
        await send(
            client,
            "POST",
            f"{REC}/plan/cards",
            f"{REC}/plan/cards",
            {"card_id": manual_id, "acknowledge_breaches": True},
        )
        await send(
            client, "POST", f"{REC}/plan/cards/{{card_id}}/move", f"{plan_card}/move",
            {"position": 1},
        )  # fmt: skip
        await send(
            client, "POST", f"{REC}/plan/cards/{{card_id}}/version", f"{plan_card}/version",
            {"version": 1},
        )  # fmt: skip
        await send(
            client, "POST", f"{REC}/plan/cards/{{card_id}}/whatif", f"{plan_card}/whatif",
            {"inputs": {}},
        )  # fmt: skip
        await send(client, "POST", f"{REC}/plan/window", f"{REC}/plan/window", {"days": 7})
        await send(client, "POST", f"{REC}/plan/refresh-base", f"{REC}/plan/refresh-base", {})
        plan = await send(
            client,
            "POST",
            f"{REC}/plan/groups",
            f"{REC}/plan/groups",
            {"members": [{"card_id": manual_id, "version": 1}], "acknowledge_breaches": True},
        )
        group_id = plan["groups"][-1]["id"]
        group = f"{REC}/plan/groups/{group_id}"
        await send(
            client, "POST", f"{REC}/plan/groups/{{group_id}}/period", f"{group}/period",
            {"days": 10},
        )  # fmt: skip
        await send(client, "POST", f"{REC}/plan/groups/{{group_id}}/cancel", f"{group}/cancel", {})
        plan = await send(
            client,
            "POST",
            f"{REC}/plan/groups",
            f"{REC}/plan/groups",
            {"members": [{"card_id": manual_id, "version": 1}], "acknowledge_breaches": True},
        )
        group = f"{REC}/plan/groups/{plan['groups'][-1]['id']}"
        await send(
            client, "POST", f"{REC}/plan/groups/{{group_id}}/members/remove",
            f"{group}/members/remove", {"card_id": manual_id, "version": 1},
        )  # fmt: skip
        await send(
            client, "POST", f"{REC}/plan/cards/{{card_id}}/remove", f"{plan_card}/remove", {}
        )
        await send(
            client, "POST", f"{REC}/plan/cards", f"{REC}/plan/cards",
            {"card_id": manual_id, "acknowledge_breaches": True},
        )  # fmt: skip
        await send(
            client, "POST", f"{REC}/plan/confirm", f"{REC}/plan/confirm",
            {"acknowledge_breaches": True},
        )  # fmt: skip
        # Yêu cầu chỉnh / Bỏ qua
        await send(
            client, "POST", f"{REC}/{{card_id}}/request-change", f"{REC}/{ads}/request-change",
            {"note": "Thử lại"},
        )  # fmt: skip
        await send(
            client, "POST", f"{REC}/{{card_id}}/dismiss", f"{REC}/{ads}/dismiss",
            {"reason_code": None, "note": None},
        )  # fmt: skip
        # P100 S2-D: Tiêu đề drafts -- the seeded titles (no LLM client is built)
        titles = await passing_titles(session, sid, ITEM, as_of=AS_OF, now=NOW)
        await seed_title_spec(session, sid, ITEM, titles, now=NOW)
        drafted = await send(
            client, "POST", f"{DEMO}/builder/drafts/title", f"{DEMO}/builder/drafts/title",
            {"item_id": ITEM, "count": 3, "as_of": AS_OF.isoformat()},
        )  # fmt: skip
        assert drafted["source"] == "seeded" and drafted["live_left"] == 1
        assert [d["title"] for d in drafted["drafts"]] == titles
        # Loại trừ, and back
        await send(
            client, "PUT", f"{DEMO}/exclusions/{{item_id}}", f"{DEMO}/exclusions/{ITEM}",
            {"reason": "khac"},
        )  # fmt: skip
        await send(client, "DELETE", f"{DEMO}/exclusions/{{item_id}}", f"{DEMO}/exclusions/{ITEM}")
    assert set(hit) == set(WRITE_TEMPLATES.values()), set(WRITE_TEMPLATES.values()) - set(hit)
    assert not tripwire.hits, tripwire.hits
    jobs = (await session.execute(select(ShopeeFillJob))).scalars().all()
    assert jobs == [], "a reviewer's approve queued work for the Connector"
    audited = await _audits(session, "reviewer_sample_write")
    assert {r.shop_id for r in audited} == {sid}
    assert {r.after["endpoint"].removeprefix("juli_backend.api.routes.") for r in audited} == set(
        WRITE_TEMPLATES.values()
    )
    assert all(r.actor_email.startswith("reviewer:shopee:") for r in audited)
    assert all(set(r.after) == {"platform", "method", "endpoint", "path"} for r in audited)


async def test_duyet_on_the_sample_shop_is_the_real_approve(session, world, tripwire):
    """The card moves to Đang thực hiện (status approved), approved by the reviewer's user."""
    from juli_backend.models.shop_proposals import ShopProposalApproval

    _seller, sample, _sandbox, reviewer_id, ids = world
    card_id = ids["min_spend_voucher"]
    async with client_for(build_app(session)) as client:
        first = await client.post(
            f"{REC}/{card_id}/approve",
            json={"chosen_version": 1, "acknowledge_breaches": True},
            headers=_headers(reviewer_id, sample.shop_id),
        )
        detail = await client.get(f"{REC}/{card_id}", headers=_headers(reviewer_id, sample.shop_id))
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["id"] == str(card_id) and body["status"] == "approved"
    assert "simulated" not in body
    assert detail.json()["status"] == "approved"  # Đang thực hiện
    (approval,) = (await session.execute(select(ShopProposalApproval))).scalars().all()
    assert approval.decided_by_user_id == reviewer_id and approval.shop_id == sample.shop_id
    assert await _audits(session, "reviewer_simulated_approve") == []
    (row,) = await _audits(session, "reviewer_sample_write")
    assert row.after["path"] == f"{REC}/{card_id}/approve"
    assert not tripwire.hits


async def test_approve_refuses_a_card_outside_the_three_strategies(session, world):
    _seller, sample, _sandbox, reviewer_id, ids = world
    before = await _snapshot(session, reviewer_id=reviewer_id)
    async with client_for(build_app(session)) as client:
        ads = await client.post(
            f"{REC}/{ids['ads_budget']}/approve",
            json={"chosen_version": 1},
            headers=_headers(reviewer_id, sample.shop_id),
        )
        unknown = await client.post(
            f"{REC}/{uuid.uuid4()}/approve",
            json={"chosen_version": 1},
            headers=_headers(reviewer_id, sample.shop_id),
        )
    assert ads.status_code == 403 and ads.headers["x-juli-reviewer-denied"] == "read_only"
    assert unknown.status_code == 404
    after = await _snapshot(session, reviewer_id=reviewer_id)
    assert [n for n in before if before[n] != after[n]] == []
    assert await _audits(session, "reviewer_sample_write") == []  # rolled back with the refusal


def test_the_fill_queue_is_off_inside_a_reviewer_request(monkeypatch):
    from juli_backend.integrations.tiktok.reviewer_scope import reviewer_session
    from juli_backend.services.shopee_recommendations import fill_queue

    monkeypatch.setenv("CONNECTOR_FILL_LISTING", "1")
    assert fill_queue.enabled() is True  # a seller's approve still queues
    with reviewer_session():
        assert fill_queue.enabled() is False


# -- other pins: unchanged ------------------------------------------------------------------------


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
    assert await _audits(session, "reviewer_sample_write") == []


async def test_the_shop_entry_refuses_a_sample_route_when_the_pin_is_not_sample(session, world):
    """Second layer: the gate admitted the route, but the entered pin is not the sample shop."""
    seller, _sample, _sandbox, _reviewer_id, _ids = world
    from juli_backend.services.reviewer.sandbox import MODE_MASKED, PinMode

    for write in (False, True):
        context = reviewer_gate.ReviewerContext(
            account=await _account(session),
            platform="shopee",
            shop_id=seller.shop.id,
            alias_id=None,
            sample_only=True,
            sample_write=write,
            method="POST" if write else "GET",
            endpoint="juli_backend.api.routes.demo_shopee_analytics:shopee_overview",
        )
        context.pin = PinMode(MODE_MASKED, writes_enabled=False)
        context.shop = seller.shop
        with pytest.raises(Exception) as refused:
            await reviewer_gate.enter_reviewer_shop(session, context, None)
        assert getattr(refused.value, "status_code", None) == 403
        assert getattr(refused.value, "headers", {})["X-Juli-Reviewer-Denied"] == "read_only"
    assert await _audits(session, "reviewer_sample_write") == []


async def test_a_masked_reviewer_reaching_approve_gets_the_simulation_never_a_real_approve(
    session, world
):
    """Fail closed below the gate: the route itself approves for real only on the sample pin."""
    from starlette.requests import Request

    from juli_backend.api.routes import demo_shopee_recommendations as route
    from juli_backend.api.routes.shopee_recommendations_common import ApproveBody
    from juli_backend.services.reviewer.sandbox import MODE_MASKED, MODE_SANDBOX, PinMode

    _seller, sample, _sandbox, reviewer_id, ids = world
    before = await _snapshot(session, reviewer_id=reviewer_id)
    for mode, expect in ((MODE_MASKED, "simulated"), (MODE_SANDBOX, "refused")):
        context = reviewer_gate.ReviewerContext(
            account=await _account(session),
            platform="shopee",
            shop_id=sample.shop_id,
            alias_id=None,
        )
        context.pin = PinMode(mode, writes_enabled=mode == MODE_SANDBOX)
        request = Request({"type": "http", "state": {reviewer_gate.STATE_KEY: context}})
        call = route.approve_recommendation(
            ids["min_spend_voucher"],
            ApproveBody(chosen_version=1, acknowledge_breaches=True),
            request,
            shop=sample.shop,
            user=cast(Any, None),
            session=session,
        )
        if expect == "simulated":
            assert (await call)["simulated"] is True
        else:
            with pytest.raises(Exception) as refused:
                await call
            assert getattr(refused.value, "status_code", None) == 403
    after = await _snapshot(session, reviewer_id=reviewer_id)
    assert [n for n in before if before[n] != after[n]] == []


async def _account(session):
    from juli_backend.services.reviewer import accounts

    (row,) = (await session.execute(select(accounts.OpsReviewerAccount))).scalars().all()
    return accounts._snapshot(row)


# -- refused on the sample pin: outbound and hidden -----------------------------------------------


async def test_outbound_and_hidden_routes_stay_refused_on_the_sample_shop(session, world, tripwire):
    _seller, sample, _sandbox, reviewer_id, ids = world
    before = await _snapshot(session, reviewer_id=reviewer_id)
    async with client_for(build_app(session)) as client:
        for method, template in REFUSED_TEMPLATES:
            path = _fill(template, ids["min_spend_voucher"])
            if template.endswith("/fill-jobs"):
                path += f"?card_id={ids['min_spend_voucher']}"
            response = await client.request(
                method, path, headers=_headers(reviewer_id, sample.shop_id), json=None
            )
            assert response.status_code == 403, (template, response.text)
            assert response.headers["x-juli-reviewer-denied"] == "read_only", template
    after = await _snapshot(session, reviewer_id=reviewer_id)
    assert [n for n in before if before[n] != after[n]] == []
    assert not tripwire.hits
    refused = await _audits(session, "reviewer_write_refused") + await _audits(
        session, "reviewer_read_refused"
    )
    assert len(refused) == len(REFUSED_TEMPLATES)


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
    assert len(refused) == 2 and {r.after["reason"] for r in refused} == {"sample_llm_off"}


# -- P100 S2-D: Tiêu đề drafts -- the pre-written titles, then one live draft per product --------
#
# A plain request serves the newest stored title spec through the same screen as a live draft (no
# LLM client, no content row written); ``regenerate`` runs ONE live draft per product, stored as
# ``source='llm'``; a second one is 403 ``sample_llm_quota``, audited, with no model call; a ticked
# keyword the stored titles lack drops them (422); a masked pin keeps refusing the route.

TITLE_URL = f"{DEMO}/builder/drafts/title"


class FakeModel:
    """A stand-in for the gated client: counts calls, answers with the given titles."""

    model = "fake-model"

    def __init__(self, titles: list[str]) -> None:
        self.titles = titles
        self.calls = 0

    async def complete_json(self, **_: Any) -> dict[str, Any]:
        self.calls += 1
        return {"drafts": [{"title": t, "note": "live"} for t in self.titles]}


async def _spec_count(session) -> int:
    return int(await session.scalar(select(func.count()).select_from(CardContentSpec)) or 0)


def _title_body(**extra: Any) -> dict[str, Any]:
    return {"item_id": ITEM, "count": 3, "as_of": AS_OF.isoformat(), **extra}


async def test_the_seeded_titles_need_no_model_and_store_nothing(session, world, tripwire):
    _seller, sample, _sandbox, reviewer_id, _ids = world
    titles = await passing_titles(session, sample.shop_id, ITEM, as_of=AS_OF, now=NOW)
    await seed_title_spec(session, sample.shop_id, ITEM, titles, now=NOW)
    before = await _spec_count(session)
    async with client_for(build_app(session)) as client:
        response = await client.post(
            TITLE_URL, json=_title_body(), headers=_headers(reviewer_id, sample.shop_id)
        )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["source"] == "seeded" and data["model"] == "seeded" and data["live_left"] == 1
    assert [d["title"] for d in data["drafts"]] == titles
    assert all(d["chars"] == len(d["title"]) for d in data["drafts"])
    assert await _spec_count(session) == before
    assert not tripwire.hits
    assert len(await _audits(session, "reviewer_sample_write")) == 1


async def test_one_live_draft_per_product_then_the_quota_refuses(session, world, monkeypatch):
    _seller, sample, _sandbox, reviewer_id, _ids = world
    sid = sample.shop_id
    titles = await passing_titles(session, sid, ITEM, as_of=AS_OF, now=NOW)
    await seed_title_spec(session, sid, ITEM, titles[:1], now=NOW)
    fake = FakeModel(titles[1:])

    async def get_client(_session, _shop_id):
        return fake

    monkeypatch.setattr(shopee_builder_common, "get_client", get_client)
    headers = _headers(reviewer_id, sid)
    async with client_for(build_app(session)) as client:
        live = await client.post(TITLE_URL, json=_title_body(regenerate=True), headers=headers)
        assert live.status_code == 200, live.text
        assert live.json()["source"] == "llm" and live.json()["live_left"] == 0
        assert [d["title"] for d in live.json()["drafts"]] == titles[1:]
        again = await client.post(TITLE_URL, json=_title_body(regenerate=True), headers=headers)
        assert again.status_code == 403, again.text
        assert again.headers["x-juli-reviewer-denied"] == "sample_llm_quota"
        assert "đã dùng lượt viết lại" in again.json()["detail"]
        latest = await client.post(TITLE_URL, json=_title_body(), headers=headers)
    assert fake.calls == 1
    rows = (
        (await session.execute(select(CardContentSpec).where(CardContentSpec.source == SOURCE_LLM)))
        .scalars()
        .all()
    )
    assert len(rows) == 1 and rows[0].shop_id == sid and rows[0].item_id == ITEM
    assert rows[0].created_by_user_id == reviewer_id
    assert [c["title"] for c in rows[0].spec["candidates"]] == titles[1:]
    # The plain request now serves the newest spec (the live one) and offers no second draft.
    assert latest.status_code == 200 and latest.json()["source"] == "llm"
    assert latest.json()["live_left"] == 0
    refused = await _audits(session, "reviewer_write_refused")
    assert [r.after["reason"] for r in refused] == ["sample_llm_quota"]


async def test_a_ticked_keyword_the_stored_titles_lack_drops_them(session, world, tripwire):
    _seller, sample, _sandbox, reviewer_id, _ids = world
    titles = await passing_titles(session, sample.shop_id, ITEM, as_of=AS_OF, now=NOW)
    await seed_title_spec(session, sample.shop_id, ITEM, titles, now=NOW)
    async with client_for(build_app(session)) as client:
        response = await client.post(
            TITLE_URL,
            json=_title_body(keywords=["từ khoá không có"]),
            headers=_headers(reviewer_id, sample.shop_id),
        )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "llm_no_valid_draft"
    assert not tripwire.hits


@pytest.mark.parametrize("regenerate", [False, True])
async def test_a_masked_pin_keeps_refusing_the_title_drafts(session, world, tripwire, regenerate):
    from juli_backend.services.reviewer.config import shop_alias_id

    seller, _sample, _sandbox, reviewer_id, _ids = world
    async with client_for(build_app(session)) as client:
        response = await client.post(
            TITLE_URL,
            json=_title_body(regenerate=regenerate),
            headers=_headers(reviewer_id, shop_alias_id(seller.shop.id)),
        )
    assert response.status_code == 403
    assert response.headers["x-juli-reviewer-denied"] == "read_only"
    assert not tripwire.hits
