"""Part S: the pure stock-alert core (forecast, stock basis, eligibility). No database."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from juli_backend.services.stock_alert import eligibility as el
from juli_backend.services.stock_alert import forecast as fc
from juli_backend.services.stock_alert import stock_basis as sb

TODAY = date(2026, 11, 15)


def _days(n: int, units: float, *, start: int = 1) -> dict[date, float]:
    return {TODAY - timedelta(days=b): units for b in range(start, start + n)}


# --------------------------------------------------------------------------- forecast


def _sale(d: date) -> bool:
    return fc.is_sale_day(d)


def test_plain_average_below_ten_orders():
    units = _days(30, 1.0) | _days(60, 4.0, start=31)
    kept = [d for d in units if not _sale(d)]
    u = fc.base_rate(units, TODAY, orders_30=5)
    assert abs(u - sum(units[d] for d in kept) / len(kept)) < 1e-9


def test_weighted_average_with_ten_orders():
    units = _days(30, 1.0) | _days(60, 4.0, start=31)
    kept = [d for d in units if not _sale(d)]
    w = {d: 2 if (TODAY - d).days <= 30 else 1 for d in kept}
    u = fc.base_rate(units, TODAY, orders_30=10)
    assert abs(u - sum(w[d] * units[d] for d in kept) / sum(w.values())) < 1e-9


def test_sale_calendar_double_day_15th_25th_and_the_day_after():
    for d in (date(2026, 1, 1), date(2026, 9, 9), date(2026, 11, 11), date(2026, 12, 12)):
        assert fc.is_sale_day(d) and fc.is_sale_day(d + timedelta(days=1))
    for d in (date(2026, 3, 15), date(2026, 3, 16), date(2026, 7, 25), date(2026, 7, 26)):
        assert fc.is_sale_day(d)
    for d in (date(2026, 11, 13), date(2026, 3, 17), date(2026, 7, 27), date(2026, 9, 11)):
        assert not fc.is_sale_day(d)
    assert fc.SALE_CALENDAR.monthly_days == (15, 25) and fc.SALE_CALENDAR.spill_days == 1


def test_sale_days_do_not_count_toward_the_base():
    units = _days(90, 2.0)
    for d in list(units):
        if _sale(d):
            units[d] = 50.0
    assert fc.base_rate(units, TODAY, orders_30=3) == 2.0


def test_zero_stock_days_never_count():
    units = _days(90, 2.0)
    zero = {TODAY - timedelta(days=2), TODAY - timedelta(days=3)}
    for d in zero:
        units[d] = 0.0
    assert fc.base_rate(units, TODAY, orders_30=3, zero_stock_days=zero) == 2.0


def test_own_spikes_above_three_times_the_median_are_dropped():
    units = _days(90, 2.0)
    spike = date(2026, 11, 4)  # not a calendar day
    assert not _sale(spike)
    units[spike] = 7.0  # > 3 x 2
    units[date(2026, 11, 5)] = 6.0  # = 3 x 2: kept
    kept = fc.kept_days(units, TODAY)
    assert spike not in kept and date(2026, 11, 5) in kept
    n = len(kept)
    assert abs(fc.base_rate(units, TODAY, orders_30=3) - (2.0 * (n - 1) + 6.0) / n) < 1e-9


def _history_with_kept(n: int) -> int:
    """The shortest history (days) whose non-sale days number ``n``."""
    days = 0
    while sum(1 for b in range(1, days + 1) if not _sale(TODAY - timedelta(days=b))) < n:
        days += 1
    return days


def test_spike_guard_needs_fourteen_kept_days():
    days = _history_with_kept(14)
    units = {TODAY - timedelta(days=b): 1.0 for b in range(1, days + 1)}
    first = TODAY - timedelta(days=days)
    big = next(d for d in units if not _sale(d))
    units[big] = 10.0
    # 14 non-sale days: the guard runs and drops the spike; 13 remain (no fallback after the guard)
    got = fc.kept_days(units, TODAY, first_day=first)
    assert big not in got and len(got) == 13
    # 13 non-sale days: every in-stock day counts, and the guard still drops the spike from that set
    short = _history_with_kept(13)
    few = {TODAY - timedelta(days=b): 1.0 for b in range(1, short + 1)}
    spike = next(d for d in few if not _sale(d))
    few[spike] = 10.0
    got = fc.kept_days(few, TODAY, first_day=TODAY - timedelta(days=short))
    assert spike not in got and any(_sale(d) for d in got)
    # one more ordinary day: 15 kept, the spike is dropped and 14 remain
    longer = _history_with_kept(15)
    units |= {TODAY - timedelta(days=b): 1.0 for b in range(days + 1, longer + 1)}
    got = fc.kept_days(units, TODAY, first_day=TODAY - timedelta(days=longer))
    assert big not in got and len(got) == 14


def test_fallback_to_every_in_stock_day_when_exclusions_leave_too_few():
    units = {TODAY - timedelta(days=b): 3.0 for b in range(1, 11)}  # 10 days of history
    first = TODAY - timedelta(days=10)
    zero = {TODAY - timedelta(days=1)}
    got = fc.kept_days(units, TODAY, zero_stock_days=zero, first_day=first)
    assert len(got) == 9 and TODAY - timedelta(days=1) not in got  # out-of-stock still excluded
    assert any(_sale(d) for d in got)  # the sale days are back in
    assert fc.base_rate(units, TODAY, orders_30=3, first_day=first, zero_stock_days=zero) == 3.0


def test_days_before_first_day_do_not_count():
    units = _days(10, 3.0)
    u = fc.base_rate(units, TODAY, orders_30=3, first_day=TODAY - timedelta(days=10))
    assert u == 3.0


def test_days_left_walks_day_by_day():
    out = fc.days_left(42, 6.0, TODAY)
    assert out.days_left == 7 and out.runs_out_on == date(2026, 11, 22)


def test_no_sales_no_forecast():
    assert fc.days_left(10, 0.0, TODAY).days_left is None


def test_card_adds_units_only_on_its_days():
    card = fc.CardEffect(TODAY + timedelta(days=2), TODAY + timedelta(days=4), 4.0)
    # 2,2,6,6,6 -> 22 after five days
    out = fc.days_left(22, 2.0, TODAY, [card])
    assert out.days_left == 5
    assert fc.days_left(22, 2.0, TODAY).days_left == 11


def test_card_beyond_horizon_is_ignored():
    far = fc.CardEffect(TODAY + timedelta(days=40), TODAY + timedelta(days=60), 100.0)
    assert fc.days_left(100, 2.0, TODAY, [far]).days_left == 50


# -------------------------------------------------------------------------- stock basis


def _utc(local_day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(local_day.year, local_day.month, local_day.day, hour, minute) - timedelta(
        hours=7
    )


NOW = _utc(TODAY, 7)


def test_basis_is_the_kho_hang_figure():
    """ORY 2026-11-15: ``sellable`` (advanced / "Gói Sẵn Giao Nhanh" stock) was 0 on every
    variation while Seller Centre's Kho hàng read 5-10, and the e-mail said "Đã hết hàng"."""
    assert sb.basis(0, 7) == 7 and sb.basis(5, 9) == 9
    assert sb.basis(4, None) == 4 and sb.basis(None, None) is None


