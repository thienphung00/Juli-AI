"""ADR-118 §3 (D81.1-D81.2): a changed item against its own history -- the verdict rules.

Pure: a day -> (impressions, clicks) series in, a verdict per metric out. Covers the
max-of-8 / median thresholds, the sale-day exclusion, and every reason for
``chua_ket_luan`` (thin baseline, too few weeks, post window not covered). Synthetic
numbers only.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from juli_backend.services.shop_proposals import self_baseline as sb

DAY0 = date(2026, 3, 10)
IMPRESSIONS = 2000.0


def _series(
    weekly_clicks: list[float], post_clicks: float, *, day0: date = DAY0
) -> dict[date, sb.DayTotals]:
    """``weekly_clicks[0]`` is the week furthest back; each day of a week has that many clicks."""
    out: dict[date, sb.DayTotals] = {}
    for index, clicks in enumerate(weekly_clicks):
        week = len(weekly_clicks) - index  # 8 = oldest ... 1 = the week before day 0
        for offset in range(7):
            out[day0 - timedelta(7 * week) + timedelta(offset)] = (IMPRESSIONS, clicks)
    for offset in range(1, 8):
        out[day0 + timedelta(offset)] = (IMPRESSIONS, post_clicks)
    return out


WEEKS = [100.0, 104.0, 98.0, 102.0, 96.0, 110.0, 106.0, 100.0]  # max 110, median 101


def _run(series, *, target="clicks", covered=DAY0 + timedelta(7), excluded=frozenset(), first=None):
    return sb.evaluate(
        series,
        day0=DAY0,
        target=target,
        first_day=first or min(series),
        covered_through=covered,
        excluded=excluded,
    )


def test_above_the_max_of_the_last_eight_weeks_is_dat():
    out = _run(_series(WEEKS, 111.0))
    got = out.of("clicks")
    assert got.verdict == sb.VERDICT_PASS
    assert got.detail["weekly_max"] == 110.0 and got.detail["weeks"] == 8


def test_equal_to_the_max_is_not_enough_for_dat():
    assert _run(_series(WEEKS, 110.0)).of("clicks").verdict == sb.VERDICT_OPEN


def test_at_or_below_the_median_is_khong_dat():
    assert _run(_series(WEEKS, 101.0)).of("clicks").verdict == sb.VERDICT_FAIL
    assert _run(_series(WEEKS, 60.0)).of("clicks").verdict == sb.VERDICT_FAIL


def test_between_the_median_and_the_max_is_not_concluded():
    got = _run(_series(WEEKS, 105.0)).of("clicks")
    assert got.verdict == sb.VERDICT_OPEN
    assert "reason" not in got.detail


def test_ctr_is_clicks_over_impressions_and_judged_when_it_is_the_target():
    # Same impressions every day, so CTR moves with clicks: 0.0555 > max weekly 0.055.
    got = _run(_series(WEEKS, 111.0), target="ctr").of("ctr")
    assert got.verdict == sb.VERDICT_PASS
    assert got.value == pytest.approx(111.0 / IMPRESSIONS)
    assert got.comparison == pytest.approx(sum(WEEKS[-4:]) / 4 / IMPRESSIONS)


def test_the_other_metrics_are_stored_but_never_decide():
    out = _run(_series(WEEKS, 111.0), target="ctr")
    assert [m.metric for m in out.metrics] == ["impressions", "clicks", "ctr"]
    assert out.of("clicks").verdict == sb.VERDICT_OPEN
    assert out.of("impressions").value == IMPRESSIONS and out.of("impressions").band is None


def test_the_baseline_is_the_28_days_before_day_zero_and_day_zero_is_left_out():
    series = _series(WEEKS, 111.0)
    series[DAY0] = (IMPRESSIONS, 100000.0)  # the day of the change itself
    out = _run(series)
    assert out.pre_from == DAY0 - timedelta(28) and out.pre_to == DAY0 - timedelta(1)
    assert out.post_from == DAY0 + timedelta(1) and out.post_to == DAY0 + timedelta(7)
    assert out.of("clicks").comparison == pytest.approx(sum(WEEKS[-4:]) / 4)


def test_sale_days_are_dropped_from_the_baseline_and_the_post_week():
    day0 = date(2026, 11, 20)  # the baseline holds 11-10..11-12, the post week none
    series = _series(WEEKS, 111.0, day0=day0)
    sale = frozenset({date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 12)})
    for day in sale:
        series[day] = (IMPRESSIONS, 5000.0)
    kept = sb.evaluate(
        series,
        day0=day0,
        target="clicks",
        first_day=min(series),
        covered_through=day0 + timedelta(7),
        excluded=sale,
    )
    polluted = sb.evaluate(
        series,
        day0=day0,
        target="clicks",
        first_day=min(series),
        covered_through=day0 + timedelta(7),
        excluded=frozenset(),
    )
    # The three sale days sit in the week of 106 clicks/day: 25 kept days of 28.
    assert kept.of("clicks").comparison == pytest.approx((sum(WEEKS[-4:]) * 7 - 3 * 106) / 25)
    assert kept.of("clicks").detail["excluded_days"] == 3
    assert polluted.of("clicks").comparison > kept.of("clicks").comparison


def test_a_post_window_the_exports_do_not_cover_is_inconclusive_and_says_how_far_data_goes():
    covered = DAY0 + timedelta(4)
    out = _run(_series(WEEKS, 500.0), covered=covered)
    got = out.of("clicks")
    assert got.verdict == sb.VERDICT_OPEN and got.detail["reason"] == "post_window_not_covered"
    assert out.data_through == covered
    assert got.detail["post_days_kept"] == 4


def test_data_through_stops_at_the_end_of_the_post_window():
    assert _run(
        _series(WEEKS, 500.0), covered=DAY0 + timedelta(30)
    ).data_through == DAY0 + timedelta(7)


def test_fewer_than_thirty_baseline_clicks_is_inconclusive():
    got = _run(_series([1.0] * 8, 50.0)).of("clicks")
    assert got.verdict == sb.VERDICT_OPEN
    assert got.detail["reason"] == "baseline_clicks_below_minimum"
    assert got.detail["baseline_clicks"] == 28.0


def test_fewer_than_four_weekly_values_is_inconclusive():
    series = _series(WEEKS, 500.0)
    out = _run(series, first=DAY0 - timedelta(21))  # the item only has 3 weeks of history
    assert out.of("clicks").detail["reason"] == "too_few_weekly_values"
    assert out.of("clicks").verdict == sb.VERDICT_OPEN


def test_days_before_the_items_first_row_are_not_zeros():
    # 5 weeks of history: the older weeks do not drag the median down to 0.
    series = {d: v for d, v in _series(WEEKS, 111.0).items() if d >= DAY0 - timedelta(35)}
    got = _run(series).of("clicks")
    assert got.detail["weeks"] == 5 and got.detail["weekly_min"] > 0


def test_a_covered_day_without_a_row_counts_as_no_traffic():
    series = _series(WEEKS, 111.0)
    del series[DAY0 + timedelta(3)]
    got = _run(series).of("clicks")
    assert got.detail["post_days_kept"] == 7
    assert got.value == pytest.approx(111.0 * 6 / 7)


def test_the_band_is_the_gap_to_the_weekly_max_and_stays_in_range():
    assert _run(_series(WEEKS, 121.0)).of("clicks").band == pytest.approx(0.1)
    huge = _run(_series([0.0001] * 4 + [100.0] * 4, 1e9)).of("clicks")
    assert huge.band is not None and huge.band <= sb.BAND_LIMIT
