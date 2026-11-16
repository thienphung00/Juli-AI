"""P101 W2a (contract §2.1, §2.4, §6): one TikTok grant attaches every shop it authorises,
``shops.kind`` follows the credential capability, and a missing scope is a ``needs_reauth``
connection state.

SQLite twins: no RLS, no ``shops_default_business`` trigger. The tenant-scoped behaviour on
PostgreSQL is unchanged from P61-I (each shop is written under the owner's user scope, each
credential under its own shop scope).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from juli_backend.core.security import (
    MultiShopBindingVerifier,
    ShopClaimedByAnotherAccount,
    VerifiedShopCipher,
)
from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.integrations.tiktok import TikTokAuth, TikTokCapability
from juli_backend.models.businesses import Business
from juli_backend.models.models import Shop, TikTokCredential
from juli_backend.services.ops import scopes
from juli_backend.services.tiktok import credential_binding
from juli_backend.services.tiktok.credential_binding import (
    CredentialBindingError,
    make_binding_verifier,
)
from tests.support.api import authenticated_client
from tests.support.builders import make_credential, make_shop, make_tenant, make_user

OPEN_ID = "merchant-open-id-w2a"
GRANT = [
    {"id": "7400000000000000001", "cipher": "ROW_w2a_cipher_a", "name": "Shop A"},
    {"id": "7400000000000000002", "cipher": "ROW_w2a_cipher_b", "name": "Shop B"},
]


def _token(open_id: str = OPEN_ID) -> dict:
    return {
        "open_id": open_id,
        "access_token": "w2a-access",
        "refresh_token": "w2a-refresh",
        "access_token_expire_in": 604800,
        "seller_name": "W2a Seller",
    }


def _service(session, verifier) -> TikTokOAuthService:
    return TikTokOAuthService(
        tiktok_auth=TikTokAuth(app_key="k", app_secret="s", base_url="https://example.test"),
        session=session,
        redirect_uri="https://example.test/cb",
        app_secret="s",
        binding_verifier=verifier,
    )


def _real_verifier(monkeypatch, grant: list[dict]) -> MultiShopBindingVerifier:
    monkeypatch.setattr(credential_binding, "resolve_authorized_shops", lambda **_kw: list(grant))
    return make_binding_verifier(app_key="k", app_secret="s")


async def _credentials(session, shop_id) -> list[TikTokCredential]:
    rows = await session.execute(
        select(TikTokCredential).where(TikTokCredential.shop_id == shop_id)
    )
    return list(rows.scalars().all())


# ---------------------------------------------------------------------------
# 1. Several shops in one grant
# ---------------------------------------------------------------------------


async def test_the_production_verifier_lists_every_shop_of_the_grant(monkeypatch):
    verifier = _real_verifier(monkeypatch, GRANT)

    shops = await verifier.authorized_shops(access_token="t")

    assert isinstance(verifier, MultiShopBindingVerifier)
    assert [str(s) for s in shops] == ["ROW_w2a_cipher_a", "ROW_w2a_cipher_b"]
    assert [s.tiktok_shop_id for s in shops] == [g["id"] for g in GRANT]
    assert [s.shop_name for s in shops] == ["Shop A", "Shop B"]


async def test_one_grant_attaches_every_authorised_shop(session, monkeypatch):
    user = await make_user(session)

    shops = await _service(
        session, _real_verifier(monkeypatch, GRANT)
    ).provision_shops_and_credentials(_token(), user_id=user.id)

    assert len(shops) == 2
    assert [s.shop_name for s in shops] == ["Shop A", "Shop B"]
    assert [s.tiktok_numeric_shop_id for s in shops] == [g["id"] for g in GRANT]
    assert len({s.tiktok_shop_id for s in shops}) == 2
    assert all(s.user_id == user.id and s.kind == "real" for s in shops)
    for shop, grant in zip(shops, GRANT, strict=True):
        creds = await _credentials(session, shop.id)
        assert [(c.shop_cipher, c.merchant_authorization_id, c.capability) for c in creds] == [
            (grant["cipher"], OPEN_ID, TikTokCapability.SELLER_CONNECT.value)
        ]


async def test_every_new_shop_joins_the_selected_business(session, monkeypatch):
    user, existing = await make_tenant(session)
    business = Business(name="Biz W2a")
    session.add(business)
    await session.flush()

    shops = await _service(
        session, _real_verifier(monkeypatch, GRANT)
    ).provision_shops_and_credentials(_token(), user_id=user.id, business_id=business.id)

    assert [s.business_id for s in shops] == [business.id, business.id]
    assert existing.id not in {s.id for s in shops}


async def test_a_reconnect_refreshes_each_shop_in_place(session, monkeypatch):
    user = await make_user(session)
    service = _service(session, _real_verifier(monkeypatch, GRANT))
    first = await service.provision_shops_and_credentials(_token(), user_id=user.id)

    again = await service.provision_shops_and_credentials(_token(), user_id=user.id)

    assert [s.id for s in again] == [s.id for s in first]
    for shop in again:
        assert len(await _credentials(session, shop.id)) == 1


async def test_a_single_shop_seller_who_adds_a_shop_keeps_the_first_row(session, monkeypatch):
    user = await make_user(session)
    (only,) = await _service(
        session, _real_verifier(monkeypatch, GRANT[:1])
    ).provision_shops_and_credentials(_token(), user_id=user.id)
    assert only.tiktok_shop_id == OPEN_ID

    both = await _service(
        session, _real_verifier(monkeypatch, GRANT)
    ).provision_shops_and_credentials(_token(), user_id=user.id)

    assert both[0].id == only.id
    assert both[1].tiktok_shop_id == f"{OPEN_ID}:{GRANT[1]['id']}"


async def test_a_pre_p68_row_is_reclaimed_only_by_the_shop_whose_cipher_it_holds(
    session, monkeypatch
):
    user = await make_user(session)
    legacy = await make_shop(session, user, tiktok_shop_id=OPEN_ID, tiktok_numeric_shop_id=None)
    await make_credential(
        session,
        legacy,
        merchant_authorization_id=OPEN_ID,
        capability=TikTokCapability.SELLER_CONNECT.value,
        shop_cipher=GRANT[1]["cipher"],
    )

    shops = await _service(
        session, _real_verifier(monkeypatch, GRANT)
    ).provision_shops_and_credentials(_token(), user_id=user.id)

    assert shops[1].id == legacy.id
    assert shops[0].id != legacy.id
    assert legacy.tiktok_numeric_shop_id == GRANT[1]["id"]


async def test_a_shop_claimed_by_another_account_stays_refused_and_the_rest_attach(
    session, monkeypatch
):
    other = await make_user(session)
    claimed = await make_shop(session, other, tiktok_numeric_shop_id=GRANT[0]["id"])
    user = await make_user(session)

    shops = await _service(
        session, _real_verifier(monkeypatch, GRANT)
    ).provision_shops_and_credentials(_token(), user_id=user.id)

    assert [s.tiktok_numeric_shop_id for s in shops] == [GRANT[1]["id"]]
    assert claimed.user_id == other.id
    assert await _credentials(session, claimed.id) == []


async def test_a_grant_whose_every_shop_is_claimed_is_refused(session, monkeypatch):
    other = await make_user(session)
    for grant in GRANT:
        await make_shop(session, other, tiktok_numeric_shop_id=grant["id"])
    user = await make_user(session)

    with pytest.raises(ShopClaimedByAnotherAccount) as e:
        await _service(session, _real_verifier(monkeypatch, GRANT)).provision_shops_and_credentials(
            _token(), user_id=user.id
        )

    assert "already connected to another account" in str(e.value)


async def test_a_single_shop_grant_claimed_elsewhere_is_still_refused(session, monkeypatch):
    other = await make_user(session)
    await make_shop(session, other, tiktok_shop_id=OPEN_ID)
    user = await make_user(session)

    with pytest.raises(ShopClaimedByAnotherAccount) as e:
        await _service(
            session, _real_verifier(monkeypatch, GRANT[:1])
        ).provision_shops_and_credentials(_token(), user_id=user.id)

    assert "already connected to another account" in str(e.value)


async def test_a_governed_capability_still_refuses_a_multi_shop_token(session, monkeypatch):
    user = await make_user(session)

    with pytest.raises(CredentialBindingError) as e:
        await _service(session, _real_verifier(monkeypatch, GRANT)).provision_shops_and_credentials(
            _token(), user_id=user.id, capability=TikTokCapability.SANDBOX_WRITE
        )

    assert "2 shops" in str(e.value)
    assert (await session.execute(select(Shop).where(Shop.user_id == user.id))).first() is None


async def test_a_grant_with_zero_shops_is_refused(monkeypatch):
    monkeypatch.undo()  # drop the autouse vendor stub: this exercises the real lookup
    monkeypatch.setattr(credential_binding, "list_authorized_shops", lambda **_kw: [])

    with pytest.raises(CredentialBindingError) as e:
        credential_binding.resolve_authorized_shops(app_key="k", app_secret="s", access_token="t")

    assert "zero shops" in str(e.value)


# ---------------------------------------------------------------------------
# 2. kind follows the credential capability, never a shop id
# ---------------------------------------------------------------------------


async def test_a_sandbox_write_connect_marks_the_shop_sandbox(session, monkeypatch):
    user = await make_user(session)

    (shop,) = await _service(
        session, _real_verifier(monkeypatch, GRANT[:1])
    ).provision_shops_and_credentials(
        _token(), user_id=user.id, capability=TikTokCapability.SANDBOX_WRITE
    )

    assert shop.kind == "sandbox"


async def test_a_seller_connect_keeps_the_shop_real(session, monkeypatch):
    user = await make_user(session)

    (shop,) = await _service(
        session, _real_verifier(monkeypatch, GRANT[:1])
    ).provision_shops_and_credentials(_token(), user_id=user.id)

    assert shop.kind == "real"


async def test_a_reconnected_sandbox_shop_becomes_sandbox_from_its_credential(session, monkeypatch):
    user = await make_user(session)
    shop = await make_shop(session, user, tiktok_shop_id=OPEN_ID)
    await make_credential(
        session,
        shop,
        merchant_authorization_id=OPEN_ID,
        capability=TikTokCapability.SANDBOX_WRITE.value,
        shop_cipher=GRANT[0]["cipher"],
    )
    assert shop.kind == "real"

    (again,) = await _service(
        session, _real_verifier(monkeypatch, GRANT[:1])
    ).provision_shops_and_credentials(_token(), user_id=user.id)

    assert again.id == shop.id
    assert again.kind == "sandbox"


async def test_a_sample_shop_kind_is_never_rewritten(session, monkeypatch):
    user = await make_user(session)
    shop = await make_shop(session, user, tiktok_shop_id=OPEN_ID, kind="sample")

    async def verifier(_session, *, capability, access_token):
        return VerifiedShopCipher("ROW_w2a_sample")

    (again,) = await _service(session, verifier).provision_shops_and_credentials(
        _token(), user_id=user.id, capability=TikTokCapability.SANDBOX_WRITE
    )

    assert again.id == shop.id
    assert again.kind == "sample"


# ---------------------------------------------------------------------------
# 3. Missing scopes -> needs_reauth (display only)
# ---------------------------------------------------------------------------

ALL = ",".join(scopes.DEFAULT_REQUIRED_SCOPES)


def test_the_p101_scopes_are_required():
    assert {
        "seller.promotion.write",
        "seller.affiliate_collaboration.read",
        "seller.affiliate_collaboration.write",
        "data.shop_analytics.public.read",
    } <= set(scopes.DEFAULT_REQUIRED_SCOPES)


def test_every_capability_scope_is_a_required_scope():
    needed = {scope for caps in scopes.SCOPES_BY_CAPABILITY.values() for scope in caps}
    assert needed <= set(scopes.DEFAULT_REQUIRED_SCOPES)


def test_all_scopes_granted_is_active():
    status = scopes.status_of(ALL)
    body = status.to_json()
    assert status.connection_state == scopes.ACTIVE
    assert body["needs_reauth"] is False and body["reauth_label"] is None
    assert body["capabilities_needing_reauth"] == []


def test_a_missing_scope_is_needs_reauth_for_its_capabilities_only():
    granted = ",".join(
        s for s in scopes.DEFAULT_REQUIRED_SCOPES if s != "seller.affiliate_collaboration.write"
    )
    body = scopes.status_of(granted).to_json()
    assert body["connection_state"] == scopes.NEEDS_REAUTH
    assert body["reauth_reason"] == scopes.REASON_MISSING_SCOPES
    assert body["reauth_label"] == "Cần cấp lại quyền TikTok"
    assert body["capabilities_needing_reauth"] == ["affiliate_commission"]
    assert body["needs_reconnect"] is True


def test_lapsed_credentials_are_an_expired_authorisation():
    status = scopes.status_from_credentials([(ALL, "needs_reauth")])
    assert status.status == scopes.NOT_CONNECTED
    assert status.connection_state == scopes.NEEDS_REAUTH
    assert status.reauth_reason == scopes.REASON_AUTHORIZATION_EXPIRED


def test_no_credential_is_not_connected():
    status = scopes.status_from_credentials([])
    assert status.connection_state == scopes.NOT_CONNECTED
    assert status.reauth_reason is None


async def test_the_shop_status_api_flags_reauth_and_leaves_the_credential_active(session):
    owner, shop = await make_tenant(session)
    granted = ",".join(s for s in scopes.DEFAULT_REQUIRED_SCOPES if s != "seller.promotion.write")
    cred = await make_credential(session, shop, scopes=granted, status="active")

    async with authenticated_client(session, user=owner, shop=shop) as client:
        body = (await client.get("/v1/shops/me/permissions")).json()["data"]

    assert body["connection_state"] == "needs_reauth"
    assert body["reauth_label"] == "Cần cấp lại quyền TikTok"
    assert body["capabilities_needing_reauth"] == ["promo_discount", "promo_flash_sale"]
    await session.refresh(cred)
    assert cred.status == "active"  # reads the granted scopes allow keep running