def test_fresh_read_today_after_six_is_used_as_is():
    read = sb.Read(_utc(TODAY, 6, 31), 42)
    got = sb.stock_now(read, NOW, units_since=3, orders_since=2)
    assert got is not None and got.stock == 42 and got.fresh


def test_older_read_subtracts_orders_since():
    read = sb.Read(_utc(TODAY - timedelta(days=1), 21, 10), 10)
    got = sb.stock_now(read, NOW, units_since=12, orders_since=5)
    assert got is not None and got.stock == 0 and got.deducted_orders == 5


def test_read_before_six_today_is_not_fresh():
    read = sb.Read(_utc(TODAY, 5, 59), 10)
    got = sb.stock_now(read, NOW, units_since=1, orders_since=1)
    assert got is not None and got.stock == 9 and not got.fresh


def test_read_older_than_48_hours_is_no_read():
    read = sb.Read(NOW - timedelta(hours=48), 10)
    assert sb.stock_now(read, NOW) is None
    assert sb.stock_now(None, NOW) is None


def test_zero_days_and_zero_since():
    reads = [
        sb.Read(_utc(TODAY - timedelta(days=5), 6), 3),
        sb.Read(_utc(TODAY - timedelta(days=4), 6), 0),
        sb.Read(_utc(TODAY - timedelta(days=2), 6), 0),
    ]
    zeros = sb.zero_days(reads, TODAY - timedelta(days=5), TODAY - timedelta(days=1))
    assert zeros == {TODAY - timedelta(days=d) for d in (4, 3, 2, 1)}
    assert sb.zero_since(reads) == TODAY - timedelta(days=4)
    assert sb.zero_since(reads[:1]) is None


# -------------------------------------------------------------------------- eligibility


def _facts(**kw) -> el.SkuFacts:
    base = {
        "item_id": "1",
        "model_id": "11",
        "product_name": "Áo",
        "variation_name": "Đỏ",
        "listing_status": None,
        "orders_30": 5,
        "orders_total": 20,
        "history_days": 90,
        "stock": 42,
        "base": 6.0,
    }
    base.update(kw)
    return el.SkuFacts(**base)


def test_eligibility_rules():
    assert el.is_eligible(_facts(), TODAY)
    assert not el.is_eligible(_facts(listing_status="unlisted"), TODAY)
    assert not el.is_eligible(_facts(orders_30=0), TODAY)
    assert not el.is_eligible(_facts(orders_total=2, history_days=10), TODAY)
    assert el.is_eligible(_facts(orders_total=2, history_days=30), TODAY)
    old_zero = _facts(stock=0, zero_since=TODAY - timedelta(days=8))
    assert not el.is_eligible(old_zero, TODAY)


def test_triggers_days_card_and_out_of_stock():
    assert el.evaluate(_facts(), TODAY).reason == el.REASON_DAYS
    assert el.evaluate(_facts(stock=60), TODAY) is None  # 10 days
    card_end = TODAY + timedelta(days=12)
    assert el.evaluate(_facts(stock=60, card_ends=(card_end,)), TODAY).reason == el.REASON_CARD
    out = el.evaluate(_facts(stock=0, zero_since=TODAY - timedelta(days=2)), TODAY)
    assert out.out_of_stock and out.out_since == TODAY - timedelta(days=2)
    assert el.evaluate(_facts(stock=60), TODAY, alert_days=10).reason == el.REASON_DAYS


def test_sort_out_of_stock_then_days_then_rate():
    rows = el.alerts(
        [
            _facts(model_id="a", stock=12, base=6.0),  # 2 days
            _facts(model_id="b", stock=0, zero_since=TODAY),
            _facts(model_id="c", stock=4, base=2.0),  # 2 days, slower
            _facts(model_id="d", stock=3, base=3.0),  # 1 day
        ],
        TODAY,
    )
    assert [r.facts.model_id for r in rows] == ["b", "d", "a", "c"]


def test_untracked_variations_get_no_alert():
    rows = el.alerts([_facts(model_id="a"), _facts(model_id="b")], TODAY, tracked={"1:b"})
    assert [r.facts.model_id for r in rows] == ["b"]
