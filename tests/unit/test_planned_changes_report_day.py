"""F4.12 (E68): an imported ads row whose campaign has no report by its start day is evaluated as
of the first day of its run window that has one. Pure search + the spec gate; made-up days."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from juli_backend.services.planned_changes import external as ext
from juli_backend.services.planned_changes import external_rows as er

FIRST = date(2026, 10, 1)


def _report_from(day: date):
    calls: list[date] = []

    async def has_report(d: date) -> bool:
        calls.append(d)
        return d >= day

    return has_report, calls


async def test_a_campaign_with_a_report_by_the_start_day_is_evaluated_there():
    has_report, calls = _report_from(date(2026, 9, 1))
    assert await ext.first_report_day(has_report, FIRST, FIRST + timedelta(days=6)) == FIRST
    assert calls == [FIRST]


async def test_the_first_day_with_a_report_inside_the_run_window_is_found():
    has_report, _ = _report_from(date(2026, 10, 5))
    got = await ext.first_report_day(has_report, FIRST, FIRST + timedelta(days=9))
    assert got == date(2026, 10, 5)


async def test_a_report_only_on_the_last_day_is_found():
    has_report, _ = _report_from(date(2026, 10, 7))
    assert await ext.first_report_day(has_report, FIRST, date(2026, 10, 7)) == date(2026, 10, 7)


async def test_no_report_anywhere_in_the_window_still_refuses():
    has_report, _ = _report_from(date(2026, 11, 1))
    assert await ext.first_report_day(has_report, FIRST, FIRST + timedelta(days=9)) is None


async def test_a_non_ads_card_keeps_its_as_of():
    plan = er.CardPlan("R1", "price", {"kind": "price", "start": "2026-10-01"})
    nothing: Any = None  # a price card never touches the session
    assert await ext._as_of_for(nothing, nothing, plan, FIRST, date(2026, 11, 1)) == FIRST
