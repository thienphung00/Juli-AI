"""P16 D25.15: scopes are persisted on refresh too, and the shop's permission status
(complete / missing / unknown) reaches Ops and the seller."""

from __future__ import annotations

import pytest

from juli_backend.core.security.credential_refresh import granted_scopes_of
from juli_backend.repositories.repos import TikTokCredentialRepo
from juli_backend.repositories.tiktok_credentials import parse_granted_scopes
from juli_backend.services.ops import scopes
from tests.support.api import authenticated_client
from tests.support.builders import make_credential, make_tenant, utc_now_naive

ALL = ",".join(scopes.DEFAULT_REQUIRED_SCOPES)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"granted_scopes": ["a", " b ", ""]}, "a,b"),
        ({"scopes": "a,b"}, "a,b"),
        ({}, None),
    ],
)
def test_granted_scopes_of_a_token_response(payload, expected):
    assert granted_scopes_of(payload) == expected


async def test_mark_refreshed_writes_scopes_only_when_given(session):
    _, shop = await make_tenant(session)
    cred = await make_credential(session, shop, scopes="old.scope")
    repo = TikTokCredentialRepo(session)
    later = utc_now_naive()
    await repo.mark_refreshed(cred.id, "a", "r", later)
    assert parse_granted_scopes(cred.scopes) == {"old.scope"}
    await repo.mark_refreshed(cred.id, "a", "r", later, scopes="seller.order.info,x")
    assert parse_granted_scopes(cred.scopes) == {"seller.order.info", "x"}


def test_status_of():
    assert scopes.status_of(ALL).status == scopes.COMPLETE
    missing = scopes.status_of("seller.order.info")
    assert missing.status == scopes.MISSING and "seller.finance.info" in missing.missing
    assert scopes.status_of(None).status == scopes.UNKNOWN
    assert scopes.status_of(None, connected=False).status == scopes.NOT_CONNECTED


def test_required_scopes_can_be_set_by_env(monkeypatch):
    monkeypatch.setenv("TIKTOK_REQUIRED_SCOPES", "seller.order.info, z.scope")
    assert list(scopes.required_scopes()) == ["seller.order.info", "z.scope"]


async def test_the_seller_endpoint_tells_when_to_reconnect(session):
    owner, shop = await make_tenant(session)
    await make_credential(session, shop, scopes="seller.order.info", status="active")
    async with authenticated_client(session, user=owner, shop=shop) as client:
        body = (await client.get("/v1/shops/me/permissions")).json()["data"]
    assert body["status"] == "missing" and body["needs_reconnect"] is True
    assert {"scope": "seller.finance.info", "used_for": "giao dịch tài chính theo đơn"} in body[
        "missing"
    ]
