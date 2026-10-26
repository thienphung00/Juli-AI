"""P69: the reviewer identity caches never serve one user's context to another (D8).

Production pays ~197 ms per database round trip, so a reviewer request now serves its
``users`` row, its reviewer account and the pinned shop's facts from a 30 s in-process
cache (``core/security/identity_cache.py``). These tests pin what that cache may and
may not do:

- keyed by the VERIFIED ``sub``: reviewer A's cached row is never handed to reviewer B,
  and a seller token never reads the reviewer cache at all;
- the reviewer gate still runs on every request: a revoke refuses the reviewer once the
  account entry expires, even while its users row and the pin are cached;
- a pin-cache hit still applies the shop's tenant scope (``SET LOCAL``) to the request;
- each hit is a fresh detached ORM instance, never one shared between requests.

Real signed tokens through the real ``get_current_user``, SQLite.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, cast

import pytest
from sqlalchemy import update

from juli_backend.api import reviewer as reviewer_api
from juli_backend.core.security import IdentityCache
from juli_backend.core.security import dependencies as security_dependencies
from juli_backend.models.ops import OpsReviewerAccount
from juli_backend.services.reviewer import accounts as reviewer_accounts
from juli_backend.services.reviewer import create_promotion_card, pin_cache
from juli_backend.services.reviewer.sandbox import MODE_MASKED, PinMode
from tests.support import reviewer as rv
from tests.support.api import build_app, client_for


@pytest.fixture(autouse=True)
def reviewer_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", rv.JWT_SECRET)
    # The production default (30 s): the caches are ON in this module.
    monkeypatch.delenv("REVIEWER_ACCOUNT_CACHE_SECONDS", raising=False)
    rv.reset_caches()
    yield
    rv.reset_caches()


@pytest.fixture
async def world(session, monkeypatch):
    ref = await rv.seed_reference_shop(session)
    await session.commit()
    monkeypatch.setenv("REVIEWER_SHOP_ID", str(ref.shop.id))
    return ref


def _headers(user_id, **kw) -> dict[str, str]:
    return {"Authorization": f"Bearer {rv.token(user_id, **kw)}"}


class _LoadSpy:
    """Counts ``load_authenticated_user`` calls (the users read) per subject."""

    def __init__(self, monkeypatch) -> None:
        self.calls: list[uuid.UUID] = []
        real = security_dependencies.load_authenticated_user

        async def spy(session, token):
            self.calls.append(token.user_id)
            return await real(session, token)

        monkeypatch.setattr(security_dependencies, "load_authenticated_user", spy)


# -- the cache itself -------------------------------------------------------------------


def test_identity_cache_expires_bounds_and_can_be_disabled():
    now = [0.0]
    ttl = [30.0]
    cache: IdentityCache[str, int] = IdentityCache(
        ttl_seconds=lambda: ttl[0], max_entries=2, clock=lambda: now[0]
    )
    cache.put("a", 1)
    assert cache.get("a") == 1
    now[0] = 30.5
    assert cache.get("a") is None  # older than the TTL: gone
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)  # bounded: the oldest entry is evicted
    assert len(cache) == 2 and cache.get("a") is None and cache.get("c") == 3
    ttl[0] = 0.0
    assert cache.get("c") is None  # TTL 0 disables serving
    cache.put("d", 4)
    assert len(cache) == 0 or cache.get("d") is None


def test_default_ttl_is_30_seconds_and_env_overrides(monkeypatch):
    from juli_backend.core.security import reviewer_identity_ttl_seconds

    monkeypatch.delenv("REVIEWER_ACCOUNT_CACHE_SECONDS", raising=False)
    assert reviewer_identity_ttl_seconds() == 30.0
    assert reviewer_accounts.cache_seconds() == 30.0
    monkeypatch.setenv("REVIEWER_ACCOUNT_CACHE_SECONDS", "0")
    assert reviewer_identity_ttl_seconds() == 0.0
    monkeypatch.setenv("REVIEWER_ACCOUNT_CACHE_SECONDS", "nonsense")
    assert reviewer_identity_ttl_seconds() == 30.0


# -- tenant isolation (D8) --------------------------------------------------------------


async def test_reviewer_a_cached_identity_is_never_served_to_reviewer_b(
    session, world, monkeypatch
):
    reviewer_a = await rv.make_reviewer(
        session, platform="shopee", email="a-review@app-juli.com", expires_in=timedelta(days=5)
    )
    reviewer_b = await rv.make_reviewer(
        session, platform="lazada", email="b-review@app-juli.com", expires_in=timedelta(days=20)
    )
    spy = _LoadSpy(monkeypatch)
    app = build_app(session)
    async with client_for(app) as client:
        a1 = await client.get("/v1/reviewer/me", headers=_headers(reviewer_a, platform="shopee"))
        a2 = await client.get("/v1/reviewer/me", headers=_headers(reviewer_a, platform="shopee"))
        b1 = await client.get("/v1/reviewer/me", headers=_headers(reviewer_b, platform="lazada"))
    assert a1.status_code == a2.status_code == b1.status_code == 200, b1.text
    # A's second request was served from A's cache entry; B's first request read B's row.
    assert spy.calls == [reviewer_a, reviewer_b]
    assert a2.json() == a1.json()
    assert b1.json()["platform"] == "lazada" and a1.json()["platform"] == "shopee"
    assert b1.json()["expires_at"] != a1.json()["expires_at"]
    cached_a = security_dependencies._reviewer_users.get(reviewer_a)
    cached_b = security_dependencies._reviewer_users.get(reviewer_b)
    assert cached_a is not None and cached_a["id"] == reviewer_a
    assert cached_b is not None and cached_b["id"] == reviewer_b


async def test_the_users_cache_hands_back_only_the_verified_subjects_own_row(monkeypatch):
    """Even a poisoned entry (another user's row under this key) is never served."""
    a, b = uuid.uuid4(), uuid.uuid4()
    security_dependencies._reviewer_users.put(a, {"id": b, "email": "b@x"})
    token = security_dependencies.VerifiedToken(
        user_id=a,
        identity=_identity(),
        reviewer_platform="shopee",
        session_id="sess-1",
    )
    loaded: list[uuid.UUID] = []

    async def fake_load(session, tok):
        loaded.append(tok.user_id)
        from juli_backend.database import User

        return User(id=tok.user_id, email="a@x")

    async def no_gate(request, session, tok):
        return None

    monkeypatch.setattr(security_dependencies, "load_authenticated_user", fake_load)
    monkeypatch.setattr(security_dependencies, "enforce_reviewer_gate", no_gate)
    monkeypatch.setattr(security_dependencies, "verify_bearer_token", _returns(token))
    user = await security_dependencies.get_current_user(
        cast(Any, object()), None, cast(Any, object())
    )
    assert user.id == a and loaded == [a]


async def test_a_seller_token_never_reads_the_reviewer_users_cache(session, world, monkeypatch):
    seller = world.owner
    # Plant the seller's own id in the reviewer cache with a different e-mail: a seller
    # request must ignore it and read its row.
    security_dependencies._reviewer_users.put(seller.id, {"id": seller.id, "email": "x@x"})
    spy = _LoadSpy(monkeypatch)
    app = build_app(session)
    async with client_for(app) as client:
        response = await client.get(
            "/v1/demo/runs",
            headers={**_headers(seller.id, platform=None), "X-Shop-Id": str(world.shop.id)},
        )
    assert response.status_code == 200, response.text
    assert spy.calls == [seller.id]


async def test_a_revoked_reviewer_is_refused_while_its_user_and_pin_are_cached(session, world):
    reviewer = await rv.make_reviewer(session)
    app = build_app(session)
    async with client_for(app) as client:
        ok = await client.get("/v1/reviewer/me", headers=_headers(reviewer))
        assert ok.status_code == 200, ok.text
        assert security_dependencies._reviewer_users.get(reviewer) is not None
        assert pin_cache.cached(world.shop.id) is not None
        await session.execute(
            update(OpsReviewerAccount)
            .where(OpsReviewerAccount.user_id == reviewer)
            .values(revoked_at=rv.naive_now())
        )
        await session.commit()
        # The account entry expiring (TTL) is what a revoke waits for -- nothing else.
        reviewer_accounts.forget_cached(reviewer)
        refused = await client.get("/v1/reviewer/me", headers=_headers(reviewer))
    assert refused.status_code == 403
    assert refused.headers["x-juli-reviewer-denied"] == "revoked"


async def test_an_expired_reviewer_is_refused_at_once_despite_a_cached_account(
    session, world, monkeypatch
):
    reviewer = await rv.make_reviewer(session, expires_in=timedelta(seconds=60))
    app = build_app(session)
    async with client_for(app) as client:
        assert (await client.get("/v1/reviewer/me", headers=_headers(reviewer))).status_code == 200
        later = rv.naive_now() + timedelta(minutes=5)
        monkeypatch.setattr(reviewer_accounts, "utc_now_naive", lambda: later)
        refused = await client.get("/v1/reviewer/me", headers=_headers(reviewer))
    assert refused.status_code == 403
    assert refused.headers["x-juli-reviewer-denied"] == "expired"


async def test_a_pin_cache_hit_still_applies_the_shops_tenant_scope(session, world, monkeypatch):
    reviewer = await rv.make_reviewer(session)
    applied: list[tuple[uuid.UUID | None, uuid.UUID | None]] = []
    real = reviewer_api._apply_tenant_context_to_session

    async def spy(sess, shop_id, user_id, **kwargs):
        applied.append((shop_id, user_id))
        await real(sess, shop_id, user_id, **kwargs)

    monkeypatch.setattr(reviewer_api, "_apply_tenant_context_to_session", spy)
    app = build_app(session)
    async with client_for(app) as client:
        first = await client.get("/v1/reviewer/me", headers=_headers(reviewer))
        second = await client.get("/v1/reviewer/me", headers=_headers(reviewer))
    assert first.status_code == second.status_code == 200
    assert pin_cache.cached(world.shop.id) is not None
    # P69b: the cold request's identity load read the pin's facts itself, so BOTH the
    # cold and the warm request applied the shop's tenant scope through the same call.
    assert applied == [(world.shop.id, world.owner.id)] * 2
    assert first.json() == second.json()


def test_each_pin_cache_hit_is_a_fresh_detached_shop(world):
    pin = PinMode(MODE_MASKED, writes_enabled=False)
    pin_cache.remember(world.shop, pin)
    one = pin_cache.cached(world.shop.id)
    two = pin_cache.cached(world.shop.id)
    assert one is not None and two is not None
    shop_one, shop_two = one.shop(), two.shop()
    assert shop_one is not shop_two and shop_one is not world.shop
    assert shop_one.id == world.shop.id and shop_one.user_id == world.owner.id
    assert pin_cache.cached(uuid.uuid4()) is None


# -- the sandbox reviewer's decisions --------------------------------------------------


def test_reviewer_cards_current_needs_both_cards_or_a_fresh_negative():
    from juli_backend.models.models import ActionCard
    from juli_backend.services.agent.playbooks import (
        CREATE_PRODUCT_WORKFLOW_KEY,
        CREATE_PROMOTION_WORKFLOW_KEY,
    )

    shop_id = uuid.uuid4()
    product = ActionCard(id=uuid.uuid4(), shop_id=shop_id, workflow_key=CREATE_PRODUCT_WORKFLOW_KEY)
    promotion = ActionCard(
        id=uuid.uuid4(), shop_id=shop_id, workflow_key=CREATE_PROMOTION_WORKFLOW_KEY
    )
    current = create_promotion_card.reviewer_cards_current
    assert current(shop_id, []) is False
    assert current(shop_id, [product]) is False  # no promotion card, no recent try
    assert current(shop_id, [product, promotion]) is False  # never verified
    create_promotion_card._verified_at[promotion.id] = create_promotion_card._now()
    assert current(shop_id, [product, promotion]) is True
    create_promotion_card._not_emitted_at[shop_id] = create_promotion_card._now()
    assert current(shop_id, [product]) is True
    # Another shop's negative never counts for this one.
    assert current(uuid.uuid4(), [product]) is False
    create_promotion_card._not_emitted_at[shop_id] = (
        create_promotion_card._now() - create_promotion_card.NOT_EMITTED_TTL - timedelta(1)
    )
    assert current(shop_id, [product]) is False


def _identity():
    from juli_backend.core.security.claims import VerifiedIdentity

    return VerifiedIdentity(email=None, display_name=None)


def _returns(value):
    async def _f(*_args, **_kwargs):
        return value

    return _f
