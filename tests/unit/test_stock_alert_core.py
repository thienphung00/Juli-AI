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


def test_plain_average_below_ten_orders():
    units = _days(30, 1.0) | _days(60, 4.0, start=31)
    u = fc.base_rate(units, TODAY, orders_30=5)
    assert abs(u - (30 * 1 + 60 * 4) / 90) < 1e-9


def test_weighted_average_with_ten_orders():
    units = _days(30, 1.0) | _days(60, 4.0, start=31)
    u = fc.base_rate(units, TODAY, orders_30=10)
    assert abs(u - (2 * 30 * 1 + 60 * 4) / (2 * 30 + 60)) < 1e-9


def test_zero_stock_and_mega_days_are_left_out():
    units = _days(90, 2.0)
    mega = date(2026, 11, 11)
    units[mega] = 50.0
    zero = {TODAY - timedelta(days=2), TODAY - timedelta(days=3)}
    for d in zero:
        units[d] = 0.0
    assert fc.base_rate(units, TODAY, orders_30=3, zero_stock_days=zero) == 2.0
    assert fc.is_mega_sale_day(mega) and not fc.is_mega_sale_day(date(2026, 11, 15))


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


def test_basis_prefers_sellable():
    assert sb.basis(5, 9) == 5 and sb.basis(None, 9) == 9 and sb.basis(None, None) is None


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
