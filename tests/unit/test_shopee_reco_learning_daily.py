"""P91 D-14: the recommendations' learning / calibration runs daily, right after the daily Shopee
KPI step, for the pilot shops only. Pure collaborators stubbed; the pilot filter on the SQLite
substrate. Synthetic ids only."""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest

from juli_backend.models.ops import OpsShopSettings
from juli_backend.services import shopee_reco_learning_daily as daily
from tests.unit.test_shopee_file_datasets import _shop

SHOPS = [uuid.UUID(int=i) for i in (1, 2, 3)]
NOW = datetime(2026, 11, 5, 18, 40)


class _Session:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        self.log.append("commit")


class _Scope:
    def __init__(self, shop_id: uuid.UUID, log: list[str]) -> None:
        self.shop_id, self.log = shop_id, log

    async def __aenter__(self) -> None:
        self.log.append(f"scope:{self.shop_id.int}")

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def stubs(monkeypatch: pytest.MonkeyPatch):
    state = SimpleNamespace(log=[], ran=[], raises={}, nows=set())

    async def ids(_session):
        return list(SHOPS)

    async def run_learning(_session, shop_id, *, now, **_kw):
        state.nows.add(now)
        if shop_id in state.raises:
            raise state.raises[shop_id]
        state.ran.append(shop_id)
        return SimpleNamespace(observations_total=5, states=2)

    monkeypatch.setattr(daily, "pilot_shop_ids", ids)
    monkeypatch.setattr(daily.measure, "run_learning", run_learning)
    monkeypatch.setattr(daily, "with_shop_scope", lambda _s, shop_id: _Scope(shop_id, state.log))
    state.factory = lambda: _Session(state.log)
    return state


async def test_each_pilot_shop_learns_in_its_own_scope_and_commits(stubs):
    summary = await daily.run_daily_learning(stubs.factory, now=NOW)
    assert stubs.ran == SHOPS and stubs.nows == {NOW}
    assert stubs.log.count("commit") == len(SHOPS)
    assert [e for e in stubs.log if e.startswith("scope")] == [f"scope:{s.int}" for s in SHOPS]
    assert summary == daily.DailyLearningSummary(3, 0, 15, 6)


async def test_a_failing_shop_is_counted_and_never_stops_the_rest(stubs):
    stubs.raises = {SHOPS[0]: RuntimeError("boom with 123456 in it")}
    summary = await daily.run_daily_learning(stubs.factory, now=NOW)
    assert stubs.ran == SHOPS[1:]
    assert (summary.shops, summary.failed) == (3, 1)
    assert stubs.log.count("commit") == 2


async def test_running_twice_is_the_same_job(stubs):
    first = await daily.run_daily_learning(stubs.factory, now=NOW)
    second = await daily.run_daily_learning(stubs.factory, now=NOW)
    assert first == second  # DB only, recomputed from the same rows


async def test_only_pilot_stage_shops_and_listed_ids_are_chosen(session, monkeypatch):
    pilot, other, listed = await _shop(session), await _shop(session), await _shop(session)
    session.add(OpsShopSettings(shop_id=pilot.id, stage="pilot"))
    session.add(OpsShopSettings(shop_id=other.id, stage="self"))
    await session.flush()
    monkeypatch.delenv(daily.ENV_SHOP_IDS, raising=False)
    assert await daily.pilot_shop_ids(session) == [pilot.id]
    monkeypatch.setenv(daily.ENV_SHOP_IDS, f"{listed.id}, not-a-uuid, ")
    assert await daily.pilot_shop_ids(session) == sorted([pilot.id, listed.id], key=str)


def test_the_kpi_beat_task_runs_the_learning_step_last(monkeypatch):
    import asyncio

    from juli_backend.workers.tasks import shopee_kpi_daily as task

    order: list[str] = []

    async def kpi(_factory):
        order.append("kpi")
        return SimpleNamespace(
            scanned=0, ran=0, skipped_nothing_landed=0, skipped_unchanged=0, refused=0, failed=0
        )

    async def measured(_factory):
        order.append("measure")
        return SimpleNamespace(counts=SimpleNamespace(written=0, measured=0), failed=0)

    async def learn(_factory):
        order.append("learn")
        return daily.DailyLearningSummary(1, 0, 3, 2)

    monkeypatch.setattr(task.daily, "run_daily_kpi", kpi)
    monkeypatch.setattr(task, "measure_all", measured)
    monkeypatch.setattr(task.learning_daily, "run_daily_learning", learn)
    out = asyncio.run(task._run(lambda: None))
    assert order == ["kpi", "measure", "learn"]
    assert (out["learning_shops"], out["learning_failed"], out["learning_observations"]) == (
        1,
        0,
        3,
    )


def test_a_failure_in_the_learning_step_does_not_fail_the_task(monkeypatch):
    import asyncio

    from juli_backend.workers.tasks import shopee_kpi_daily as task

    async def kpi(_factory):
        return SimpleNamespace(
            scanned=0, ran=0, skipped_nothing_landed=0, skipped_unchanged=0, refused=0, failed=0
        )

    async def measured(_factory):
        return SimpleNamespace(counts=SimpleNamespace(written=0, measured=0), failed=0)

    async def learn(_factory):
        raise RuntimeError("x")

    monkeypatch.setattr(task.daily, "run_daily_kpi", kpi)
    monkeypatch.setattr(task, "measure_all", measured)
    monkeypatch.setattr(task.learning_daily, "run_daily_learning", learn)
    assert "learning_shops" not in asyncio.run(task._run(lambda: None))
