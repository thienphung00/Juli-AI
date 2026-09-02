"""The two capability resolvers never cross the production / sandbox boundary (#296, #1234).

``resolve_production_read_credential`` must return the production merchant's
credential and only that; ``resolve_sandbox_write_credential`` the sandbox
merchant's. Neither falls back to the other when its own is absent -- a
missing production credential is ``NotFound``, never "use the sandbox one".
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from juli_backend.core.security.credential_resolver import (
    resolve_production_read_credential,
    resolve_sandbox_write_credential,
)
from juli_backend.database.exceptions import NotFound
from juli_backend.integrations.tiktok import PRODUCTION_AUTH_ID, SANDBOX_AUTH_ID, TikTokCapability
from juli_backend.repositories import TikTokCredentialRepo
from tests.support.builders import utc_now_naive

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


@pytest.mark.parametrize(
    ("resolve", "own", "other"),
    [
        pytest.param(resolve_production_read_credential, PRODUCTION, SANDBOX, id="production-read"),
        pytest.param(resolve_sandbox_write_credential, SANDBOX, PRODUCTION, id="sandbox-write"),
    ],
)
class TestCapabilityResolvers:
    async def test_returns_only_its_own_merchants_credential(
        self, session, shop, resolve, own, other
    ):
        await issue_credential(session, shop, own, access_token="own-token")
        await issue_credential(session, shop, other, access_token="other-token")

        credential = await resolve(session)

        assert credential.access_token == "own-token"
        assert (credential.merchant_authorization_id, credential.capability) == (
            own[0],
            own[1].value,
        )

    async def test_never_falls_back_to_the_other_merchant(self, session, shop, resolve, own, other):
        await issue_credential(session, shop, other, access_token="other-only")

        with pytest.raises(NotFound):
            await resolve(session)
