"""P74-A (D77) -- the partner reviewer holds two pins: Fujiwa (masked) first, the sandbox second.

Owner decision 2026-10-29: Shopee's reviewer opens on the real production shop, masked and
read-only with the simulated Duyệt / Thực thi (D42), and may switch (``X-Shop-Id``) to Juli's
own TikTok sandbox shop for live writes (D73). Each pin is classified on its own and
everything a request does follows the pin it selected. The hard invariant: nothing the
reviewer does writes to the masked shop -- no run, no rule, no sync, no card change.

Real signed tokens through the real ``get_current_user`` (the gate lives there), SQLite.
"""

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from juli_backend.integrations.tiktok import TikTokCapability
from juli_backend.models.models import ActionCard, WorkflowRun
from juli_backend.models.run_changes import ShopRule
from juli_backend.repositories import TikTokCredentialRepo
from juli_backend.services.reviewer import config as reviewer_config
from juli_backend.services.reviewer import sandbox as reviewer_sandbox
from juli_backend.services.reviewer.config import shop_alias_id
from juli_backend.services.reviewer.masking import REVIEWER_SHOP_LABEL
from tests.support import reviewer as rv
from tests.support.api import build_app, client_for
from tests.support.builders import utc_now_naive

SANDBOX_SHOP_NAME = "Juli Sandbox VN"


