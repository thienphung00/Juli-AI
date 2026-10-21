"""The two capability resolvers never cross the production / sandbox boundary (#296, #1234).

P61-G (D71.6): neither resolver knows a configured merchant id. The per-shop read resolver
returns the shop's OWN read-capable credential; ``resolve_sandbox_write_credential`` returns the
row whose capability is ``sandbox_write``. Neither falls back to the other when its own is
absent -- a missing production credential is ``NotFound``, never "use the sandbox one".
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from juli_backend.core.security.credential_resolver import (
    NoReadCredentialForShop,
    resolve_read_credential_for_shop,
    resolve_sandbox_write_credential,
)
from juli_backend.database.exceptions import NotFound
from juli_backend.integrations.tiktok import TikTokCapability
from juli_backend.repositories import TikTokCredentialRepo
from tests.support.builders import utc_now_naive

# Test merchant ids (P61-G, D71.6): nothing is configured; these are just row values.
PRODUCTION_AUTH_ID = "test-production-merchant"
SANDBOX_AUTH_ID = "test-sandbox-merchant"

PRODUCTION = (PRODUCTION_AUTH_ID, TikTokCapability.PRODUCTION_READ)
SANDBOX = (SANDBOX_AUTH_ID, TikTokCapability.SANDBOX_WRITE)


async def issue_credential(session, shop, merchant, *, access_token: str):
    merchant_id, capability = merchant
    return await TikTokCredentialRepo(session).create(
        shop.id,
        access_token,
        f"{access_token}-refresh",
        utc_now_naive() + timedelta(hours=1),
        merchant_authorization_id=merchant_id,
        capability=capability.value,
    )


async def _resolve_read(session, shop):
    return await resolve_read_credential_for_shop(session, shop.id)


@pytest.mark.parametrize(
    ("resolve", "own", "other", "missing"),
    [
        pytest.param(
            _resolve_read, PRODUCTION, SANDBOX, NoReadCredentialForShop, id="production-read"
        ),
        pytest.param(
            lambda session, shop: resolve_sandbox_write_credential(session),
            SANDBOX,
            PRODUCTION,
            NotFound,
            id="sandbox-write",
        ),
    ],
)
class TestCapabilityResolvers:
    async def test_returns_only_its_own_capabilitys_credential(
        self, session, shop, resolve, own, other, missing
    ):
        await issue_credential(session, shop, own, access_token="own-token")
        await issue_credential(session, shop, other, access_token="other-token")

        credential = await resolve(session, shop)

        assert credential.access_token == "own-token"
        assert (credential.merchant_authorization_id, credential.capability) == (
            own[0],
            own[1].value,
        )

    async def test_never_falls_back_to_the_other_capability(
        self, session, shop, resolve, own, other, missing
    ):
        await issue_credential(session, shop, other, access_token="other-only")

        with pytest.raises(missing):
            await resolve(session, shop)
