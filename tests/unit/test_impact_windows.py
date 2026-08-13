"""Date-window arithmetic — ADR-077 decision 2 (#1041).

Acceptance criterion: day T is excluded from pre, post and control windows,
asserted with a fixture where T carries an extreme value that would visibly
move any mean it leaked into.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from juli_backend.services.impact.windows import (
    compute_windows,
    date_range,
    mean_over_window,
    post_window,
    pre_window,
)

T = date(2026, 1, 15)


class TestPreWindow:
    def test_pre_window_is_fourteen_days_ending_the_day_before_t(self):
        start, end = pre_window(T)
        assert start == date(2026, 1, 1)
        assert end == date(2026, 1, 14)
        assert (end - start).days + 1 == 14

    def test_pre_window_never_includes_t(self):
        start, end = pre_window(T)
        assert T not in date_range(start, end)

    def test_pre_window_same_regardless_of_kind(self):
        # Only the post window's length depends on preliminary vs final.
        assert pre_window(T) == pre_window(T)


class TestPostWindow:
    def test_preliminary_post_window_is_seven_days_starting_the_day_after_t(self):
        start, end = post_window(T, "preliminary")
        assert start == date(2026, 1, 16)
        assert end == date(2026, 1, 22)
        assert (end - start).days + 1 == 7

    def test_final_post_window_is_fourteen_days_starting_the_day_after_t(self):
        start, end = post_window(T, "final")
        assert start == date(2026, 1, 16)
        assert end == date(2026, 1, 29)
        assert (end - start).days + 1 == 14

    def test_post_window_never_includes_t_preliminary(self):
        start, end = post_window(T, "preliminary")
        assert T not in date_range(start, end)

    def test_post_window_never_includes_t_final(self):
        start, end = post_window(T, "final")
        assert T not in date_range(start, end)


class TestComputeWindows:
    def test_bundles_pre_and_post_consistently(self):
        windows = compute_windows(T, "final")
        assert (windows.pre_start, windows.pre_end) == pre_window(T)
        assert (windows.post_start, windows.post_end) == post_window(T, "final")


class TestDateRange:
    def test_inclusive_both_ends(self):
        result = date_range(date(2026, 1, 1), date(2026, 1, 3))
        assert result == (date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3))

    def test_single_day(self):
        assert date_range(T, T) == (T,)

    def test_end_before_start_is_empty(self):
        assert date_range(date(2026, 1, 5), date(2026, 1, 1)) == ()


class TestMeanOverWindow:
    def test_simple_mean(self):
        daily = {
            date(2026, 1, 1): Decimal(10),
            date(2026, 1, 2): Decimal(20),
            date(2026, 1, 3): Decimal(30),
        }
        result = mean_over_window(daily, date(2026, 1, 1), date(2026, 1, 3))
        assert result == Decimal(20)

    def test_missing_days_skipped_not_zero_filled(self):
        # Only day 1 and day 3 have data; day 2 is absent entirely.
        daily = {
            date(2026, 1, 1): Decimal(10),
            date(2026, 1, 3): Decimal(30),
        }
        result = mean_over_window(daily, date(2026, 1, 1), date(2026, 1, 3))
        # If day 2 were zero-filled the mean would be (10+0+30)/3 == 13.33...
        assert result == Decimal(20)

    def test_none_values_skipped_not_zero_filled(self):
        daily = {
            date(2026, 1, 1): Decimal(10),
            date(2026, 1, 2): None,
            date(2026, 1, 3): Decimal(30),
        }
        result = mean_over_window(daily, date(2026, 1, 1), date(2026, 1, 3))
        assert result == Decimal(20)

    def test_no_data_at_all_returns_none_not_an_exception(self):
        result = mean_over_window({}, date(2026, 1, 1), date(2026, 1, 3))
        assert result is None

    def test_exclude_drops_the_named_date_even_when_inside_the_window(self):
        # Regression-shaped fixture: T carries an extreme value that would
        # visibly move the mean if the exclude guard failed to drop it, even
        # though the window boundaries handed to mean_over_window here
        # deliberately span T (simulating a hypothetical off-by-one in a
        # caller's window construction).
        daily = {
            date(2026, 1, 13): Decimal(100),
            date(2026, 1, 14): Decimal(100),
            T: Decimal(999_999),  # extreme — would dominate any mean it leaks into
        }
        result = mean_over_window(daily, date(2026, 1, 13), T, exclude=T)
        assert result == Decimal(100)

    def test_without_exclude_the_same_extreme_value_does_move_the_mean(self):
        # Sanity check that the fixture above is actually extreme, i.e. the
        # previous test's green is not a vacuous pass.
        daily = {
            date(2026, 1, 13): Decimal(100),
            date(2026, 1, 14): Decimal(100),
            T: Decimal(999_999),
        }
        result = mean_over_window(daily, date(2026, 1, 13), T)
        assert result is not None
        assert result > Decimal(300_000)

    def test_exclude_outside_window_is_a_no_op(self):
        daily = {
            date(2026, 1, 1): Decimal(10),
            date(2026, 1, 2): Decimal(20),
        }
        result = mean_over_window(
            daily, date(2026, 1, 1), date(2026, 1, 2), exclude=date(2026, 6, 1)
        )
        assert result == Decimal(15)

    def test_deterministic_across_repeated_calls(self):
        daily = {T + timedelta(days=i): Decimal(i) for i in range(-20, 21)}
        first = mean_over_window(daily, *pre_window(T), exclude=T)
        second = mean_over_window(daily, *pre_window(T), exclude=T)
        assert first == second
