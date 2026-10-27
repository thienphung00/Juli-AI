"""P69: how many database round trips the demo page's load requests make, on real Postgres.

Production pays ~197 ms per round trip (VPS -> Supabase Postgres via Supavisor, measured
2026-10-26), so these counts ARE the latency budget. The partner reviewer on the sandbox
shop measured 9.4-10 s on ``GET /v1/reviewer/me`` and 24.8 s on ``GET /v1/demo/decisions``.

Every request runs the real auth path (a signed Supabase JWT through ``get_current_user``
and the reviewer gate) on a fresh ``juli_app`` session per request -- production's shape,
with RLS, the ``juli_ops`` role switch and the tenant GUCs all live -- and is counted by
``tests/support/sql_counter`` (statements + BEGIN/COMMIT/ROLLBACK).

Each endpoint is called twice and the SECOND call is counted (the reviewer's identity
cache warm, the steady state of a page that fires these together); the cold path is
asserted separately. The seller path is bounded beside it so it never gets worse.

Run with ``-s`` to print every endpoint's statement list.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from juli_backend.api.app import create_app
from juli_backend.database import get_session
from juli_backend.integrations.tiktok import TikTokCapability
from tests.support.postgres import juli_app_async_sessionmaker, requires_postgres
from tests.support.sql_counter import Seen, SqlCounter

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

SECRET = "reviewer-round-trips-secret-0123456789"
PRODUCT_ID = "1730000000000000069"
SESSION_ID = "p69-session"

#: Upper bounds, in round trips (statements + BEGIN/COMMIT/ROLLBACK), on the WARM call.
#: Each was measured on this branch with no slack; raising one is ~197 ms per unit.
#:
#: BEFORE P69 (same data, same harness; reviewer on the sandbox pin): me 12, shop 14,
#: decisions 22 (37 when the promotion card's TikTok check really loads the sandbox
#: credential -- plus the TikTok HTTP calls, on EVERY request while no card qualified),
#: analysis 13, rules 14, runs 16; seller: decisions 16, analysis 11, rules 12, runs 12.
#: Cold ``/v1/reviewer/me``: 20.
#:
#: P69: the reviewer's users row, account and the pinned shop's facts (row + sandbox
#: classification) come from a 30 s identity cache, so a warm reviewer request is
#: BEGIN + the tenant GUCs + the route's own reads + COMMIT/ROLLBACK; the decisions read
#: carries the auto_levers rule and fuses its card context into two joins; the runs list
#: reads narration + "started by me" in the runs statement and both ledger flags in one;
#: the seller's shop check no longer restores a GUC pair it overwrites next.
REVIEWER_BOUNDS: dict[str, int] = {
    "me": 3,
    "shop": 5,
    # BEGIN, GUCs, cards (+ auto_levers), products ⋈ SKUs, runs ⋈ writes, COMMIT.
    "decisions": 6,
    "analysis": 4,
    "rules": 5,
    "runs": 5,
    # BEGIN, GUCs, ingestion state + report flag (one statement since P69b), ROLLBACK.
    "onboarding": 4,
}
#: P69b: the COLD call (account, users row and pin entries expired; asyncpg statements
#: warm), per route. BEFORE P69b (same harness): me 17, shop 19, decisions 20,
#: analysis 18, rules 19, runs 19, onboarding 19. Now the identity costs three round
#: trips over the warm call (ops role switch; account + role restore + GUCs; users row +
#: shops row + pin facts), in the route's own transaction with no COMMIT.
COLD_REVIEWER_BOUNDS: dict[str, int] = {
    "me": 6,
    "shop": 8,
    "decisions": 9,
    "analysis": 7,
    "rules": 8,
    "runs": 8,
    "onboarding": 7,
}
SELLER_BOUNDS: dict[str, int] = {
    "decisions": 12,
    "analysis": 10,
    "rules": 11,
    "runs": 10,
}

ROUTES: dict[str, str] = {
    "me": "/v1/reviewer/me",
    "shop": "/v1/reviewer/shop",
    "decisions": "/v1/demo/decisions",
    "analysis": "/v1/demo/analysis",
    "rules": "/v1/demo/rules",
    "runs": "/v1/demo/runs",
    "onboarding": "/v1/shops/me/onboarding",
}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _forget_caches() -> None:
    from tests.support import reviewer as rv

    rv.reset_caches()


def _forget_identity_caches() -> None:
    """What >30 s idle expires: the reviewer account, users row and pinned shop entries.

    The 60 s "no promotion card" memory and the 10 min mask dictionary are left as they
    are, so the cold count is the identity path itself.
    """
    from juli_backend.core.security import forget_cached_reviewer_users
    from juli_backend.services.reviewer import accounts, pin_cache

    accounts.forget_cached()
    forget_cached_reviewer_users()
    pin_cache.forget_cached()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setenv("TIKTOK_APP_KEY", "app-key")
    monkeypatch.setenv("TIKTOK_APP_SECRET", "app-secret")
    monkeypatch.delenv("REVIEWER_ACCOUNT_CACHE_SECONDS", raising=False)
    _forget_caches()
    yield
    _forget_caches()


def _seed(engine) -> dict[str, uuid.UUID]:
    tag = uuid.uuid4().hex[:8]
    owner, shop, product, card, reviewer = (uuid.uuid4() for _ in range(5))
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM public.tiktok_credentials WHERE capability = 'sandbox_write'")
        )
        conn.execute(
            text("INSERT INTO public.users (id, phone, email) VALUES (:id, :p, :e)"),
            {"id": owner, "p": f"+1569{owner.hex[:7]}", "e": f"seller-{tag}@gmail.com"},
        )
        conn.execute(
            text(
                "INSERT INTO public.shops (id, user_id, shop_name, tiktok_shop_id) "
                "VALUES (:id, :u, :n, :t)"
            ),
            {
                "id": shop,
                "u": owner,
                "n": f"Juli Sandbox {tag}",
                "t": f"76{shop.int % 10**17:017d}",
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.tiktok_credentials "
                "(id, shop_id, merchant_authorization_id, capability, shop_cipher, access_token, "
                " refresh_token, token_expires_at, scopes, status, refresh_count) "
                "VALUES (:id, :s, :m, :c, 'cipher', 'sbx-access', 'r', :exp, "
                " 'seller.product.basic', 'active', 0)"
            ),
            {
                "id": uuid.uuid4(),
                "s": shop,
                "m": f"sbx-{tag}",
                "c": TikTokCapability.SANDBOX_WRITE.value,
                "exp": _now() + timedelta(days=30),
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.products (id, shop_id, tiktok_product_id, name, title, "
                "status, update_time) VALUES (:id, :s, :t, 'Sandbox áo thun', "
                "'Sandbox áo thun', 'ACTIVATE', now())"
            ),
            {"id": product, "s": shop, "t": PRODUCT_ID},
        )
        payload = {
            "diagnosis": {
                "version": "adr106-v1",
                "as_of": "2026-10-26",
                "rank": 1,
                "status": "weak",
                "status_label": "Yếu",
                "stage": {"code": "card", "label": "Thẻ sản phẩm"},
                "lever": {"code": "title", "label": "Tiêu đề", "action": "Viết lại"},
                "main_kpi": {"key": "ctr", "label": "CTR", "value": "1,2%", "raw": 0.012},
                "trigger": {"code": "below_median", "gap": 0.3, "sentence": "CTR thấp"},
                "recoverable_gmv_per_day": 990000.0,
                "product_title": "Sandbox áo thun",
                "tiktok_product_id": PRODUCT_ID,
            }
        }
        conn.execute(
            text(
                "INSERT INTO public.action_cards (id, shop_id, workflow_key, subject_type, "
                "subject_id, revision, priority, severity, title, description, "
                "recommendation_payload, status, surfaced_at, computed_at) VALUES "
                "(:id, :s, 'optimize_product_2', 'product', :p, 1, 1, 'medium', "
                "'Tối ưu tiêu đề', '', :payload, 'active', now(), now())"
            ),
            {"id": card, "s": shop, "p": str(product), "payload": json.dumps(payload)},
        )
        conn.execute(
            text(
                "INSERT INTO public.ops_reviewer_accounts (id, user_id, email, role, platform, "
                "expires_at, created_by, last_session_id) VALUES (:id, :u, :e, 'reviewer', "
                "'shopee', :exp, 'owner@app-juli.com', :sid)"
            ),
            {
                "id": uuid.uuid4(),
                "u": reviewer,
                "e": f"shopee-review-{tag}@app-juli.com",
                "exp": _now() + timedelta(days=30),
                "sid": SESSION_ID,
            },
        )
        # A run the reviewer started from that card (approval, narration, a confirmed write):
        # the sandbox reviewer's runs list and the card's context read all of them.
        run = uuid.uuid4()
        conn.execute(
            text("INSERT INTO public.users (id, phone, email) VALUES (:id, :p, :e)"),
            {"id": reviewer, "p": f"+1570{reviewer.hex[:7]}", "e": f"rv-{tag}@app-juli.com"},
        )
        conn.execute(
            text(
                "INSERT INTO public.workflow_runs (id, shop_id, product_id, action_card_id, "
                "status, prompt_version, prompt_sha256, subject_ref, write_mode, created_at) "
                "VALUES (:id, :s, :p, :c, 'completed', 'v1', 'sha', :p, 'live', now())"
            ),
            {"id": run, "s": shop, "p": product, "c": card},
        )
        conn.execute(
            text(
                "INSERT INTO public.action_card_approvals (id, action_card_id, "
                "approved_by_user_id, approved_at, card_snapshot) "
                "VALUES (:id, :c, :u, now(), '{}')"
            ),
            {"id": uuid.uuid4(), "c": card, "u": reviewer},
        )
        conn.execute(
            text(
                "INSERT INTO public.workflow_run_events (id, workflow_run_id, sequence_number, "
                "event_type, timestamp, payload) VALUES (:id, :r, 1, 'workflow.status', now(), "
                '\'{"phase_narration": "Xong"}\')'
            ),
            {"id": uuid.uuid4(), "r": run},
        )
        conn.execute(
            text(
                "INSERT INTO public.tool_executions (id, shop_id, approval_id, workflow_run_id, "
                "tool_name, payload_json, status, outcome_json) VALUES (:id, :s, :a, :r, "
                "'update_product_listing', '{}', 'succeeded', '{\"ok\": true, \"title\": \"x\"}')"
            ),
            {"id": uuid.uuid4(), "s": shop, "a": uuid.uuid4(), "r": run},
        )
        # The onboarding poll reads the shop's ingestion state (every connected shop has one).
        conn.execute(
            text("INSERT INTO public.shop_ingestion_state (shop_id) VALUES (:s)"), {"s": shop}
        )
    return {"owner": owner, "shop": shop, "card": card, "reviewer": reviewer}


def _tiktok_unreadable(*_args, **_kwargs):
    raise RuntimeError("no TikTok in this test")


@pytest.fixture
def world(owner_engine, monkeypatch) -> dict[str, uuid.UUID]:
    # The "Tạo khuyến mãi" card asks TikTok whether a product is promotable; never from a
    # test. Unreadable -> no card (and the shop is not re-tried for NOT_EMITTED_TTL).
    from juli_backend.services.reviewer import create_promotion_card

    monkeypatch.setattr(create_promotion_card, "_promotion_resources", _tiktok_unreadable)
    seeded = _seed(owner_engine)
    monkeypatch.setenv("REVIEWER_SHOP_ID", str(seeded["shop"]))
    return seeded


def _token(user_id: uuid.UUID, *, reviewer: bool, session_id: str = SESSION_ID) -> str:
    claims: dict = {
        "sub": str(user_id),
        "aud": "authenticated",
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "email": "shopee-review@app-juli.com" if reviewer else "seller@gmail.com",
        "email_verified": True,
        "session_id": session_id,
        "app_metadata": {"provider": "email"},
    }
    if reviewer:
        claims["app_metadata"].update({"juli_role": "reviewer", "juli_platform": "shopee"})
    return pyjwt.encode(claims, SECRET, algorithm="HS256")


class Probe:
    def __init__(self, client: AsyncClient, counter: SqlCounter) -> None:
        self.client = client
        self.counter = counter

    async def once(self, path: str, headers: dict[str, str]) -> Seen:
        with self.counter.measure() as seen:
            response = await self.client.get(path, headers=headers)
        # ``/v1/demo/analysis`` answers 404 until the shop's first diagnosis is built; the
        # read it makes to say so is the same one that finds a report.
        ok = (200, 404) if path == ROUTES["analysis"] else (200,)
        assert response.status_code in ok, (path, response.status_code, response.text)
        return seen

    async def warm(self, label: str, path: str, headers: dict[str, str]) -> Seen:
        await self.once(path, headers)
        seen = await self.once(path, headers)
        print(f"\n== {label} GET {path}\n{seen.describe()}")
        return seen

    async def cold(self, label: str, path: str, headers: dict[str, str]) -> Seen:
        """The first request after every identity cache expired (asyncpg statements warm)."""
        await self.once(path, headers)
        _forget_identity_caches()
        seen = await self.once(path, headers)
        print(f"\n== {label} GET {path} (cold)\n{seen.describe()}")
        return seen


@pytest_asyncio.fixture
async def probe(world) -> AsyncIterator[Probe]:
    async with juli_app_async_sessionmaker() as factory:
        engine = factory.kw["bind"]
        counter = SqlCounter.attach(engine)
        app = create_app()

        async def per_request_session():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = per_request_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield Probe(client, counter)
        counter.detach()


def _reviewer_headers(world) -> dict[str, str]:
    # The sandbox shop is shown unmasked, under its real id (D73).
    return {
        "Authorization": f"Bearer {_token(world['reviewer'], reviewer=True)}",
        "X-Shop-Id": str(world["shop"]),
    }


def _seller_headers(world) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token(world['owner'], reviewer=False)}",
        "X-Shop-Id": str(world["shop"]),
    }


@pytest.mark.parametrize("name", sorted(REVIEWER_BOUNDS))
async def test_reviewer_route_round_trips(probe, world, name):
    seen = await probe.warm("reviewer", ROUTES[name], _reviewer_headers(world))
    assert seen.round_trips <= REVIEWER_BOUNDS[name], f"{name}: {seen.describe()}"


@pytest.mark.parametrize("name", sorted(SELLER_BOUNDS))
async def test_seller_route_round_trips(probe, world, name):
    seen = await probe.warm("seller", ROUTES[name], _seller_headers(world))
    assert seen.round_trips <= SELLER_BOUNDS[name], f"{name}: {seen.describe()}"


@pytest.mark.parametrize("name", sorted(COLD_REVIEWER_BOUNDS))
async def test_reviewer_route_round_trips_cold(probe, world, name):
    """The first request after the identity caches expired (>30 s idle), per route."""
    seen = await probe.cold("reviewer", ROUTES[name], _reviewer_headers(world))
    assert seen.round_trips <= COLD_REVIEWER_BOUNDS[name], f"{name}: {seen.describe()}"


async def test_two_reviewers_each_get_their_own_identity_on_postgres(probe, world, owner_engine):
    """D8: reviewer A's cached account / users row is never served to reviewer B."""
    with owner_engine.begin() as conn:
        other = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO public.ops_reviewer_accounts (id, user_id, email, role, platform, "
                "expires_at, created_by, last_session_id) VALUES (:id, :u, :e, 'reviewer', "
                "'lazada', :exp, 'owner@app-juli.com', :sid)"
            ),
            {
                "id": uuid.uuid4(),
                "u": other,
                "e": f"lazada-review-{other.hex[:6]}@app-juli.com",
                "exp": _now() + timedelta(days=3),
                "sid": SESSION_ID,
            },
        )
    a_headers = _reviewer_headers(world)
    b_token = _token(other, reviewer=True)
    claims = pyjwt.decode(b_token, SECRET, algorithms=["HS256"], audience="authenticated")
    claims["app_metadata"]["juli_platform"] = "lazada"
    b_headers = {
        "Authorization": f"Bearer {pyjwt.encode(claims, SECRET, algorithm='HS256')}",
        "X-Shop-Id": str(world["shop"]),
    }
    a1 = await probe.client.get(ROUTES["me"], headers=a_headers)
    b1 = await probe.client.get(ROUTES["me"], headers=b_headers)
    a2 = await probe.client.get(ROUTES["me"], headers=a_headers)
    assert a1.status_code == b1.status_code == a2.status_code == 200, b1.text
    assert a1.json()["platform"] == a2.json()["platform"] == "shopee"
    assert b1.json()["platform"] == "lazada"
    assert b1.json()["expires_at"] != a1.json()["expires_at"]