@pytest.fixture(autouse=True)
def reviewer_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", rv.JWT_SECRET)
    monkeypatch.setenv("REVIEWER_ACCOUNT_CACHE_SECONDS", "0")
    monkeypatch.setenv("TIKTOK_APP_KEY", "app-key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "app-secret")
    monkeypatch.delenv("REVIEWER_SHOP_ID", raising=False)
    rv.reset_caches()
    reviewer_sandbox.forget_sync_slots()
    yield
    rv.reset_caches()
    reviewer_sandbox.forget_sync_slots()


async def _credential(session, shop, capability: TikTokCapability, merchant: str, token: str):
    return await TikTokCredentialRepo(session).create(
        shop.id,
        token,
        f"{token}-refresh",
        utc_now_naive() + timedelta(days=30),
        merchant_authorization_id=merchant,
        capability=capability.value,
        shop_cipher=f"cipher-{merchant}",
        scopes="seller.product.basic,seller.order.info",
    )


@pytest.fixture
async def world(session, monkeypatch):
    """Fujiwa (production_read) pinned first, the sandbox shop (sandbox_write) second."""
    fujiwa = await rv.seed_reference_shop(session)
    sandbox = await rv.seed_reference_shop(
        session,
        name=SANDBOX_SHOP_NAME,
        tiktok_shop_id="7600000000000000001",
        title="Sandbox áo thun",
        product_id="1730000000000000001",
        seller_sku="SBX-01",
    )
    await _credential(
        session, sandbox.shop, TikTokCapability.SANDBOX_WRITE, "sandbox-merchant", "sbx-token"
    )
    await _credential(
        session, fujiwa.shop, TikTokCapability.PRODUCTION_READ, "prod-merchant", "fuji-token"
    )
    await session.commit()
    monkeypatch.setenv("REVIEWER_SHOP_IDS", f"{fujiwa.shop.id},{sandbox.shop.id}")
    reviewer_id = await rv.make_reviewer(session)
    return fujiwa, sandbox, reviewer_id


def _headers(user_id, shop_id=None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {rv.token(user_id)}"}
    if shop_id is not None:
        headers["X-Shop-Id"] = str(shop_id)
    return headers


def _assert_masked(text: str, fujiwa_id: uuid.UUID) -> None:
    for secret in (*rv.SECRETS, str(fujiwa_id)):
        assert secret not in text, f"{secret!r} leaked: {text[:400]}"


@pytest.fixture
def enqueued(monkeypatch) -> list[Any]:
    """Everything a reviewer request would hand to Celery (runs, resumes, poll_shop)."""
    queued: list[Any] = []
    monkeypatch.setattr(
        "juli_backend.api.routes.demo_execution._enqueue_run_agent_workflow",
        lambda run_id: queued.append(("run", run_id)) or "celery-1",
    )
    monkeypatch.setattr(
        "juli_backend.api.routes.demo_execution._enqueue_approval_baseline",
        lambda shop_id, run_id: None,
    )
    monkeypatch.setattr(
        "juli_backend.api.routes.agent_runs._enqueue_resume_agent_workflow",
        lambda run_id, approved: queued.append(("resume", run_id)) or "celery-2",
    )
    monkeypatch.setattr(
        "juli_backend.api.routes.reviewer._enqueue_poll_shop",
        lambda shop_id: queued.append(("poll_shop", shop_id)) or "task-1",
    )
    return queued


def _write_routes(card_id: uuid.UUID, run_id: uuid.UUID) -> list[tuple[str, str, Any]]:
    """Every sandbox-only route (runs, Hoàn tác, rules) plus the sync and the shop card."""
    return [
        ("POST", f"/v1/demo/decisions/{card_id}/approve", None),
        ("GET", f"/v1/demo/runs/{run_id}/events", None),
        ("POST", f"/v1/demo/runs/{run_id}/confirmations/call_1", {"decision": "approve"}),
        ("POST", f"/v1/demo/runs/{run_id}/cancel", None),
        ("POST", f"/v1/demo/runs/{run_id}/photo", None),
        ("POST", f"/v1/demo/runs/{run_id}/decline", {"reason_code": "other"}),
        ("POST", f"/v1/demo/runs/{run_id}/revert", None),
        (
            "PUT",
            "/v1/demo/rules/stability_band",
            {"scope_ref": "ctr", "value": 12.5, "set_by": "seller"},
        ),
        ("DELETE", "/v1/demo/rules/stability_band?scope_ref=ctr", None),
        ("POST", "/v1/reviewer/shop/sync", None),
        ("GET", "/v1/reviewer/shop", None),
    ]


# -- config -------------------------------------------------------------------------------


def test_reviewer_shop_ids_wins_over_the_single_pin_and_keeps_its_order(monkeypatch):
    first, second, single = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    monkeypatch.setenv("REVIEWER_SHOP_ID", str(single))
    monkeypatch.setenv("REVIEWER_SHOP_IDS", f" {first} , not-a-uuid,{second},{first}")
    assert reviewer_config.reviewer_shop_ids() == (first, second)
    assert reviewer_config.reviewer_shop_id() == first
    monkeypatch.setenv("REVIEWER_SHOP_IDS", " , junk")
    assert reviewer_config.reviewer_shop_ids() == (single,)
    monkeypatch.delenv("REVIEWER_SHOP_ID")
    assert reviewer_config.reviewer_shop_ids() == ()
    assert reviewer_config.reviewer_shop_id() is None


def test_select_pin_takes_an_alias_or_a_real_id_else_the_default():
    first, second = uuid.uuid4(), uuid.uuid4()
    pins = (first, second)
    assert reviewer_config.select_pin(pins, None) == first
    assert reviewer_config.select_pin(pins, str(shop_alias_id(second)).upper()) == second
    assert reviewer_config.select_pin(pins, str(second)) == second
    assert reviewer_config.select_pin(pins, str(uuid.uuid4())) == first
    assert reviewer_config.select_pin((), str(first)) is None


# -- the default pin and the switch -------------------------------------------------------


async def test_me_defaults_to_the_first_pin_masked_and_lists_both(session, world):
    fujiwa, sandbox, reviewer_id = world
    alias = shop_alias_id(fujiwa.shop.id)
    async with client_for(build_app(session)) as client:
        me = await client.get("/v1/reviewer/me", headers=_headers(reviewer_id))
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["shop"]["id"] == str(alias)
    assert body["mode"] == "masked" and body["writes_enabled"] is False
    assert [s["id"] for s in body["shops"]] == [str(alias), str(sandbox.shop.id)]
    assert [(s["mode"], s["writes_enabled"]) for s in body["shops"]] == [
        ("masked", False),
        ("sandbox", True),
    ]
    assert body["shops"][0]["name"] == REVIEWER_SHOP_LABEL
    assert body["shop"]["name"] == REVIEWER_SHOP_LABEL
    # P74-A: the masked production shop never reads as a "demo" (Shopee: not live).
    assert "demo" not in body["shop"]["name"].lower()
    _assert_masked(me.text, fujiwa.shop.id)


async def test_me_on_the_sandbox_pin_is_live_and_still_masks_fujiwa(session, world):
    fujiwa, sandbox, reviewer_id = world
    async with client_for(build_app(session)) as client:
        me = await client.get("/v1/reviewer/me", headers=_headers(reviewer_id, sandbox.shop.id))
    body = me.json()
    assert body["shop"] == {"id": str(sandbox.shop.id), "name": SANDBOX_SHOP_NAME}
    assert body["mode"] == "sandbox" and body["writes_enabled"] is True
    # The mask is off on the sandbox pin: the Fujiwa entry is masked by the route itself.
    assert body["shops"][0] == {
        "id": str(shop_alias_id(fujiwa.shop.id)),
        "name": REVIEWER_SHOP_LABEL,
        "mode": "masked",
        "writes_enabled": False,
    }
    _assert_masked(me.text, fujiwa.shop.id)


@pytest.mark.parametrize("selected", ["default", "fujiwa_alias", "sandbox"])
async def test_shops_list_returns_both_pins_default_first_and_never_fujiwas_identity(
    session, world, selected
):
    fujiwa, sandbox, reviewer_id = world
    alias = shop_alias_id(fujiwa.shop.id)
    header = {"default": None, "fujiwa_alias": alias, "sandbox": sandbox.shop.id}[selected]
    async with client_for(build_app(session)) as client:
        response = await client.get("/v1/shops", headers=_headers(reviewer_id, header))
    assert response.status_code == 200, response.text
    shops = response.json()
    assert [s["id"] for s in shops] == [str(alias), str(sandbox.shop.id)]
    assert shops[0]["shop_name"] == REVIEWER_SHOP_LABEL
    assert shops[0]["tiktok_shop_id"] is None
    if selected == "sandbox":
        assert shops[1]["shop_name"] == SANDBOX_SHOP_NAME
    _assert_masked(response.text, fujiwa.shop.id)


async def test_the_pin_accepts_only_a_masked_alias_and_the_sandbox_id(session, world):
    fujiwa, sandbox, reviewer_id = world
    async with client_for(build_app(session)) as client:
        by_alias = await client.get(
            "/v1/shops/me", headers=_headers(reviewer_id, shop_alias_id(fujiwa.shop.id))
        )
        by_real_fujiwa = await client.get(
            "/v1/shops/me", headers=_headers(reviewer_id, fujiwa.shop.id)
        )
        by_sandbox_id = await client.get(
            "/v1/shops/me", headers=_headers(reviewer_id, sandbox.shop.id)
        )
        by_sandbox_alias = await client.get(
            "/v1/shops/me", headers=_headers(reviewer_id, shop_alias_id(sandbox.shop.id))
        )
        by_stranger = await client.get("/v1/shops/me", headers=_headers(reviewer_id, uuid.uuid4()))
    assert by_alias.status_code == 200
    assert by_alias.json()["id"] == str(shop_alias_id(fujiwa.shop.id))
    _assert_masked(by_alias.text, fujiwa.shop.id)
    assert by_real_fujiwa.status_code == 403
    assert by_real_fujiwa.headers["x-juli-reviewer-denied"] == "shop"
    assert by_sandbox_id.status_code == 200
    assert by_sandbox_id.json()["shop_name"] == SANDBOX_SHOP_NAME
    assert by_sandbox_alias.status_code == 200
    assert by_stranger.status_code == 403
    assert by_stranger.headers["x-juli-reviewer-denied"] == "shop"


async def test_the_mask_follows_the_selected_pin(session, world):
    fujiwa, sandbox, reviewer_id = world
    fujiwa_id = fujiwa.shop.id
    async with client_for(build_app(session)) as client:
        masked = await client.get(
            f"/v1/demo/decisions/{fujiwa.card.id}",
            headers=_headers(reviewer_id, shop_alias_id(fujiwa_id)),
        )
        live = await client.get(
            f"/v1/demo/decisions/{sandbox.card.id}", headers=_headers(reviewer_id, sandbox.shop.id)
        )
        # Each pin reads only its own shop: the other pin's card is not found.
        crossed = await client.get(
            f"/v1/demo/decisions/{fujiwa.card.id}", headers=_headers(reviewer_id, sandbox.shop.id)
        )
    assert masked.status_code == 200, masked.text
    _assert_masked(masked.text, fujiwa_id)
    # P74-A (D77): the masked shop's labels never read "demo" (Shopee: not live).
    assert "demo product" not in masked.text.lower()
    assert re.search(r"demo-[a-z]+-[0-9a-f]{8}", masked.text) is None
    assert live.status_code == 200, live.text
    assert "Sandbox áo thun" in live.text  # the sandbox shop is shown as it is
    assert str(fujiwa_id) not in live.text
    assert crossed.status_code == 404


# -- the hard invariant: nothing writes to the masked pin ---------------------------------


async def test_every_write_and_sync_route_is_refused_on_the_masked_pin(session, world, enqueued):
    fujiwa, _, reviewer_id = world
    fujiwa_id, card_id = fujiwa.shop.id, fujiwa.card.id
    alias = shop_alias_id(fujiwa_id)
    async with client_for(build_app(session)) as client:
        for method, path, body in _write_routes(card_id, uuid.uuid4()):
            response = await client.request(
                method, path, json=body, headers=_headers(reviewer_id, alias)
            )
            assert response.status_code == 403, (path, response.text)
            assert response.headers["x-juli-reviewer-denied"] == "sandbox_only", path
        # No header = the default pin (Fujiwa): the sync and the shop card refuse too.
        for method, path in (("POST", "/v1/reviewer/shop/sync"), ("GET", "/v1/reviewer/shop")):
            response = await client.request(method, path, headers=_headers(reviewer_id))
            assert response.status_code == 403, (path, response.text)
            assert response.headers["x-juli-reviewer-denied"] == "sandbox_only", path
    assert enqueued == []
    session.expire_all()
    assert (await session.execute(select(WorkflowRun))).scalars().all() == []
    rules = (await session.execute(select(ShopRule).where(ShopRule.shop_id == fujiwa_id))).scalars()
    assert list(rules) == []
    status = (
        await session.execute(select(ActionCard.status).where(ActionCard.id == card_id))
    ).scalar_one()
    assert status == "active"


async def test_the_masked_pin_keeps_the_simulation(session, world):
    fujiwa, sandbox, reviewer_id = world
    async with client_for(build_app(session)) as client:
        simulated = await client.post(
            f"/v1/reviewer/decisions/{fujiwa.card.id}/simulate",
            json={"step": "execute"},
            headers=_headers(reviewer_id, shop_alias_id(fujiwa.shop.id)),
        )
        retired = await client.post(
            f"/v1/reviewer/decisions/{sandbox.card.id}/simulate",
            json={"step": "execute"},
            headers=_headers(reviewer_id, sandbox.shop.id),
        )
    assert simulated.status_code == 200, simulated.text
    assert simulated.json()["simulated"] is True
    _assert_masked(simulated.text, fujiwa.shop.id)
    assert retired.status_code == 403
    assert retired.headers["x-juli-reviewer-denied"] == "sandbox_live"


async def test_the_sandbox_pin_still_syncs_approves_and_sets_rules(session, world, enqueued):
    fujiwa, sandbox, reviewer_id = world
    fujiwa_id, sandbox_id, card_id = fujiwa.shop.id, sandbox.shop.id, sandbox.card.id
    async with client_for(build_app(session)) as client:
        shop = await client.get("/v1/reviewer/shop", headers=_headers(reviewer_id, sandbox_id))
        sync = await client.post(
            "/v1/reviewer/shop/sync", headers=_headers(reviewer_id, sandbox_id)
        )
        approve = await client.post(
            f"/v1/demo/decisions/{card_id}/approve", headers=_headers(reviewer_id, sandbox_id)
        )
        band = await client.put(
            "/v1/demo/rules/stability_band",
            json={"scope_ref": "ctr", "value": 9, "set_by": "seller"},
            headers=_headers(reviewer_id, sandbox_id),
        )
    assert shop.status_code == 200, shop.text
    assert sync.status_code == 202, sync.text
    assert approve.status_code == 202, approve.text
    assert band.status_code == 200, band.text
    run_id = uuid.UUID(approve.json()["data"]["run_id"])
    assert enqueued == [("poll_shop", sandbox_id), ("run", run_id)]
    session.expire_all()
    runs = (await session.execute(select(WorkflowRun))).scalars().all()
    assert [run.shop_id for run in runs] == [sandbox_id]
    rule_shops = {r.shop_id for r in (await session.execute(select(ShopRule))).scalars()}
    assert rule_shops == {sandbox_id}
    assert fujiwa_id not in rule_shops


async def test_switching_back_and_forth_never_crosses_the_pins(session, world, enqueued):
    """Warm caches for both pins: each request still gets ITS pin's mode and mask."""
    fujiwa, sandbox, reviewer_id = world
    alias = shop_alias_id(fujiwa.shop.id)
    async with client_for(build_app(session)) as client:
        for _ in range(2):
            live = await client.get(
                "/v1/reviewer/me", headers=_headers(reviewer_id, sandbox.shop.id)
            )
            masked = await client.get("/v1/reviewer/me", headers=_headers(reviewer_id, alias))
            assert live.json()["mode"] == "sandbox"
            assert masked.json()["mode"] == "masked"
            _assert_masked(masked.text, fujiwa.shop.id)
            refused = await client.post(
                "/v1/reviewer/shop/sync", headers=_headers(reviewer_id, alias)
            )
            assert refused.headers["x-juli-reviewer-denied"] == "sandbox_only"
    assert enqueued == []
