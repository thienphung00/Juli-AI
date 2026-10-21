"""Two-shop proof, on real Postgres as `juli_app`, that the agent's
`get_shop_identity` tool calls Get Authorized Shops with the run shop's OWN
read credential and answers with that shop's identity only (fast track P63).

Two seeded shops each hold their own read credential (A `production_read`,
B `seller_connect`). The read factory is replaced by one that builds the real
`AuthorizationResource` over a fake TikTok transport: the transport answers
`/authorization/.../shops` from the token it was signed with, and records every
request. Nothing reaches TikTok.

- shop B's tool call carries B's token and returns B's name, never A's;
- shop A's likewise from the same database;
- the output carries no id, cipher or token;
- a token that reaches another shop than the run's shop is a refusal-style
  result (`mismatch`), not an exception, with no other-shop details.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from tests.integration.two_tenant import RUNTIME_ROLE

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]


@asynccontextmanager
async def juli_app_session():
    """A `juli_app` session with no tenant scope (the code under test sets it)."""
    from juli_backend.core.config.runtime import async_database_url

    engine = create_async_engine(async_database_url(os.environ["DATABASE_URL"]))
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
            await conn.commit()
            session = AsyncSession(bind=conn, expire_on_commit=False)
            try:
                yield session
            finally:
                await session.rollback()
                await session.close()
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def shops(owner_engine, two_tenants):
    """Each tenant gets its own read credential, cipher and (fake) TikTok shop."""
    tenant_a, tenant_b = two_tenants
    expected: dict[Any, dict[str, str]] = {}
    with owner_engine.begin() as conn:
        for tenant, label, capability in (
            (tenant_a, "a", "production_read"),
            (tenant_b, "b", "seller_connect"),
        ):
            merchant = f"identity-merchant-{label}-{tenant.shop_id.hex[:6]}"
            cipher = f"identity-cipher-{label}"
            conn.execute(
                text(
                    "UPDATE public.tiktok_credentials "
                    "SET capability = :capability, merchant_authorization_id = :merchant, "
                    "    shop_cipher = :cipher "
                    "WHERE id = :id"
                ),
                {
                    "capability": capability,
                    "merchant": merchant,
                    "cipher": cipher,
                    "id": str(tenant.fresh_credential_id),
                },
            )
            token = conn.execute(
                text("SELECT access_token FROM public.tiktok_credentials WHERE id = :id"),
                {"id": str(tenant.fresh_credential_id)},
            ).scalar_one()
            expected[tenant.shop_id] = {
                "token": token,
                "cipher": cipher,
                "name": f"Shop {label.upper()} Official",
                "tiktok_id": f"77000000000000{label}",
            }
    return tenant_a.shop_id, tenant_b.shop_id, expected


@pytest.fixture
def transport(monkeypatch, shops) -> list[dict[str, Any]]:
    """Replace the read factory with the real `AuthorizationResource` over a fake
    transport; returns the list of requests the transport saw."""
    from juli_backend.integrations.tiktok import AuthorizationResource, ProductionReadResources
    from juli_backend.integrations.tiktok.client import TikTokClient
    from juli_backend.services.agent import composition

    _a, _b, expected = shops
    by_token = {entry["token"]: entry for entry in expected.values()}
    requests: list[dict[str, Any]] = []

    class _FakeTransportClient(TikTokClient):
        def get(self, path, params=None, *, response_model=None):
            entry = by_token[self._access_token]
            requests.append(
                {"path": path, "token": self._access_token, "cipher": self._shop_cipher}
            )
            return {
                "shops": [
                    {
                        "id": entry["tiktok_id"],
                        "cipher": entry["cipher"],
                        "name": entry["name"],
                        "region": "VN",
                        "seller_type": "LOCAL",
                    }
                ]
            }

    class _Factory:
        def create_resources(self, config):
            client = _FakeTransportClient(
                app_key=config.app_key,
                app_secret=config.app_secret,
                access_token=config.access_token,
                shop_cipher=config.shop_cipher,
            )
            return ProductionReadResources(
                authorization=AuthorizationResource(client),
                orders=None,
                products=None,
                returns=None,
                inventory=None,
                analytics=None,
                promotion=None,
            )

    monkeypatch.setenv("TIKTOK_APP_KEY", "test-app-key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "test-app-secret")
    monkeypatch.setattr(composition, "ProductionReadClientFactory", _Factory)
    return requests


def _executor(read_resources):
    from juli_backend.services.agent import composition
    from juli_backend.services.agent.runner import ProductToolExecutor

    return ProductToolExecutor(
        registry=composition.build_product_tool_registry(),
        product_id="product-of-this-run",
        read_resources=read_resources,
    )


def _call(read_resources) -> dict[str, Any]:
    from juli_backend.services.agent.tools.product import GetShopIdentityInput

    return dict(
        _executor(read_resources).execute(
            tool_name="get_shop_identity", params=GetShopIdentityInput()
        )
    )


@pytest.mark.asyncio
async def test_shop_b_tool_call_uses_b_credential_and_returns_b_identity_only(shops, transport):
    from juli_backend.services.agent.composition import build_read_resources

    shop_a, shop_b, expected = shops

    async with juli_app_session() as session:
        resources = await build_read_resources(session, shop_b)
    result = _call(resources)

    assert [(r["token"], r["cipher"]) for r in transport] == [
        (expected[shop_b]["token"], expected[shop_b]["cipher"])
    ]
    assert result["status"] == "verified"
    assert result["shop_matches"] is True
    dumped = json.dumps(result, ensure_ascii=False)
    assert expected[shop_b]["name"] in dumped
    assert expected[shop_a]["name"] not in dumped
    for secret in (
        expected[shop_a]["token"],
        expected[shop_b]["token"],
        expected[shop_a]["cipher"],
        expected[shop_b]["cipher"],
        expected[shop_a]["tiktok_id"],
        expected[shop_b]["tiktok_id"],
    ):
        assert secret not in dumped


@pytest.mark.asyncio
async def test_shop_a_tool_call_uses_a_credential_and_returns_a_identity_only(shops, transport):
    from juli_backend.services.agent.composition import build_read_resources

    shop_a, shop_b, expected = shops

    async with juli_app_session() as session:
        resources = await build_read_resources(session, shop_a)
    result = _call(resources)

    assert [r["token"] for r in transport] == [expected[shop_a]["token"]]
    dumped = json.dumps(result, ensure_ascii=False)
    assert result["status"] == "verified"
    assert expected[shop_a]["name"] in dumped
    assert expected[shop_b]["name"] not in dumped


@pytest.mark.asyncio
async def test_token_reaching_another_shop_is_a_refusal_result_not_an_exception(
    shops, transport, caplog
):
    """Shop B's run holds B's cipher but the token answers for shop A."""
    from juli_backend.integrations.tiktok import AuthorizationResource
    from juli_backend.integrations.tiktok.client import TikTokClient
    from juli_backend.services.agent.composition import build_read_resources

    shop_a, shop_b, expected = shops

    async with juli_app_session() as session:
        resources = await build_read_resources(session, shop_b)

    # Swap in a client that holds B's cipher but A's token (a credential that was
    # re-pointed at another shop after it was stored).
    crossed = type(resources.authorization._client)(
        app_key="k",
        app_secret="s",
        access_token=expected[shop_a]["token"],
        shop_cipher=expected[shop_b]["cipher"],
    )
    assert isinstance(crossed, TikTokClient)
    object.__setattr__(resources, "authorization", AuthorizationResource(crossed))

    with caplog.at_level("WARNING"):
        result = _call(resources)

    assert result["status"] == "mismatch"
    assert result["shop_matches"] is False
    dumped = json.dumps(result, ensure_ascii=False)
    assert expected[shop_a]["name"] not in dumped
    assert expected[shop_a]["cipher"] not in dumped
    assert any(r.getMessage() == "agent_shop_identity_mismatch" for r in caplog.records)