async def test_cold_identity_load_leaves_only_the_reviewers_own_scope_on_postgres(world):
    """D8: after the fused cold load the role is back to juli_app and the GUCs name only the
    verified sub and the configured pin; the reads saw only those two rows."""
    from juli_backend.services.reviewer import identity

    _forget_identity_caches()
    async with juli_app_async_sessionmaker() as factory, factory() as session:
        loaded = await identity.load_identity(session, world["reviewer"], world["shop"])
        role, user_guc, shop_guc, visible_users = (
            await session.execute(
                text(
                    "SELECT current_user, current_setting('app.current_user_id', true), "
                    "current_setting('app.current_shop_id', true), "
                    "(SELECT count(*) FROM public.users)"
                )
            )
        ).one()
        await session.rollback()
    assert role == "juli_app"
    assert user_guc == str(world["reviewer"]) and shop_guc == str(world["shop"])
    assert visible_users == 1  # RLS: the reviewer's own row, never the shop owner's
    assert loaded.account is not None and loaded.account.user_id == world["reviewer"]
    assert loaded.user_values is not None and loaded.user_values["id"] == world["reviewer"]
    assert loaded.pinned is not None and loaded.pinned.shop_id == world["shop"]
    assert loaded.pinned.owner_user_id == world["owner"]
    assert loaded.pinned.pin.sandbox and loaded.pinned.pin.writes_enabled


