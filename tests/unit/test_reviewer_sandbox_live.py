"""P64 (D73, D73.2a) -- the partner reviewer on Juli's own TikTok Shop SANDBOX shop.

Owner decisions (grill 2026-10-21): the reviewer pinned to the sandbox shop sees it unmasked
and REALLY writes its listings -- only there, only through ``SandboxWriteClientFactory``
(three layers, each fail closed); and the sandbox credential may read / be polled for the one
shop its own row belongs to, never another (D73.2a).

Required tests, by the owner's letters:

- (a) ``test_a_reviewer_execute_on_a_seller_shop_pin_is_403_and_builds_no_write_client``
- (b) ``test_b_reviewer_execute_on_the_sandbox_pin_builds_exactly_one_sandbox_client``
- (c) ``test_c_a_production_pin_disables_reviewer_writes`` (+ the layer-2 refusals)
- (d) ``test_d_a_seller_session_cannot_reach_any_reviewer_sandbox_route``
- (e) ``test_e_sandbox_credential_serves_reads_for_its_own_shop``
- (f) ``test_f_sandbox_credential_is_refused_for_any_other_shop``
- (g) ``test_g_the_sandbox_shop_is_pollable``
- (h) ``test_h_a_production_shops_read_path_is_unchanged``

Real signed tokens through the real ``get_current_user`` (the gate lives there), SQLite.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select

from juli_backend.core.security.credential_resolver import (
    NoReadCredentialForShop,
    resolve_read_credential_for_shop,
)
from juli_backend.integrations.tiktok import (
    ClientFactoryConfig,
    ProductionReadClientFactory,
    ProductionWriteClientFactory,
    ReviewerProductionWriteRefused,
    SandboxWriteClientFactory,
    TikTokAPIError,
    TikTokCapability,
    reviewer_session,
)
from juli_backend.integrations.tiktok import client as tiktok_client
from juli_backend.integrations.tiktok import factories as tiktok_factories
from juli_backend.models.models import ProductionWriteShop
from juli_backend.models.ops import OpsAuditLog
from juli_backend.repositories import TikTokCredentialRepo
from juli_backend.services.reviewer import sandbox as reviewer_sandbox
from juli_backend.services.reviewer.config import shop_alias_id
from tests.support import reviewer as rv
from tests.support.api import build_app, client_for
from tests.support.builders import make_tenant, utc_now_naive

SANDBOX_MERCHANT = "sandbox-merchant-7001"
SANDBOX_SHOP_NAME = "Juli Sandbox VN"
FUJIWA_MERCHANT = "prod-merchant-9001"


@pytest.fixture(autouse=True)
def reviewer_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", rv.JWT_SECRET)
    monkeypatch.setenv("REVIEWER_ACCOUNT_CACHE_SECONDS", "0")
    monkeypatch.setenv("TIKTOK_APP_KEY", "app-key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "app-secret")
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
    """The sandbox shop (sandbox_write only), Fujiwa (production_read) and another seller."""
    sandbox = await rv.seed_reference_shop(
        session,
        name=SANDBOX_SHOP_NAME,
        tiktok_shop_id="7600000000000000001",
        title="Sandbox áo thun",
        product_id="1730000000000000001",
        seller_sku="SBX-01",
    )
    fujiwa = await rv.seed_reference_shop(session)
    seller = await rv.seed_reference_shop(
        session,
        name="Other Seller Shop",
        tiktok_shop_id="7494000000000000777",
        title="Áo thun nữ cotton Mộc Lan",
        product_id="1729000000000000777",
        seller_sku="ML-AO-01",
    )
    await _credential(
        session, sandbox.shop, TikTokCapability.SANDBOX_WRITE, SANDBOX_MERCHANT, "sbx-token"
    )
    await _credential(
        session, fujiwa.shop, TikTokCapability.PRODUCTION_READ, FUJIWA_MERCHANT, "fuji-token"
    )
    await _credential(
        session, seller.shop, TikTokCapability.SELLER_CONNECT, "seller-merchant-1", "sell-token"
    )
    await session.commit()
    monkeypatch.setenv("REVIEWER_SHOP_ID", str(sandbox.shop.id))
    reviewer_id = await rv.make_reviewer(session)
    return sandbox, fujiwa, seller, reviewer_id


def _headers(user_id, shop_id=None, **kw) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {rv.token(user_id, **kw)}"}
    if shop_id is not None:
        headers["X-Shop-Id"] = str(shop_id)
    return headers


class FakeProducts:
    """``ProductsResource`` double: the TikTok product, edited in place."""

    def __init__(self, *, refuse_code: int | None = None) -> None:
        self.detail: dict[str, Any] = {
            "id": "1730000000000000001",
            "title": "Sandbox áo thun",
            "description": "<p>cũ</p>",
            "category_chains": [{"id": "601", "is_leaf": True}],
            "main_images": [{"uri": "tos-old-1"}, {"uri": "tos-old-2"}],
            "skus": [{"id": "sku-1"}],
        }
        self.edits: list[dict[str, Any]] = []
        self.uploads = 0
        self.refuse_code = refuse_code

    def get_details(self, product_id: str) -> dict[str, Any]:
        if self.refuse_code is not None:
            raise TikTokAPIError(self.refuse_code, "product does not belong to this seller")
        return {**self.detail, "main_images": list(self.detail["main_images"])}

    def edit(self, *, product_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.edits.append(body)
        self.detail.update({k: body[k] for k in ("title", "description", "main_images")})
        return {"code": 0}

    def upload_product_image(self, *, image_bytes: bytes, filename: str, **_: Any) -> dict:
        self.uploads += 1
        return {"data": {"uri": "tos-new-cover"}}


class FactoryRecorder:
    """Records every write-factory build; production factories trip the test."""

    def __init__(self, monkeypatch, products: FakeProducts) -> None:
        self.sandbox_configs: list[ClientFactoryConfig] = []
        self.forbidden: list[str] = []
        recorder = self

        def sandbox_resources(_factory, config):
            recorder.sandbox_configs.append(config)
            return type("Resources", (), {"products": products})()

        def trip(name):
            def _raise(*args, **kwargs):
                recorder.forbidden.append(name)
                raise AssertionError(f"reviewer request built {name}")

            return _raise

        monkeypatch.setattr(SandboxWriteClientFactory, "create_resources", sandbox_resources)
        monkeypatch.setattr(ProductionWriteClientFactory, "create", trip("ProductionWrite"))
        monkeypatch.setattr(ProductionReadClientFactory, "create", trip("ProductionRead"))
        monkeypatch.setattr(tiktok_client.TikTokClient, "__init__", trip("TikTokClient"))


# -- (a) ------------------------------------------------------------------------------------


@pytest.mark.parametrize("pin", ["fujiwa", "seller"])
async def test_a_reviewer_execute_on_a_seller_shop_pin_is_403_and_builds_no_write_client(
    session, world, monkeypatch, pin
):
    sandbox, fujiwa, seller, reviewer_id = world
    target = fujiwa if pin == "fujiwa" else seller
    monkeypatch.setenv("REVIEWER_SHOP_ID", str(target.shop.id))
    products = FakeProducts()
    recorder = FactoryRecorder(monkeypatch, products)
    monkeypatch.setattr(
        SandboxWriteClientFactory,
        "__init__",
        lambda self: recorder.forbidden.append("Sandbox") or None,
    )
    alias = shop_alias_id(target.shop.id)
    async with client_for(build_app(session)) as client:
        for method, path, body in (
            ("POST", f"/v1/reviewer/decisions/{target.card.id}/execute", {"title": "Mới"}),
            ("POST", f"/v1/reviewer/decisions/{target.card.id}/approve", None),
            ("POST", "/v1/reviewer/shop/sync", None),
            ("GET", "/v1/reviewer/shop", None),
        ):
            response = await client.request(
                method, path, json=body, headers=_headers(reviewer_id, alias)
            )
            assert response.status_code == 403, (path, response.text)
            assert response.headers["x-juli-reviewer-denied"] == "sandbox_only"
        # Another shop's id is refused at the pin, before any route code.
        other = await client.post(
            f"/v1/reviewer/decisions/{sandbox.card.id}/execute",
            json={"title": "Mới"},
            headers=_headers(reviewer_id, sandbox.shop.id),
        )
        assert other.status_code == 403
    assert recorder.sandbox_configs == []
    assert recorder.forbidden == []
    assert products.edits == []


# -- (b) ------------------------------------------------------------------------------------


async def test_b_reviewer_execute_on_the_sandbox_pin_builds_exactly_one_sandbox_client(
    session, world, monkeypatch
):
    sandbox, _, _, reviewer_id = world
    products = FakeProducts()
    recorder = FactoryRecorder(monkeypatch, products)
    async with client_for(build_app(session)) as client:
        approve = await client.post(
            f"/v1/reviewer/decisions/{sandbox.card.id}/approve",
            headers=_headers(reviewer_id, sandbox.shop.id),
        )
        assert approve.status_code == 200, approve.text
        assert approve.json()["simulated"] is False
        assert approve.json()["executable"] is True
        assert recorder.sandbox_configs == []  # approve writes nothing
        response = await client.post(
            f"/v1/reviewer/decisions/{sandbox.card.id}/execute",
            json={"title": "Áo thun sandbox – tiêu đề mới"},
            headers=_headers(reviewer_id, sandbox.shop.id),
        )
    assert response.status_code == 200, response.text
    assert len(recorder.sandbox_configs) == 1
    config = recorder.sandbox_configs[0]
    assert config.merchant_auth_id == SANDBOX_MERCHANT
    assert config.credential_capability == TikTokCapability.SANDBOX_WRITE.value
    assert config.access_token == "sbx-token"
    assert recorder.forbidden == []
    assert products.edits[0]["title"] == "Áo thun sandbox – tiêu đề mới"
    body = response.json()
    assert body["tiktok_write"] is True and body["simulated"] is False
    assert body["read_back"]["fields"] == [
        {
            "field": "title",
            "before": "Sandbox áo thun",
            "after": "Áo thun sandbox – tiêu đề mới",
            "after_source": "read_back",
        }
    ]
    assert body["read_back"]["listing"]["title"] == "Áo thun sandbox – tiêu đề mới"
    assert body["read_back"]["confirmed_at"].endswith("Z")
    # Unmasked (D73 Q1/Q2): the card's real TikTok product id, not a ``demo-…`` alias.
    assert body["tiktok_product_id"] == rv.TIKTOK_PRODUCT_ID
    actions = [row.action for row in (await session.execute(select(OpsAuditLog))).scalars().all()]
    assert "reviewer_sandbox_approve" in actions and "reviewer_sandbox_execute" in actions


async def test_b_cover_image_is_uploaded_then_attached(session, world, monkeypatch):
    sandbox, _, _, reviewer_id = world
    products = FakeProducts()
    recorder = FactoryRecorder(monkeypatch, products)
    monkeypatch.setattr(
        "juli_backend.services.agent.tools.product_write.screen_and_reencode_image",
        lambda data: (data, "safe.png"),
    )
    import base64

    async with client_for(build_app(session)) as client:
        response = await client.post(
            f"/v1/reviewer/decisions/{sandbox.card.id}/execute",
            json={"image_base64": base64.b64encode(b"\x89PNG fake").decode()},
            headers=_headers(reviewer_id, sandbox.shop.id),
        )
    assert response.status_code == 200, response.text
    assert products.uploads == 1
    assert products.edits[0]["main_images"] == [
        {"uri": "tos-new-cover"},
        {"uri": "tos-old-2"},
    ]
    assert response.json()["operations"] == ["upload_product_image", "update_product_listing"]
    assert len(recorder.sandbox_configs) == 1


async def test_b_tiktok_12052048_is_a_clear_409_never_a_success(session, world, monkeypatch):
    sandbox, _, _, reviewer_id = world
    products = FakeProducts(refuse_code=12052048)
    FactoryRecorder(monkeypatch, products)
    async with client_for(build_app(session)) as client:
        response = await client.post(
            f"/v1/reviewer/decisions/{sandbox.card.id}/execute",
            json={"title": "Mới"},
            headers=_headers(reviewer_id, sandbox.shop.id),
        )
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "product_not_owned_by_sandbox_seller",
        "tiktok_code": 12052048,
    }
    assert products.edits == []


async def test_b_sandbox_pin_is_unmasked_and_the_simulation_is_retired(session, world):
    sandbox, _, _, reviewer_id = world
    async with client_for(build_app(session)) as client:
        me = await client.get("/v1/reviewer/me", headers=_headers(reviewer_id))
        shop = await client.get("/v1/reviewer/shop", headers=_headers(reviewer_id, sandbox.shop.id))
        simulate = await client.post(
            f"/v1/reviewer/decisions/{sandbox.card.id}/simulate",
            json={"step": "execute"},
            headers=_headers(reviewer_id, sandbox.shop.id),
        )
    assert me.status_code == 200
    assert me.json()["shop"] == {"id": str(sandbox.shop.id), "name": SANDBOX_SHOP_NAME}
    assert me.json()["mode"] == "sandbox" and me.json()["writes_enabled"] is True
    assert shop.status_code == 200, shop.text
    info = shop.json()
    assert info["shop"]["tiktok_shop_id"] == "7600000000000000001"
    assert info["connection"]["capability"] == "sandbox_write"
    assert info["connection"]["scopes"] == ["seller.product.basic", "seller.order.info"]
    assert "sbx-token" not in shop.text and SANDBOX_MERCHANT not in shop.text
    assert simulate.status_code == 403
    assert simulate.headers["x-juli-reviewer-denied"] == "sandbox_live"


async def test_b_sync_now_enqueues_poll_shop_once_per_minute(session, world, monkeypatch):
    sandbox, _, _, reviewer_id = world
    queued: list[uuid.UUID] = []
    monkeypatch.setattr(
        "juli_backend.api.routes.reviewer._enqueue_poll_shop",
        lambda shop_id: queued.append(shop_id) or "task-1",
    )
    async with client_for(build_app(session)) as client:
        first = await client.post(
            "/v1/reviewer/shop/sync", headers=_headers(reviewer_id, sandbox.shop.id)
        )
        second = await client.post(
            "/v1/reviewer/shop/sync", headers=_headers(reviewer_id, sandbox.shop.id)
        )
    assert first.status_code == 202, first.text
    assert first.json()["queued"] is True
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "sync_rate_limited"
    assert 1 <= int(second.headers["retry-after"]) <= 60
    assert queued == [sandbox.shop.id]


# -- (c) ------------------------------------------------------------------------------------


@pytest.mark.parametrize("production", ["production_read", "production_write_row"])
async def test_c_a_production_pin_disables_reviewer_writes(
    session, world, monkeypatch, caplog, production
):
    sandbox, _, _, reviewer_id = world
    if production == "production_read":
        await _credential(
            session, sandbox.shop, TikTokCapability.PRODUCTION_READ, "prod-x", "prod-token"
        )
    else:
        session.add(ProductionWriteShop(shop_id=sandbox.shop.id, enabled_by="owner"))
    await session.commit()
    products = FakeProducts()
    recorder = FactoryRecorder(monkeypatch, products)
    alias = shop_alias_id(sandbox.shop.id)
    with caplog.at_level(logging.ERROR):
        async with client_for(build_app(session)) as client:
            me = await client.get("/v1/reviewer/me", headers=_headers(reviewer_id))
            response = await client.post(
                f"/v1/reviewer/decisions/{sandbox.card.id}/execute",
                json={"title": "Mới"},
                headers=_headers(reviewer_id, alias),
            )
    assert me.json()["mode"] == "masked" and me.json()["writes_enabled"] is False
    assert SANDBOX_SHOP_NAME not in me.text  # masked again
    assert response.status_code == 403
    assert response.headers["x-juli-reviewer-denied"] == "sandbox_only"
    assert "reviewer_pin_production_shop" in caplog.text
    assert recorder.sandbox_configs == [] and products.edits == []


def test_c_production_write_factory_refuses_inside_a_reviewer_request():
    config = ClientFactoryConfig(
        app_key="k",
        app_secret="s",
        access_token="t",
        merchant_auth_id=FUJIWA_MERCHANT,
        credential_capability=TikTokCapability.PRODUCTION_READ.value,
    )
    with reviewer_session(), pytest.raises(ReviewerProductionWriteRefused):
        ProductionWriteClientFactory().create(config)


async def test_c_production_write_resolver_refuses_a_reviewer_request(session, world, monkeypatch):
    from juli_backend.services.execution.production_write import (
        load_production_write_resources,
    )
    from juli_backend.services.execution.production_write_resolver import (
        PreconditionFailure,
        PreconditionName,
        resolve_write_capability,
    )

    _, fujiwa, _, _ = world
    session.add(ProductionWriteShop(shop_id=fujiwa.shop.id, enabled_by="owner"))
    await session.commit()
    monkeypatch.setenv("PRODUCTION_WRITE_ENABLED", "true")
    monkeypatch.setattr(
        "juli_backend.services.execution.production_write_resolver.is_production_write_enabled",
        lambda: True,
    )
    with reviewer_session():
        with pytest.raises(PreconditionFailure) as refused:
            await resolve_write_capability(
                session,
                tool_name="update_product_listing",
                payload={"tiktok_product_id": rv.TIKTOK_PRODUCT_ID},
                shop_id=fujiwa.shop.id,
            )
        assert refused.value.precondition is PreconditionName.REVIEWER_SESSION
        with pytest.raises(ReviewerProductionWriteRefused):
            await load_production_write_resources(
                session,
                shop_id=fujiwa.shop.id,
                capability={"capability": "production_write", "shop_id": str(fujiwa.shop.id)},
                app_key="k",
                app_secret="s",
            )


async def test_c_reviewer_write_resources_refuse_outside_a_reviewer_request(session, world):
    sandbox, _, _, _ = world
    with pytest.raises(reviewer_sandbox.ReviewerWriteRefused):
        await reviewer_sandbox.load_reviewer_write_resources(
            session, shop_id=sandbox.shop.id, app_key="k", app_secret="s"
        )


# -- (d) ------------------------------------------------------------------------------------


async def test_d_a_seller_session_cannot_reach_any_reviewer_sandbox_route(
    session, world, monkeypatch
):
    sandbox, _, _, _ = world
    products = FakeProducts()
    recorder = FactoryRecorder(monkeypatch, products)
    queued: list[Any] = []
    monkeypatch.setattr(
        "juli_backend.api.routes.reviewer._enqueue_poll_shop",
        lambda shop_id: queued.append(shop_id) or "task",
    )
    # The sandbox shop's own owner, a plain seller token (no reviewer mark).
    owner = sandbox.owner.id
    async with client_for(build_app(session)) as client:
        for method, path, body in (
            ("POST", f"/v1/reviewer/decisions/{sandbox.card.id}/execute", {"title": "Mới"}),
            ("POST", f"/v1/reviewer/decisions/{sandbox.card.id}/approve", None),
            ("POST", "/v1/reviewer/shop/sync", None),
            ("GET", "/v1/reviewer/shop", None),
        ):
            response = await client.request(
                method,
                path,
                json=body,
                headers=_headers(owner, sandbox.shop.id, platform=None, email="o@gmail.com"),
            )
            assert response.status_code == 403, (path, response.text)
    assert recorder.sandbox_configs == [] and recorder.forbidden == []
    assert queued == [] and products.edits == []


# -- (e)-(h): the sandbox credential's own-shop read exception (D73.2a) ----------------------


async def test_e_sandbox_credential_serves_reads_for_its_own_shop(session, world):
    sandbox, _, _, _ = world
    credential = await resolve_read_credential_for_shop(session, sandbox.shop.id)
    assert credential.shop_id == sandbox.shop.id
    assert credential.capability == TikTokCapability.SANDBOX_WRITE.value
    assert credential.merchant_authorization_id == SANDBOX_MERCHANT
    # The read client: ReadOnlyTransportGuard, admitted only with the own-shop flag.
    config = ClientFactoryConfig(
        app_key="k",
        app_secret="s",
        access_token=credential.access_token,
        merchant_auth_id=SANDBOX_MERCHANT,
        credential_capability=credential.capability,
        own_shop_sandbox_read=True,
    )
    client = ProductionReadClientFactory().create(config)
    assert type(client._guard).__name__ == "ReadOnlyTransportGuard"
    from juli_backend.workers.services.polling.orchestrate import (
        _assert_pollable_read_credential,
        _factory_config,
    )

    _assert_pollable_read_credential(credential, shop_id=sandbox.shop.id)
    poll_config = type("Cfg", (), {"app_key": "k", "app_secret": "s"})()
    assert _factory_config(poll_config, credential, shop_id=sandbox.shop.id).own_shop_sandbox_read


async def test_f_sandbox_credential_is_refused_for_any_other_shop(session, world):
    sandbox, fujiwa, _, _ = world
    _, empty_shop = await make_tenant(session)
    await session.commit()
    with pytest.raises(NoReadCredentialForShop):
        await resolve_read_credential_for_shop(session, empty_shop.id)
    # A shop holding an OLDER sandbox_write row is not the sandbox shop: refused too.
    stale = await rv.seed_reference_shop(
        session,
        name="Stale",
        tiktok_shop_id="7600000000000000099",
        product_id="1730000000000000099",
    )
    stale_row = await _credential(
        session, stale.shop, TikTokCapability.SANDBOX_WRITE, "stale-merchant", "stale-token"
    )
    stale_row.created_at = utc_now_naive() - timedelta(days=30)
    await session.commit()
    with pytest.raises(NoReadCredentialForShop):
        await resolve_read_credential_for_shop(session, stale.shop.id)
    # The sandbox credential presented for Fujiwa's poll is refused by the ownership check.
    sandbox_row = await resolve_read_credential_for_shop(session, sandbox.shop.id)
    from juli_backend.workers.services.polling.orchestrate import _assert_pollable_read_credential

    with pytest.raises(ValueError):
        _assert_pollable_read_credential(sandbox_row, shop_id=fujiwa.shop.id)
    # And the read factory refuses it without the caller's own-shop proof.
    with pytest.raises(ValueError):
        ProductionReadClientFactory().create(
            ClientFactoryConfig(
                app_key="k",
                app_secret="s",
                access_token="t",
                merchant_auth_id=SANDBOX_MERCHANT,
                credential_capability=TikTokCapability.SANDBOX_WRITE.value,
            )
        )
    from juli_backend.integrations.tiktok import is_own_shop_read_capability

    assert not is_own_shop_read_capability(
        "sandbox_write", credential_shop_id=sandbox.shop.id, shop_id=fujiwa.shop.id
    )


async def test_g_the_sandbox_shop_is_pollable(session, world):
    from juli_backend.workers.services.polling.ingestion import enumerate_pollable_shops

    sandbox, fujiwa, seller, _ = world
    pollable = {shop.shop_id for shop in await enumerate_pollable_shops(session)}
    assert pollable == {sandbox.shop.id, fujiwa.shop.id, seller.shop.id}


async def test_h_a_production_shops_read_path_is_unchanged(session, world):
    from juli_backend.workers.services.polling.orchestrate import _factory_config

    sandbox, fujiwa, _, _ = world
    credential = await resolve_read_credential_for_shop(session, fujiwa.shop.id)
    assert credential.capability == TikTokCapability.PRODUCTION_READ.value
    assert credential.merchant_authorization_id == FUJIWA_MERCHANT
    poll_config = type("Cfg", (), {"app_key": "k", "app_secret": "s"})()
    config = _factory_config(poll_config, credential, shop_id=fujiwa.shop.id)
    assert config.own_shop_sandbox_read is False
    # A shop holding a read credential keeps it even beside the sandbox exception; a
    # shop with no sandbox pin is masked and read-only as in P32.
    with pytest.raises(ValueError):
        tiktok_factories.ProductionReadClientFactory().create(
            ClientFactoryConfig(
                app_key="k",
                app_secret="s",
                access_token="t",
                merchant_auth_id=SANDBOX_MERCHANT,
                credential_capability=TikTokCapability.SANDBOX_WRITE.value,
                own_shop_sandbox_read=False,
            )
        )
    assert sandbox.shop.id != fujiwa.shop.id
