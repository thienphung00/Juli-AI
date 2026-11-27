"""C5e (batch-1123-a): one computer per hole day on ``GET /v1/connector/shopee/read-days``.
Synthetic values."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from juli_backend.services.ingest import read_day_claims as claims
from juli_backend.services.ingest import read_days
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from tests.support.api import client_for
from tests.unit.test_ingest_gateway import _paired_client, _shopee_tenant

TODAY = date(2026, 11, 19)
SHOP = uuid.uuid4()
A, B = uuid.uuid4(), uuid.uuid4()


def _answer() -> dict:
    return {
        "as_of": "2026-11-19",
        "window_days": 30,
        "datasets": {
            "shop_overview": {"missing": ["2026-11-17", "2026-11-18"]},
            "order_income": {"missing": ["2026-11-18"]},
        },
    }


@pytest.fixture(autouse=True)
def stores():
    set_ingest_rate_gate(InMemoryRateGate())
    claims.set_read_day_claim_store(claims.InMemoryReadDayClaims())
    yield
    claims.set_read_day_claim_store(None)
    set_ingest_rate_gate(None)


async def test_a_second_computer_is_not_handed_the_days_the_first_holds():
    first = await claims.claim_holes(_answer(), shop_id=SHOP, token_id=A)
    second = await claims.claim_holes(_answer(), shop_id=SHOP, token_id=B)
    again = await claims.claim_holes(_answer(), shop_id=SHOP, token_id=A)
    assert first["datasets"] == _answer()["datasets"]
    assert second["datasets"] == {}
    assert again["datasets"] == _answer()["datasets"]  # the holder keeps its own days
    assert second["as_of"] == "2026-11-19" and second["window_days"] == 30


async def test_a_new_hole_goes_to_whoever_asks_first():
    await claims.claim_holes(_answer(), shop_id=SHOP, token_id=A)
    more = _answer()
    more["datasets"]["shop_overview"]["missing"].append("2026-11-16")
    second = await claims.claim_holes(more, shop_id=SHOP, token_id=B)
    assert second["datasets"] == {"shop_overview": {"missing": ["2026-11-16"]}}


async def test_another_shop_is_never_blocked():
    await claims.claim_holes(_answer(), shop_id=SHOP, token_id=A)
    other = await claims.claim_holes(_answer(), shop_id=uuid.uuid4(), token_id=B)
    assert other["datasets"] == _answer()["datasets"]


class _Unavailable:
    async def claim(self, keys, holder, ttl_seconds):
        return None


async def test_without_a_claim_store_the_answer_is_unchanged():
    claims.set_read_day_claim_store(_Unavailable())
    assert await claims.claim_holes(_answer(), shop_id=SHOP, token_id=B) == _answer()


class _FakePipe:
    def __init__(self, data: dict, fail: bool, ttls: set[int]):
        self.data, self.fail, self.ttls, self.ops = data, fail, ttls, []

    def set(self, key, value, nx, ex):
        assert nx is True
        self.ttls.add(ex)
        self.ops.append(("set", key, value, nx, ex))

    def get(self, key):
        self.ops.append(("get", key))

    async def execute(self):
        if self.fail:
            raise RedisConnectionError("down")
        out = []
        for op in self.ops:
            if op[0] == "set":
                _, key, value, _nx, _ex = op
                if key in self.data:
                    out.append(None)
                else:
                    self.data[key] = value
                    out.append(True)
            else:
                out.append(self.data.get(op[1]))
        return out


class _FakeRedis:
    def __init__(self, fail: bool = False):
        self.data: dict = {}
        self.fail = fail
        self.ttls: set[int] = set()

    def pipeline(self, transaction):
        assert transaction is False
        return _FakePipe(self.data, self.fail, self.ttls)


async def test_redis_claims_set_nx_with_the_lease_and_keep_the_holders_own_keys():
    redis = _FakeRedis()
    claims.set_read_day_claim_store(claims.RedisReadDayClaims(redis))
    first = await claims.claim_holes(_answer(), shop_id=SHOP, token_id=A)
    second = await claims.claim_holes(_answer(), shop_id=SHOP, token_id=B)
    again = await claims.claim_holes(_answer(), shop_id=SHOP, token_id=A)
    assert first["datasets"] == _answer()["datasets"] == again["datasets"]
    assert second["datasets"] == {}
    assert redis.ttls == {int(claims.READ_DAY_LEASE.total_seconds())}
    assert claims.READ_DAY_LEASE.total_seconds() >= 2 * 3600  # one daily run plus margin


async def test_a_redis_error_degrades_to_the_unfiltered_answer(caplog):
    claims.set_read_day_claim_store(claims.RedisReadDayClaims(_FakeRedis(fail=True)))
    with caplog.at_level("WARNING"):
        got = await claims.claim_holes(_answer(), shop_id=SHOP, token_id=B)
    assert got == _answer()
    assert any(r.getMessage() == "read_day_claims_unavailable" for r in caplog.records)


async def test_two_paired_computers_do_not_get_the_same_hole_days(session, monkeypatch):
    monkeypatch.setattr(read_days, "vietnam_today", lambda now=None: TODAY)
    user, shop = await _shopee_tenant(session)
    app, code_a = await _paired_client(session, shop, user)
    _, code_b = await _paired_client(session, shop, user)
    async with client_for(app) as ext:
        tokens = []
        for code in (code_a, code_b):
            paired = await ext.post("/v1/ingest/pair", json={"code": code, "platform": "shopee"})
            assert paired.status_code == 200, paired.text
            tokens.append({"Authorization": f"Bearer {paired.json()['token']}"})
        first = (await ext.get("/v1/connector/shopee/read-days", headers=tokens[0])).json()
        second = (await ext.get("/v1/connector/shopee/read-days", headers=tokens[1])).json()
    assert len(first["datasets"]["order_lines"]["missing"]) == 30
    held = {(ds, d) for ds, e in first["datasets"].items() for d in e["missing"]}
    other = {(ds, d) for ds, e in second["datasets"].items() for d in e["missing"]}
    assert held and not held & other


async def test_the_unsettled_refs_follow_the_days_a_token_holds():
    """7b: the second computer gets neither the unsettled days the first holds nor their refs."""
    answer = _answer()
    answer["datasets"]["order_income_unsettled"] = {"missing": ["2026-11-10"]}
    answer["unsettled_orders"] = {"2026-11-10": ["r1", "r2"]}
    first = await claims.claim_holes(answer, shop_id=SHOP, token_id=A)
    second = await claims.claim_holes(answer, shop_id=SHOP, token_id=B)
    assert first["unsettled_orders"] == {"2026-11-10": ["r1", "r2"]}
    assert "unsettled_orders" not in second