async def test_concurrent_cold_requests_share_one_load_on_postgres(probe, world, owner_engine):
    """N concurrent cold requests of one reviewer: one account read; two reviewers: two."""
    other = uuid.uuid4()
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.ops_reviewer_accounts (id, user_id, email, role, platform, "
                "expires_at, created_by, last_session_id) VALUES (:id, :u, :e, 'reviewer', "
                "'shopee', :exp, 'owner@app-juli.com', :sid)"
            ),
            {
                "id": uuid.uuid4(),
                "u": other,
                "e": f"second-review-{other.hex[:6]}@app-juli.com",
                "exp": _now() + timedelta(days=3),
                "sid": SESSION_ID,
            },
        )
        conn.execute(
            text("INSERT INTO public.users (id, phone, email) VALUES (:id, :p, :e)"),
            {"id": other, "p": f"+1571{other.hex[:7]}", "e": f"rv2-{other.hex[:6]}@app-juli.com"},
        )
    a = _reviewer_headers(world)
    b = {
        "Authorization": f"Bearer {_token(other, reviewer=True)}",
        "X-Shop-Id": str(world["shop"]),
    }
    await probe.once(ROUTES["me"], a)  # asyncpg statements warm
    _forget_identity_caches()
    paths = [ROUTES[name] for name in ("me", "shop", "analysis", "onboarding", "rules", "runs")]
    with probe.counter.measure() as seen:
        responses = await asyncio.gather(
            *(probe.client.get(path, headers=h) for path in paths for h in (a, b))
        )
    assert all(r.status_code in (200, 404) for r in responses), [r.text for r in responses]
    account_reads = [e for e in seen.events if e.startswith("SELECT account.id")]
    assert len(account_reads) == 2, seen.describe()  # one per reviewer, not one per request
    me_a, me_b = responses[0].json(), responses[1].json()
    assert me_a["expires_at"] != me_b["expires_at"]  # each reviewer got its own account
