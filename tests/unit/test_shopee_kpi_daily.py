"""The daily Shopee KPI beat: registration, slot, per-shop isolation, skip-if-unchanged.

Collaborators are stubbed (no database); the DB path is
``tests/integration/test_shopee_kpi_daily_db.py``. Synthetic ids only.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from juli_backend.services import shopee_kpi, shopee_kpi_daily
from juli_backend.services.shopee_kpi.rules import ContractTermsError

SHOPS = [uuid.UUID(int=i) for i in (1, 2, 3, 4)]


class _Session:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        self.log.append("commit")


@pytest.fixture
def stubs(monkeypatch: pytest.MonkeyPatch):
    state = SimpleNamespace(
        log=[],
        quiet=set(),
        unchanged=set(),
        checked=[],
        raises={},
        ran=[],
        shops=list(SHOPS),
        now_seen=set(),
    )

    async def ids(_session):
        return state.shops

    async def landed(_session, shop_id):
        return shop_id not in state.quiet

    async def unchanged(_session, shop_id):
        state.checked.append(shop_id)
        exc = state.raises.get(("check", shop_id))
        if exc:
            raise exc
        return shop_id in state.unchanged

    async def run(_session, shop_id, *, now, **_kw):
        state.now_seen.add(now)
        exc = state.raises.get(("run", shop_id))
        if exc:
            raise exc
        state.ran.append(shop_id)

    monkeypatch.setattr(shopee_kpi_daily, "contract_shop_ids", ids)
    monkeypatch.setattr(shopee_kpi_daily, "landed_since_last_run", landed)
    monkeypatch.setattr(shopee_kpi_daily, "inputs_unchanged", unchanged)
    monkeypatch.setattr(shopee_kpi_daily.job, "run_shop_kpi", run)
    state.factory = lambda: _Session(state.log)
    return state


def test_beat_is_registered_on_the_default_queue():
    from juli_backend.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["shopee-kpi-daily"]
    assert entry["task"] == "juli_backend.shopee_kpi_daily"
    assert entry["task"] not in celery_app.conf.task_routes  # default queue, already in -Q

    from juli_backend.workers.tasks import shopee_kpi_daily as module

    assert module.shopee_kpi_daily.name == entry["task"]


def test_slot_is_off_five_and_unshared_with_other_beats():
    from juli_backend.workers.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    mine = schedule["shopee-kpi-daily"]["schedule"]
    (slot,) = {(h, m) for h in mine.hour for m in mine.minute}
    assert slot == (18, 29)
    assert slot[1] % 5 != 0
    for name, entry in schedule.items():
        if name == "shopee-kpi-daily":
            continue
        other = entry["schedule"]
        fires = {(h, m) for h in other.hour for m in other.minute}
        # the every-minute CDP reconcile is the documented exception
        if len(fires) == 24 * 60:
            continue
        assert slot not in fires, name


async def test_each_changed_shop_runs_and_commits(stubs):
    summary = await shopee_kpi_daily.run_daily_kpi(stubs.factory)
    assert stubs.ran == SHOPS
    assert stubs.log.count("commit") == len(SHOPS)
    assert summary == shopee_kpi_daily.DailyKpiSummary(4, 4, 0, 0, 0, 0)


async def test_unchanged_shop_is_skipped_without_running(stubs):
    stubs.unchanged = {SHOPS[1], SHOPS[2]}
    summary = await shopee_kpi_daily.run_daily_kpi(stubs.factory)
    assert stubs.ran == [SHOPS[0], SHOPS[3]]
    assert summary.skipped_unchanged == 2
    assert summary.ran == 2


async def test_a_shop_where_nothing_landed_is_skipped_before_reading_its_inputs(stubs):
    stubs.quiet = {SHOPS[0], SHOPS[3]}
    summary = await shopee_kpi_daily.run_daily_kpi(stubs.factory)
    assert stubs.checked == [SHOPS[1], SHOPS[2]]
    assert stubs.ran == [SHOPS[1], SHOPS[2]]
    assert (summary.skipped_nothing_landed, summary.skipped_unchanged) == (2, 0)


async def test_one_shop_failing_never_aborts_the_others(stubs):
    stubs.raises = {
        ("run", SHOPS[0]): RuntimeError("boom"),
        ("run", SHOPS[1]): shopee_kpi.NoMetrics("x"),
        ("check", SHOPS[2]): ContractTermsError("bad"),
    }
    summary = await shopee_kpi_daily.run_daily_kpi(stubs.factory)
    assert stubs.ran == [SHOPS[3]]
    assert (summary.ran, summary.refused, summary.failed) == (1, 2, 1)
    assert summary.scanned == 4


async def test_every_known_refusal_is_counted_not_failed(stubs):
    stubs.shops = SHOPS
    stubs.raises = {
        ("run", SHOPS[0]): shopee_kpi.NoKpiContract("x"),
        ("run", SHOPS[1]): shopee_kpi.NoMetrics("x"),
        ("check", SHOPS[2]): shopee_kpi.MeasureStartMissing("x"),
        ("check", SHOPS[3]): ContractTermsError("x"),
    }
    summary = await shopee_kpi_daily.run_daily_kpi(stubs.factory)
    assert (summary.refused, summary.failed, summary.ran) == (4, 0, 0)


async def test_all_shops_share_one_run_time(stubs):
    await shopee_kpi_daily.run_daily_kpi(stubs.factory)
    assert len(stubs.now_seen) == 1


async def test_failure_log_carries_type_only(stubs, caplog: pytest.LogCaptureFixture):
    stubs.shops = SHOPS[:1]
    stubs.raises = {("run", SHOPS[0]): RuntimeError("secret-metric-1234")}
    with caplog.at_level("INFO"):
        await shopee_kpi_daily.run_daily_kpi(stubs.factory)
    assert "secret-metric-1234" not in caplog.text
    failed = [r for r in caplog.records if r.message == "shopee_kpi_daily_shop_failed"]
    assert [r.error_type for r in failed] == ["RuntimeError"]
