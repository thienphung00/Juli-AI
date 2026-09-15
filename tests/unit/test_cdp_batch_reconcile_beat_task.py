"""Beat-task no-ops are a recorded fact (#1857, W8-F / P10-6).

Before this slice, `cdp_batch_staggered_reconcile_beat_tick` wrote NOTHING at
all on the flag-off path -- the branch that produced 188 "successes" in
~0.002s each on 2026-09-05, indistinguishable from real work. This suite pins
that `cdp_batch_staggered_reconcile_tick_complete` now fires on EVERY exit
path, always carrying `enqueued_count` and a measured `duration_ms`, and that
an exception raised outside the per-shop loop still emits the fact and then
re-raises rather than being swallowed by the outer `try/finally`.

Every assertion reads the EMITTED log record (`caplog`), never the module
source and never a value the test supplied to itself without passing through
the real code path. `celery_app.send_task` is doubled with the real call
shape the production code uses (positional `name`, keyword `kwargs=`, keyword
`queue=`), never a bare `**kwargs` catch-all.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime

import pytest
from freezegun import freeze_time

from juli_backend.core.observability.logging import JsonFormatter
from juli_backend.services.cdp_batch.stagger_scheduler import (
    ReconcileWindow,
    window_minute_for_shop,
)
from juli_backend.workers.tasks.cdp_batch_reconcile import (
    cdp_batch_staggered_reconcile_beat_tick,
)

_EVENT = "cdp_batch_staggered_reconcile_tick_complete"


def _completion_record(caplog):
    return next(r for r in caplog.records if r.message == _EVENT)


def _fake_clock(*ticks: float):
    """Returns successive values from `ticks` on each call -- never a literal."""
    values = iter(ticks)

    def _clock() -> float:
        return next(values)

    return _clock


def _bound_send_task_double(calls: list[dict], *, raise_for_shop: str | None = None):
    """Bound to the real `Celery.send_task` call shape the task actually uses:
    positional `name`, keyword `kwargs=`, keyword `queue=` -- not `**kwargs`,
    which would prove routing rather than that the real call would work.
    """

    def _send_task(name, args=None, kwargs=None, *, queue=None, **options):
        del args, options
        job_kwargs = kwargs or {}
        if raise_for_shop is not None and job_kwargs.get("shop_id") == raise_for_shop:
            raise RuntimeError("broker unreachable")
        calls.append({"name": name, "kwargs": kwargs, "queue": queue})

    return _send_task


# --- flag OFF: the load-bearing no-op, previously silent ------------------


def test_flag_off_still_emits_completion_with_zero_count_and_duration(monkeypatch, caplog):
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ENABLED", "false")
    clock = _fake_clock(100.0, 100.25)

    with caplog.at_level(logging.INFO):
        cdp_batch_staggered_reconcile_beat_tick(clock=clock)

    record = _completion_record(caplog)
    assert record.enqueued_count == 0
    assert record.duration_ms == int((100.25 - 100.0) * 1000)


# --- flag ON, allowlist empty: retained skip line + new completion line ---


def test_empty_allowlist_retains_skip_log_and_emits_completion(monkeypatch, caplog):
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ENABLED", "true")
    monkeypatch.delenv("CDP_BATCH_STAGGERED_RECONCILE_ALLOWLIST", raising=False)
    clock = _fake_clock(200.0, 200.1)

    with caplog.at_level(logging.INFO):
        cdp_batch_staggered_reconcile_beat_tick(clock=clock)

    skip_record = next(
        r for r in caplog.records if r.message == "cdp_batch_staggered_reconcile_skipped"
    )
    assert skip_record.reason == "empty_allowlist"

    completion_record = _completion_record(caplog)
    assert completion_record.enqueued_count == 0
    assert completion_record.duration_ms == int((200.1 - 200.0) * 1000)


# --- flag ON, non-empty allowlist, nothing in window -----------------------


def test_no_shop_in_window_emits_completion_with_zero_count(monkeypatch, caplog):
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ENABLED", "true")
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ALLOWLIST", "shop-a,shop-b")
    clock = _fake_clock(300.0, 300.4)

    calls: list[dict] = []
    monkeypatch.setattr(
        "juli_backend.workers.tasks.cdp_batch_reconcile.celery_app.send_task",
        _bound_send_task_double(calls),
    )

    # Force both shops to a window minute that will not match the frozen
    # current minute below -- deterministic, not a hunt for a hash coincidence.
    far_window = ReconcileWindow(shop_id="irrelevant", day=date(2025, 1, 15), minute_of_day=999)
    monkeypatch.setattr(
        "juli_backend.services.cdp_batch.StaggerScheduler.assign_window",
        lambda self, shop_id, day: far_window,
    )

    with freeze_time(datetime(2025, 1, 15, 0, 0, 0)):
        with caplog.at_level(logging.INFO):
            cdp_batch_staggered_reconcile_beat_tick(clock=clock)

    assert calls == []
    record = _completion_record(caplog)
    assert record.enqueued_count == 0
    assert record.duration_ms == int((300.4 - 300.0) * 1000)


# --- exactly one shop matches its window -----------------------------------


def test_one_shop_in_window_enqueues_exactly_once(monkeypatch, caplog):
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ENABLED", "true")
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ALLOWLIST", "the-only-shop")

    minute = window_minute_for_shop("the-only-shop")
    hour, minute_of_hour = divmod(minute, 60)

    calls: list[dict] = []
    monkeypatch.setattr(
        "juli_backend.workers.tasks.cdp_batch_reconcile.celery_app.send_task",
        _bound_send_task_double(calls),
    )

    with freeze_time(datetime(2025, 1, 15, hour, minute_of_hour, 0)):
        with caplog.at_level(logging.INFO):
            cdp_batch_staggered_reconcile_beat_tick()

    assert len(calls) == 1
    record = _completion_record(caplog)
    assert record.enqueued_count == 1
    assert record.enqueued_count == len(calls)


# --- one enqueue raises, the loop still reaches the shop after it ---------


def test_enqueue_failure_for_one_shop_does_not_stop_the_loop_or_double_fire(monkeypatch, caplog):
    shop_a, shop_b, shop_c = "shop-a", "shop-b", "shop-c"
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ENABLED", "true")
    monkeypatch.setenv(
        "CDP_BATCH_STAGGERED_RECONCILE_ALLOWLIST", ",".join([shop_a, shop_b, shop_c])
    )

    # All three shops share one window minute -- deterministic, not a hunt
    # for a real hash coincidence across three shop ids.
    shared_window = ReconcileWindow(shop_id="shared", day=date(2025, 1, 15), minute_of_day=90)
    monkeypatch.setattr(
        "juli_backend.services.cdp_batch.StaggerScheduler.assign_window",
        lambda self, shop_id, day: shared_window,
    )

    calls: list[dict] = []
    monkeypatch.setattr(
        "juli_backend.workers.tasks.cdp_batch_reconcile.celery_app.send_task",
        _bound_send_task_double(calls, raise_for_shop=shop_b),
    )

    with freeze_time(datetime(2025, 1, 15, 1, 30, 0)):
        with caplog.at_level(logging.INFO):
            cdp_batch_staggered_reconcile_beat_tick()

    enqueued_shops = {c["kwargs"]["shop_id"] for c in calls}
    assert enqueued_shops == {shop_a, shop_c}

    failed_records = [
        r for r in caplog.records if r.message == "cdp_batch_staggered_reconcile_enqueue_failed"
    ]
    assert len(failed_records) == 1
    assert failed_records[0].shop_id == shop_b

    completion_records = [r for r in caplog.records if r.message == _EVENT]
    assert len(completion_records) == 1
    assert completion_records[0].enqueued_count == 2


# --- exception outside the per-shop loop: fact fires, then re-raises ------


def test_exception_before_any_shop_processed_still_emits_completion_and_reraises(
    monkeypatch, caplog
):
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ENABLED", "true")
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ALLOWLIST", "shop-x")

    def _boom(self, shop_id, day):
        raise RuntimeError("assign_window exploded")

    monkeypatch.setattr(
        "juli_backend.services.cdp_batch.StaggerScheduler.assign_window",
        _boom,
    )
    clock = _fake_clock(400.0, 400.05)

    with caplog.at_level(logging.INFO):
        with pytest.raises(RuntimeError, match="assign_window exploded"):
            cdp_batch_staggered_reconcile_beat_tick(clock=clock)

    record = _completion_record(caplog)
    assert record.enqueued_count == 0
    assert record.duration_ms == int((400.05 - 400.0) * 1000)


# --- the emitted line stays one valid JSON object per line -----------------


def test_completion_record_formats_to_one_valid_json_object(monkeypatch, caplog):
    monkeypatch.setenv("CDP_BATCH_STAGGERED_RECONCILE_ENABLED", "false")

    with caplog.at_level(logging.INFO):
        cdp_batch_staggered_reconcile_beat_tick(clock=_fake_clock(1.0, 1.01))

    record = _completion_record(caplog)
    formatted = JsonFormatter().format(record)
    assert "\n" not in formatted.strip("\n")
    payload = json.loads(formatted)
    assert payload["enqueued_count"] == 0
    assert isinstance(payload["duration_ms"], int)
