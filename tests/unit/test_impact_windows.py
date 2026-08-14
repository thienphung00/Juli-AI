"""Date-window arithmetic for the ratio-form DiD compute — ADR-077 decision 2
(#1041).

Acceptance criteria covered here:
- Day T is excluded from the pre window, the post window (both preliminary
  and final), and from any mean computed over a window that happens to span
  it — asserted with a fixture where T carries an extreme value that would
  visibly move any mean it leaked into.
- Preliminary post window is T+1..T+7, final is T+1..T+14.
- Windows are a pure function of one injected reference date `T` — no
  `date.today()` / `datetime.now()` anywhere in this file or the module
  under test.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from juli_backend.services.impact.windows import (
    POST_WINDOW_DAYS,
    PRE_WINDOW_DAYS,
    compute_windows,
    date_range,
    mean_over_window,
    post_window,
    pre_window,
)

# Single injected reference point — every date in this file is derived from
# T, never from datetime.now()/date.today().
T = date(2026, 3, 20)


class TestPreWindow:
    def test_pre_window_is_fourteen_days_ending_the_day_before_t(self):
        start, end = pre_window(T)
        assert start == T - timedelta(days=14)
        assert end == T - timedelta(days=1)
        assert (end - start).days + 1 == PRE_WINDOW_DAYS == 14

    def test_pre_window_never_includes_t(self):
        start, end = pre_window(T)
        assert T not in date_range(start, end)

    def test_pre_window_identical_for_preliminary_and_final(self):
        # Only the post window's length depends on preliminary vs final.
        assert pre_window(T) == pre_window(T)


class TestPostWindow:
    def test_preliminary_post_window_is_seven_days_starting_the_day_after_t(self):
        start, end = post_window(T, "preliminary")
        assert start == T + timedelta(days=1)
        assert end == T + timedelta(days=7)
        assert (end - start).days + 1 == POST_WINDOW_DAYS["preliminary"] == 7

    def test_final_post_window_is_fourteen_days_starting_the_day_after_t(self):
        start, end = post_window(T, "final")
        assert start == T + timedelta(days=1)
        assert end == T + timedelta(days=14)
        assert (end - start).days + 1 == POST_WINDOW_DAYS["final"] == 14

    def test_post_window_never_includes_t_preliminary(self):
        start, end = post_window(T, "preliminary")
        assert T not in date_range(start, end)

    def test_post_window_never_includes_t_final(self):
        start, end = post_window(T, "final")
        assert T not in date_range(start, end)


class TestComputeWindows:
    def test_bundles_pre_and_post_consistently_final(self):
        windows = compute_windows(T, "final")
        assert (windows.pre_start, windows.pre_end) == pre_window(T)
        assert (windows.post_start, windows.post_end) == post_window(T, "final")

    def test_bundles_pre_and_post_consistently_preliminary(self):
        windows = compute_windows(T, "preliminary")
        assert (windows.pre_start, windows.pre_end) == pre_window(T)
        assert (windows.post_start, windows.post_end) == post_window(T, "preliminary")


class TestDateRange:
    def test_inclusive_both_ends(self):
        result = date_range(T, T + timedelta(days=2))
        assert result == (T, T + timedelta(days=1), T + timedelta(days=2))

    def test_single_day(self):
        assert date_range(T, T) == (T,)

    def test_end_before_start_is_empty(self):
        assert date_range(T + timedelta(days=5), T) == ()


class TestMeanOverWindow:
    def test_simple_mean(self):
        daily = {
            T: Decimal(10),
            T + timedelta(days=1): Decimal(20),
            T + timedelta(days=2): Decimal(30),
        }
        result = mean_over_window(daily, T, T + timedelta(days=2))
        assert result == Decimal(20)

    def test_missing_days_skipped_not_zero_filled(self):
        # Only day 0 and day 2 have data; day 1 is absent entirely.
        daily = {T: Decimal(10), T + timedelta(days=2): Decimal(30)}
        result = mean_over_window(daily, T, T + timedelta(days=2))
        # If day 1 were zero-filled the mean would be (10+0+30)/3 == 13.33...
        assert result == Decimal(20)

    def test_none_values_skipped_not_zero_filled(self):
        daily = {
            T: Decimal(10),
            T + timedelta(days=1): None,
            T + timedelta(days=2): Decimal(30),
        }
        result = mean_over_window(daily, T, T + timedelta(days=2))
        assert result == Decimal(20)

    def test_no_data_at_all_returns_none_not_an_exception(self):
        result = mean_over_window({}, T, T + timedelta(days=2))
        assert result is None

    def test_exclude_drops_the_named_date_even_when_inside_the_window(self):
        # Regression-shaped fixture: T carries an extreme value that would
        # visibly move the mean if the exclude guard failed to drop it, even
        # though the window boundaries handed to mean_over_window here
        # deliberately span T (simulating a hypothetical off-by-one in a
        # caller's window construction).
        daily = {
            T - timedelta(days=2): Decimal(100),
            T - timedelta(days=1): Decimal(100),
            T: Decimal(999_999),  # extreme — would dominate any mean it leaks into
        }
        result = mean_over_window(daily, T - timedelta(days=2), T, exclude=T)
        assert result == Decimal(100)

    def test_without_exclude_the_same_extreme_value_does_move_the_mean(self):
        # Sanity check that the fixture above is actually extreme, i.e. the
        # previous test's green is not a vacuous pass.
        daily = {
            T - timedelta(days=2): Decimal(100),
            T - timedelta(days=1): Decimal(100),
            T: Decimal(999_999),
        }
        result = mean_over_window(daily, T - timedelta(days=2), T)
        assert result is not None
        assert result > Decimal(300_000)

    def test_exclude_outside_window_is_a_no_op(self):
        daily = {T: Decimal(10), T + timedelta(days=1): Decimal(20)}
        result = mean_over_window(daily, T, T + timedelta(days=1), exclude=T + timedelta(days=365))
        assert result == Decimal(15)

    def test_deterministic_across_repeated_calls(self):
        daily = {T + timedelta(days=i): Decimal(i) for i in range(-20, 21)}
        first = mean_over_window(daily, *pre_window(T), exclude=T)
        second = mean_over_window(daily, *pre_window(T), exclude=T)
        assert first == second

    def test_rate_values_average_as_arithmetic_mean_not_special_cased(self):
        # windows.py is metric-agnostic — a rate series (fractional values,
        # e.g. CTR) averages exactly like a count series. This module makes
        # no rate/count distinction; metric_map.py's MetricSpec.is_rate is
        # the single source of truth for that distinction downstream.
        daily = {
            T: Decimal("0.04"),
            T + timedelta(days=1): Decimal("0.05"),
            T + timedelta(days=2): Decimal("0.06"),
        }
        result = mean_over_window(daily, T, T + timedelta(days=2))
        assert result == Decimal("0.05")
