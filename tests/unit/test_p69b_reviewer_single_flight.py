"""P69b: concurrent cold reviewer requests share ONE identity load, never across users (D8).

Live after P69 (2026-10-26): the demo page fires 4-7 requests at once; after >30 s idle
each one missed the reviewer identity cache and ran the whole cold path itself (6-7 s
each). ``core.security.SingleFlight`` + ``services/reviewer/identity.load_identity`` make
the first miss load and the rest wait for it. These tests pin:

- N concurrent cold loads for one reviewer -> the account read and the pin
  classification run ONCE, and every caller gets that reviewer's own facts;
- two reviewers concurrently -> two loads, each caller gets its own (never crossed);
- a loader error reaches every waiter, is not kept, and the next call loads again;
- a cancelled leader does not fail its waiters (one of them loads instead).

SQLite (the plain-statement path of the same loader); the fused Postgres statements are
measured and checked in ``tests/integration/test_reviewer_round_trips.py``.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import SingleFlight, remember_reviewer_user
from juli_backend.models.models import User
from juli_backend.services.reviewer import accounts, identity, pin_cache, sandbox
from juli_backend.services.reviewer.identity import ReviewerIdentity
from tests.support import reviewer as rv

N = 6
#: The loader is replaced in the tests that pass this: no session is ever used.
_NO_SESSION = cast(AsyncSession, object())


@pytest.fixture(autouse=True)
def _caches(monkeypatch):
    monkeypatch.delenv("REVIEWER_ACCOUNT_CACHE_SECONDS", raising=False)
    rv.reset_caches()
    yield
    rv.reset_caches()


# -- the primitive -----------------------------------------------------------------------


async def test_concurrent_calls_for_one_key_run_the_loader_once():
    flight: SingleFlight[str, int] = SingleFlight()
    calls: list[str] = []
    gate = asyncio.Event()

    async def loader() -> int:
        calls.append("a")
        await gate.wait()
        return 7

    tasks = [asyncio.create_task(flight.run("a", loader)) for _ in range(N)]
    await asyncio.sleep(0)
    gate.set()
    assert await asyncio.gather(*tasks) == [7] * N
    assert calls == ["a"]
    assert not flight.in_flight("a")


async def test_two_keys_never_share_a_flight():
    flight: SingleFlight[str, str] = SingleFlight()
    gate = asyncio.Event()
    calls: list[str] = []

    def loader_for(key: str):
        async def loader() -> str:
            calls.append(key)
            await gate.wait()
            return f"value-of-{key}"

        return loader

    a = [asyncio.create_task(flight.run("a", loader_for("a"))) for _ in range(3)]
    b = [asyncio.create_task(flight.run("b", loader_for("b"))) for _ in range(3)]
    await asyncio.sleep(0)
    gate.set()
    assert await asyncio.gather(*a) == ["value-of-a"] * 3
    assert await asyncio.gather(*b) == ["value-of-b"] * 3
    assert sorted(calls) == ["a", "b"]


async def test_an_error_reaches_every_waiter_and_the_next_call_retries():
    flight: SingleFlight[str, int] = SingleFlight()
    gate = asyncio.Event()
    calls = 0

    async def failing() -> int:
        nonlocal calls
        calls += 1
        await gate.wait()
        raise RuntimeError("database went away")

    tasks = [asyncio.create_task(flight.run("k", failing)) for _ in range(N)]
    await asyncio.sleep(0)
    gate.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert calls == 1
    assert all(isinstance(r, RuntimeError) for r in results)
    assert not flight.in_flight("k")  # the error is not kept

    async def working() -> int:
        nonlocal calls
        calls += 1
        return 3

    assert await flight.run("k", working) == 3
    assert calls == 2


async def test_a_cancelled_leader_does_not_fail_its_waiters():
    flight: SingleFlight[str, int] = SingleFlight()
    started = asyncio.Event()
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await asyncio.sleep(3600)  # the leader's client goes away mid-load
        return 11

    leader = asyncio.create_task(flight.run("k", loader))
    await started.wait()
    waiter = asyncio.create_task(flight.run("k", loader))
    await asyncio.sleep(0)
    leader.cancel()
    assert await waiter == 11  # the waiter became the new leader
    assert calls == 2
    with pytest.raises(asyncio.CancelledError):
        await leader


# -- the reviewer identity load ----------------------------------------------------------


class _Spies:
    """Count (and slow down) the account read and the pin classification."""

    def __init__(self, monkeypatch) -> None:
        self.accounts: list[uuid.UUID] = []
        self.pins: list[uuid.UUID] = []
        read_account, classify_pin = accounts.read_account, sandbox.classify_pin

        async def slow_account(session, user_id):
            self.accounts.append(user_id)
            await asyncio.sleep(0.02)  # every other request arrives while this one loads
            return await read_account(session, user_id)

        async def slow_pin(session, shop_id):
            self.pins.append(shop_id)
            await asyncio.sleep(0.02)
            return await classify_pin(session, shop_id)

        monkeypatch.setattr(accounts, "read_account", slow_account)
        monkeypatch.setattr(sandbox, "classify_pin", slow_pin)


async def _reviewer_with_user_row(session, **kw) -> uuid.UUID:
    reviewer = await rv.make_reviewer(session, **kw)
    session.add(User(id=reviewer, email=f"{reviewer.hex[:8]}@app-juli.com"))
    await session.commit()
    return reviewer


async def test_n_concurrent_cold_requests_for_one_reviewer_load_once(session, monkeypatch):
    ref = await rv.seed_reference_shop(session)
    await session.commit()
    reviewer = await _reviewer_with_user_row(session)
    spies = _Spies(monkeypatch)

    results = await asyncio.gather(
        *(identity.load_identity(session, reviewer, ref.shop.id) for _ in range(N))
    )

    assert spies.accounts == [reviewer]  # one account read for the whole burst
    assert spies.pins == [ref.shop.id]  # one pin classification
    for result in results:
        assert result.account is not None and result.account.user_id == reviewer
        assert result.user_values is not None and result.user_values["id"] == reviewer
        assert result.pinned is not None and result.pinned.shop_id == ref.shop.id
    # And the burst warmed the caches: the next request loads nothing.
    again = await identity.load_identity(session, reviewer, ref.shop.id)
    assert again.account == results[0].account
    assert spies.accounts == [reviewer] and spies.pins == [ref.shop.id]


async def test_the_flight_is_shared_even_with_the_cache_disabled(session, monkeypatch):
    """TTL 0 (tests flip state between requests): concurrent misses still load once."""
    monkeypatch.setenv("REVIEWER_ACCOUNT_CACHE_SECONDS", "0")
    ref = await rv.seed_reference_shop(session)
    await session.commit()
    reviewer = await _reviewer_with_user_row(session)
    spies = _Spies(monkeypatch)
    await asyncio.gather(
        *(identity.load_identity(session, reviewer, ref.shop.id) for _ in range(3))
    )
    assert spies.accounts == [reviewer]
    await identity.load_identity(session, reviewer, ref.shop.id)
    assert spies.accounts == [reviewer, reviewer]  # nothing kept: the next one reads


async def test_two_reviewers_concurrently_load_twice_and_never_cross(monkeypatch):
    a, b, shop = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    loads: list[uuid.UUID] = []
    gate = asyncio.Event()

    async def fake_load(session, user_id, pin_shop_id):
        loads.append(user_id)
        await gate.wait()
        account = accounts.ReviewerAccount(
            id=uuid.uuid4(),
            user_id=user_id,
            email=f"{user_id.hex[:6]}@app-juli.com",
            platform="shopee" if user_id == a else "lazada",
            expires_at=rv.naive_now() + timedelta(days=3),
            revoked_at=None,
            last_session_id=None,
        )
        return ReviewerIdentity(account, {"id": user_id}, None)

    monkeypatch.setattr(identity, "_load", fake_load)
    tasks = [
        asyncio.create_task(identity.load_identity(_NO_SESSION, who, shop))
        for who in (a, b, a, b, a, b)
    ]
    await asyncio.sleep(0)
    gate.set()
    results = await asyncio.gather(*tasks)
    assert sorted(loads) == sorted([a, b])  # one load per reviewer, not one for both
    for who, result in zip((a, b, a, b, a, b), results, strict=True):
        assert result.account is not None and result.account.user_id == who
        assert result.user_values == {"id": who}
        assert result.account.platform == ("shopee" if who == a else "lazada")


async def test_a_loaded_value_for_another_key_is_never_handed_out(monkeypatch):
    """Defence in depth: a (buggy) loader answering for someone else is dropped, fail closed."""
    me, someone_else, shop = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async def wrong_load(session, user_id, pin_shop_id):
        account = accounts.ReviewerAccount(
            id=uuid.uuid4(),
            user_id=someone_else,
            email="x@app-juli.com",
            platform="shopee",
            expires_at=rv.naive_now() + timedelta(days=3),
            revoked_at=None,
            last_session_id=None,
        )
        return ReviewerIdentity(account, {"id": someone_else}, None)

    monkeypatch.setattr(identity, "_load", wrong_load)
    result = await identity.load_identity(_NO_SESSION, me, shop)
    assert result.account is None and result.user_values is None and result.pinned is None


async def test_a_load_error_reaches_every_waiter_and_the_next_request_retries(session, monkeypatch):
    ref = await rv.seed_reference_shop(session)
    await session.commit()
    reviewer = await _reviewer_with_user_row(session)
    calls = 0
    real = accounts.read_account

    async def flaky(sess, user_id):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        if calls == 1:
            raise ConnectionError("pool timeout")
        return await real(sess, user_id)

    monkeypatch.setattr(accounts, "read_account", flaky)
    results = await asyncio.gather(
        *(identity.load_identity(session, reviewer, ref.shop.id) for _ in range(N)),
        return_exceptions=True,
    )
    assert calls == 1
    assert all(isinstance(r, ConnectionError) for r in results)
    assert accounts.cached_account(reviewer) is None  # the failure is not cached

    retried = await identity.load_identity(session, reviewer, ref.shop.id)
    assert calls == 2
    assert retried.account is not None and retried.account.user_id == reviewer


async def test_a_refused_account_loads_no_user_row_and_no_pin(session, monkeypatch):
    ref = await rv.seed_reference_shop(session)
    await session.commit()
    revoked = await _reviewer_with_user_row(session, revoked=True)
    spies = _Spies(monkeypatch)
    result = await identity.load_identity(session, revoked, ref.shop.id)
    assert result.account is not None and result.account.status() == accounts.STATUS_REVOKED
    assert result.user_values is None and result.pinned is None
    assert spies.pins == []


async def test_warm_caches_serve_without_any_load(session, monkeypatch):
    ref = await rv.seed_reference_shop(session)
    await session.commit()
    reviewer = await _reviewer_with_user_row(session)
    await identity.load_identity(session, reviewer, ref.shop.id)
    assert pin_cache.cached(ref.shop.id) is not None
    remember_reviewer_user({"id": reviewer, "email": "r@app-juli.com"})

    async def no_load(*_a, **_k):
        raise AssertionError("a warm request must not load")

    monkeypatch.setattr(identity, "_load", no_load)
    warm = await identity.load_identity(session, reviewer, ref.shop.id)
    assert warm.user_values is not None and warm.user_values["id"] == reviewer
