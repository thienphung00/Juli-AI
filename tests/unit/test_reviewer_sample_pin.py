"""P100 S2-B -- the reviewer's third pin mode, ``sample``: a synthetic Shopee shop.

A separate slice (S2-A) loads a synthetic Shopee shop ("Dữ liệu mẫu") through the ingest
gateway. Listed in ``REVIEWER_SAMPLE_SHOP_IDS`` (and pinned through ``REVIEWER_SHOP_IDS``), it is
shown UNMASKED (its names are synthetic) but stays read-only: Duyệt / Thực thi are the same
simulation as on a masked pin, and every sandbox-only route refuses. The pin is ``sample`` only
when every check holds; any failing check is the P32 ``masked`` mode, with a warning naming the
reason. Fujiwa's id is refused as sample whatever the env says.

Same shape as ``test_reviewer_sandbox_live.py`` / ``test_reviewer_two_pins.py``: real signed
tokens through the real ``get_current_user``, SQLite.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from juli_backend.core.security import SandboxWriteOwner
from juli_backend.integrations.tiktok import TikTokCapability
from juli_backend.models.ingest import IngestToken
from juli_backend.models.models import (
    ActionCard,
    ProductionWriteShop,
    TikTokCredential,
    WorkflowRun,
)
from juli_backend.models.run_changes import ShopRule
from juli_backend.repositories import TikTokCredentialRepo
from juli_backend.services.reviewer import config as reviewer_config
from juli_backend.services.reviewer import sandbox as reviewer_sandbox
from juli_backend.services.reviewer.config import shop_alias_id
from juli_backend.services.reviewer.sandbox import (
    MODE_MASKED,
    MODE_SAMPLE,
    REASON_SAMPLE_FACTS_MISSING,
    REASON_SAMPLE_NOT_SHOPEE,
    REASON_SAMPLE_PRODUCTION_WRITE,
    REASON_SAMPLE_REFUSED_SHOP,
    REASON_SAMPLE_SANDBOX_OWNER,
    REASON_SAMPLE_SHOP,
    REASON_SAMPLE_TIKTOK_CREDENTIAL,
    REASON_SAMPLE_TIKTOK_LINKED,
    PinShopFacts,
    pin_mode,
)
from tests.support import reviewer as rv
from tests.support.api import build_app, client_for
from tests.support.builders import utc_now_naive

FUJIWA = uuid.UUID("2b1da87b-d0a8-46a6-b3c6-2132be0b5f4f")
SAMPLE_SHOP_NAME = "Dữ liệu mẫu"
SAMPLE_TITLE = "Hộp đựng gia vị Nhà Mây 6 ngăn"
CLEAN = PinShopFacts(platform="shopee", tiktok_linked=False, credential_rows=0)


@pytest.fixture(autouse=True)
def reviewer_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", rv.JWT_SECRET)
    monkeypatch.setenv("REVIEWER_ACCOUNT_CACHE_SECONDS", "0")
    monkeypatch.setenv("TIKTOK_APP_KEY", "app-key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "app-secret")
    monkeypatch.delenv("REVIEWER_SHOP_ID", raising=False)
    monkeypatch.delenv("REVIEWER_SHOP_IDS", raising=False)
    monkeypatch.delenv("REVIEWER_SAMPLE_SHOP_IDS", raising=False)
    rv.reset_caches()
    reviewer_sandbox.forget_sync_slots()
    yield
    rv.reset_caches()
    reviewer_sandbox.forget_sync_slots()


def _pin(monkeypatch, *shop_ids: uuid.UUID, sample: tuple[uuid.UUID, ...] = ()) -> None:
    monkeypatch.setenv("REVIEWER_SHOP_IDS", ",".join(str(s) for s in shop_ids))
    monkeypatch.setenv("REVIEWER_SAMPLE_SHOP_IDS", ",".join(str(s) for s in sample))


def _owner(shop_id: uuid.UUID) -> SandboxWriteOwner:
    return SandboxWriteOwner(shop_id, "sandbox-merchant", False)


def _decide(shop_id: uuid.UUID, facts: PinShopFacts | None = CLEAN, **kw: Any):
    return pin_mode(
        shop_id,
        sandbox_owner=kw.get("owner"),
        capabilities=kw.get("capabilities", set()),
        production_write_row=kw.get("production_write_row", False),
        shop=facts,
    )


# -- config ---------------------------------------------------------------------------------


def test_the_sample_list_is_parsed_like_the_pins_and_never_adds_a_pin(monkeypatch):
    pinned, unpinned = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setenv("REVIEWER_SHOP_IDS", f"{pinned}")
    monkeypatch.setenv("REVIEWER_SAMPLE_SHOP_IDS", f" {pinned} ,not-a-uuid,,{unpinned},{pinned}")
    assert reviewer_config.reviewer_sample_shop_ids() == frozenset({pinned})
    # The sample list never widens what the reviewer may enter.
    assert reviewer_config.reviewer_shop_ids() == (pinned,)
    monkeypatch.delenv("REVIEWER_SHOP_IDS")
    monkeypatch.setenv("REVIEWER_SHOP_ID", str(unpinned))
    assert reviewer_config.reviewer_sample_shop_ids() == frozenset({unpinned})
    monkeypatch.delenv("REVIEWER_SHOP_ID")
    assert reviewer_config.reviewer_sample_shop_ids() == frozenset()
    assert reviewer_config.reviewer_shop_ids() == ()


# -- the decision, branch by branch ----------------------------------------------------------


def test_happy_path_is_sample_with_the_mask_off_and_writes_off(monkeypatch):
    shop_id = uuid.uuid4()
    _pin(monkeypatch, shop_id, sample=(shop_id,))
    pin = _decide(shop_id, owner=_owner(uuid.uuid4()))
    assert pin.mode == MODE_SAMPLE
    assert pin.mask is False
    assert pin.sandbox is False
    assert pin.writes_enabled is False
    assert pin.writes_disabled_reason == REASON_SAMPLE_SHOP


def test_a_pin_not_on_the_sample_list_is_masked_as_before(monkeypatch):
    shop_id = uuid.uuid4()
    _pin(monkeypatch, shop_id)
    pin = _decide(shop_id)
    assert (pin.mode, pin.mask, pin.writes_enabled) == (MODE_MASKED, True, False)
    assert pin.writes_disabled_reason == reviewer_sandbox.REASON_NOT_SANDBOX


def test_a_sample_listed_id_that_is_not_pinned_is_not_sample(monkeypatch):
    shop_id, other = uuid.uuid4(), uuid.uuid4()
    _pin(monkeypatch, other, sample=(shop_id,))
    assert _decide(shop_id).mode == MODE_MASKED


@pytest.mark.parametrize(
    ("facts", "kw", "reason"),
    [
        (None, {}, REASON_SAMPLE_FACTS_MISSING),
        (
            PinShopFacts(platform="shopee", tiktok_linked=False, credential_rows=1),
            {},
            REASON_SAMPLE_TIKTOK_CREDENTIAL,
        ),
        (
            PinShopFacts(platform="shopee", tiktok_linked=False, credential_rows=1),
            {"capabilities": {TikTokCapability.SELLER_CONNECT.value}},
            REASON_SAMPLE_TIKTOK_CREDENTIAL,
        ),
        (CLEAN, {"production_write_row": True}, REASON_SAMPLE_PRODUCTION_WRITE),
        (CLEAN, {"owner": "self"}, REASON_SAMPLE_SANDBOX_OWNER),
        (
            PinShopFacts(platform="tiktok", tiktok_linked=False, credential_rows=0),
            {},
            REASON_SAMPLE_NOT_SHOPEE,
        ),
        (
            PinShopFacts(platform="shopee", tiktok_linked=True, credential_rows=0),
            {},
            REASON_SAMPLE_TIKTOK_LINKED,
        ),
    ],
    ids=["no-facts", "credential", "seller-connect", "pw-row", "sandbox-owner", "tiktok", "linked"],
)
def test_every_failing_check_is_masked_with_a_warning_naming_the_reason(
    monkeypatch, caplog, facts, kw, reason
):
    shop_id = uuid.uuid4()
    _pin(monkeypatch, shop_id, sample=(shop_id,))
    if kw.get("owner") == "self":
        kw = {**kw, "owner": _owner(shop_id)}
    with caplog.at_level(logging.WARNING, logger="juli_backend.services.reviewer.sandbox"):
        pin = _decide(shop_id, facts, **kw)
    assert (pin.mode, pin.mask, pin.writes_enabled) == (MODE_MASKED, True, False)
    assert pin.writes_disabled_reason == reason
    refused = [r for r in caplog.records if r.getMessage() == "reviewer_pin_sample_refused"]
    assert len(refused) == 1
    assert refused[0].levelno == logging.WARNING
    assert refused[0].__dict__["reason"] == reason
    assert refused[0].__dict__["shop_id"] == str(shop_id)


def test_the_sandbox_shop_listed_as_sample_loses_its_writes(monkeypatch):
    """Fail closed: a listed sandbox shop is neither sample nor live -- it is masked."""
    shop_id = uuid.uuid4()
    _pin(monkeypatch, shop_id, sample=(shop_id,))
    pin = _decide(
        shop_id,
        PinShopFacts(platform="tiktok", tiktok_linked=True, credential_rows=1),
        owner=_owner(shop_id),
        capabilities={TikTokCapability.SANDBOX_WRITE.value},
    )
    assert (pin.mode, pin.writes_enabled) == (MODE_MASKED, False)
    assert pin.writes_disabled_reason == REASON_SAMPLE_TIKTOK_CREDENTIAL


def test_fujiwa_is_refused_as_sample_whatever_the_env_says(monkeypatch, caplog):
    _pin(monkeypatch, FUJIWA, sample=(FUJIWA,))
    with caplog.at_level(logging.WARNING, logger="juli_backend.services.reviewer.sandbox"):
        pin = _decide(FUJIWA)
    assert (pin.mode, pin.mask, pin.writes_enabled) == (MODE_MASKED, True, False)
    assert pin.writes_disabled_reason == REASON_SAMPLE_REFUSED_SHOP
    assert any(r.__dict__.get("reason") == REASON_SAMPLE_REFUSED_SHOP for r in caplog.records)


# -- through the API --------------------------------------------------------------------------


async def _sample_shop(session) -> rv.ReferenceShop:
    """A Shopee shop as the S2-A loader leaves it: no TikTok linkage, an ingest token only."""
    ref = await rv.seed_reference_shop(
        session,
        name=SAMPLE_SHOP_NAME,
        tiktok_shop_id="unused",
        title=SAMPLE_TITLE,
        product_id="1740000000000000001",
        seller_sku="NM-GV-06",
    )
    ref.shop.platform = "shopee"
    ref.shop.tiktok_shop_id = None
    ref.shop.shopee_shop_id = "990000000001"
    session.add(
        IngestToken(
            id=uuid.uuid4(),
            shop_id=ref.shop.id,
            token_hash="0" * 64,
            platform="shopee",
            created_at=utc_now_naive(),
            expires_at=utc_now_naive() + timedelta(days=90),
        )
    )
    await session.flush()
    return ref


@pytest.fixture
async def world(session, monkeypatch):
    """Fujiwa-like masked pin first, the synthetic sample shop second, the sandbox third."""
    seller = await rv.seed_reference_shop(session)
    sample = await _sample_shop(session)
    sandbox = await rv.seed_reference_shop(
        session,
        name="Juli Sandbox VN",
        tiktok_shop_id="7600000000000000001",
        title="Sandbox áo thun",
        product_id="1730000000000000001",
        seller_sku="SBX-01",
    )
    for shop, capability, merchant in (
        (sandbox.shop, TikTokCapability.SANDBOX_WRITE, "sandbox-merchant"),
        (seller.shop, TikTokCapability.PRODUCTION_READ, "prod-merchant"),
    ):
        await TikTokCredentialRepo(session).create(
            shop.id,
            f"{merchant}-token",
            f"{merchant}-refresh",
            utc_now_naive() + timedelta(days=30),
            merchant_authorization_id=merchant,
            capability=capability.value,
            shop_cipher=f"cipher-{merchant}",
            scopes="seller.product.basic",
        )
    await session.commit()
    _pin(monkeypatch, seller.shop.id, sample.shop.id, sandbox.shop.id, sample=(sample.shop.id,))
    reviewer_id = await rv.make_reviewer(session)
    return seller, sample, sandbox, reviewer_id


def _headers(user_id, shop_id=None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {rv.token(user_id)}"}
    if shop_id is not None:
        headers["X-Shop-Id"] = str(shop_id)
    return headers


@pytest.fixture
def enqueued(monkeypatch) -> list[Any]:
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


async def test_me_exposes_the_sample_mode_unmasked_and_read_only(session, world):
    seller, sample, sandbox, reviewer_id = world
    async with client_for(build_app(session)) as client:
        me = await client.get("/v1/reviewer/me", headers=_headers(reviewer_id, sample.shop.id))
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["mode"] == "sample"
    assert body["writes_enabled"] is False
    assert body["shop"] == {"id": str(sample.shop.id), "name": SAMPLE_SHOP_NAME}
    modes = [(s["id"], s["mode"], s["writes_enabled"]) for s in body["shops"]]
    assert modes == [
        (str(shop_alias_id(seller.shop.id)), "masked", False),
        (str(sample.shop.id), "sample", False),
        (str(sandbox.shop.id), "sandbox", True),
    ]
    assert body["shops"][1]["name"] == SAMPLE_SHOP_NAME
    # The masked pin is still described only by its alias, even beside the sample one.
    for secret in rv.SECRETS:
        assert secret not in me.text


async def test_the_sample_pin_is_shown_unmasked(session, world):
    _seller, sample, _sandbox, reviewer_id = world
    async with client_for(build_app(session)) as client:
        listed = await client.get(
            "/v1/demo/decisions", headers=_headers(reviewer_id, sample.shop.id)
        )
    assert listed.status_code == 200, listed.text
    assert SAMPLE_TITLE in listed.text


async def test_the_sample_pin_also_takes_its_alias(session, world):
    _seller, sample, _sandbox, reviewer_id = world
    async with client_for(build_app(session)) as client:
        me = await client.get(
            "/v1/reviewer/me", headers=_headers(reviewer_id, shop_alias_id(sample.shop.id))
        )
    assert me.status_code == 200, me.text
    assert me.json()["mode"] == "sample"


async def test_simulated_execution_runs_on_the_sample_pin_and_writes_nothing(session, world):
    _seller, sample, _sandbox, reviewer_id = world
    card_id = sample.card.id
    async with client_for(build_app(session)) as client:
        results = [
            await client.post(
                f"/v1/reviewer/decisions/{sample.card.id}/simulate",
                json={"step": step},
                headers=_headers(reviewer_id, sample.shop.id),
            )
            for step in ("approve", "execute")
        ]
    for result in results:
        assert result.status_code == 200, result.text
        assert result.json()["simulated"] is True
    session.expire_all()
    card = (await session.execute(select(ActionCard).where(ActionCard.id == card_id))).scalar_one()
    assert card.status == "active"
    assert (await session.execute(select(WorkflowRun))).scalars().all() == []


async def test_every_write_and_sync_route_is_refused_on_the_sample_pin(session, world, enqueued):
    _seller, sample, _sandbox, reviewer_id = world
    card_id, run_id = sample.card.id, uuid.uuid4()
    routes: list[tuple[str, str, Any]] = [
        ("POST", f"/v1/demo/decisions/{card_id}/approve", None),
        ("POST", f"/v1/demo/runs/{run_id}/confirmations/call_1", {"decision": "approve"}),
        ("POST", f"/v1/demo/runs/{run_id}/revert", None),
        (
            "PUT",
            "/v1/demo/rules/stability_band",
            {"scope_ref": "ctr", "value": 12.5, "set_by": "seller"},
        ),
        ("POST", "/v1/reviewer/shop/sync", None),
        ("GET", "/v1/reviewer/shop", None),
    ]
    async with client_for(build_app(session)) as client:
        for method, url, payload in routes:
            response = await client.request(
                method, url, json=payload, headers=_headers(reviewer_id, sample.shop.id)
            )
            assert response.status_code == 403, (method, url, response.text)
            assert response.headers["x-juli-reviewer-denied"] == "sandbox_only", (method, url)
    assert enqueued == []
    session.expire_all()
    assert (await session.execute(select(WorkflowRun))).scalars().all() == []
    assert (await session.execute(select(ShopRule))).scalars().all() == []


async def test_a_tiktok_credential_turns_the_sample_pin_masked(session, world):
    _seller, sample, _sandbox, reviewer_id = world
    # A NULL-capability row still counts: any TikTok credential means a real platform shop.
    session.add(
        TikTokCredential(
            id=uuid.uuid4(),
            shop_id=sample.shop.id,
            access_token="x",
            refresh_token="y",
            token_expires_at=utc_now_naive() + timedelta(days=1),
            capability=None,
        )
    )
    await session.commit()
    async with client_for(build_app(session)) as client:
        me = await client.get(
            "/v1/reviewer/me", headers=_headers(reviewer_id, shop_alias_id(sample.shop.id))
        )
    assert me.status_code == 200, me.text
    assert me.json()["mode"] == "masked"
    assert SAMPLE_SHOP_NAME not in me.text


async def test_a_production_write_row_turns_the_sample_pin_masked(session, world):
    _seller, sample, _sandbox, reviewer_id = world
    session.add(ProductionWriteShop(shop_id=sample.shop.id, enabled_by="owner@app-juli.com"))
    await session.commit()
    async with client_for(build_app(session)) as client:
        me = await client.get(
            "/v1/reviewer/me", headers=_headers(reviewer_id, shop_alias_id(sample.shop.id))
        )
    assert me.status_code == 200, me.text
    assert me.json()["mode"] == "masked"


async def test_the_sample_classification_is_cached_for_the_identity_ttl(
    session, world, monkeypatch
):
    """P69: like every mode, ``sample`` is decided on a pin-cache miss and then kept."""
    from juli_backend.services.reviewer import pin_cache

    _seller, sample, _sandbox, reviewer_id = world
    sample_id = sample.shop.id
    monkeypatch.setenv("REVIEWER_ACCOUNT_CACHE_SECONDS", "30")
    calls: list[uuid.UUID] = []
    classify = reviewer_sandbox.classify_pin

    async def counting(session, shop_id):
        calls.append(shop_id)
        return await classify(session, shop_id)

    monkeypatch.setattr(reviewer_sandbox, "classify_pin", counting)
    async with client_for(build_app(session)) as client:
        first = await client.get("/v1/reviewer/me", headers=_headers(reviewer_id, sample_id))
        cached = pin_cache.cached(sample_id)
        assert cached is not None and cached.pin.mode == "sample"
        before = calls.count(sample_id)
        second = await client.get("/v1/reviewer/me", headers=_headers(reviewer_id, sample_id))
    assert first.json()["mode"] == second.json()["mode"] == "sample"
    assert calls.count(sample_id) == before  # the hit re-classified nothing


async def test_the_sample_shop_can_be_the_default_pin(session, world, monkeypatch):
    """Owner, 2026-11-11: prod pins the sample shop FIRST (the default) and the sandbox second."""
    seller, sample, sandbox, reviewer_id = world
    _pin(monkeypatch, sample.shop.id, sandbox.shop.id, sample=(sample.shop.id,))
    async with client_for(build_app(session)) as client:
        me = await client.get("/v1/reviewer/me", headers=_headers(reviewer_id))
        # The shell then sends the default pin's id (``me.shop.id``) as ``X-Shop-Id``.
        shops_me = await client.get(
            "/v1/shops/me", headers=_headers(reviewer_id, me.json()["shop"]["id"])
        )
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["mode"] == "sample"
    assert body["shop"] == {"id": str(sample.shop.id), "name": SAMPLE_SHOP_NAME}
    assert [s["mode"] for s in body["shops"]] == ["sample", "sandbox"]
    assert str(seller.shop.id) not in me.text
    # The shell picks its Shopee screens from ``/v1/shops/me`` ``platform``.
    assert shops_me.status_code == 200, shops_me.text
    assert shops_me.json()["platform"] == "shopee"


async def test_shopee_reads_are_admitted_on_the_sample_pin_only(session, world):
    """P100 S2-F: the reviewed sample-only list (``SAMPLE_SHOP_ENDPOINTS``) admits the Shopee
    screens' reads on the sample pin; the masked pin still gets 403 ``read_only``. The full
    proof (every route, no write, simulated Duyệt) is ``test_reviewer_sample_shopee.py``.
    """
    seller, sample, _sandbox, reviewer_id = world
    async with client_for(build_app(session)) as client:
        overview = await client.get(
            "/v1/demo/shopee/overview", headers=_headers(reviewer_id, sample.shop.id)
        )
        masked = await client.get(
            "/v1/demo/shopee/overview", headers=_headers(reviewer_id, shop_alias_id(seller.shop.id))
        )
        keywords = await client.get(
            "/v1/demo/shopee/keywords", headers=_headers(reviewer_id, sample.shop.id)
        )
    # This shop holds no Shopee numbers: the route answers itself (409), not the gate.
    assert "x-juli-reviewer-denied" not in overview.headers, overview.text
    assert masked.status_code == 403
    assert masked.headers["x-juli-reviewer-denied"] == "read_only"
    # ``GET /keywords`` commits: never on the list.
    assert keywords.status_code == 403
    assert keywords.headers["x-juli-reviewer-denied"] == "read_only"
