"""KPI freshness must describe the data, not the compute (#853).

`computed_at` answers "when did gold last run". Once a Partner fetch failure stops
aborting the whole job, gold keeps running on schedule while silver.orders is frozen,
so `computed_at` stays fresh forever and says nothing true about the numbers. These
tests pin the separate signal that does: how old the newest source record is.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from juli_backend.services.analytics_kpi_masking import mask_public_analytics_envelope
from juli_backend.services.gold_kpi_envelope_contract import (
    KPI_SOURCE,
    SOURCE_STALE_AFTER_SECONDS,
    build_source_freshness,
)

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
ORDERS_THRESHOLD = SOURCE_STALE_AFTER_SECONDS["silver.orders"]


def test_fresh_source_is_not_stale():
    entry = build_source_freshness(
        source="silver.orders", as_of=NOW - timedelta(minutes=30), computed_at=NOW, row_count=10
    )

    assert entry["stale"] is False
    assert entry["age_seconds"] == 1800
    assert entry["row_count"] == 10
    assert entry["as_of"] == (NOW - timedelta(minutes=30)).isoformat()


def test_source_past_the_threshold_is_stale():
    entry = build_source_freshness(
        source="silver.orders",
        as_of=NOW - timedelta(seconds=ORDERS_THRESHOLD + 1),
        computed_at=NOW,
        row_count=1000,
    )

    assert entry["stale"] is True


def test_threshold_boundary_is_not_stale():
    entry = build_source_freshness(
        source="silver.orders",
        as_of=NOW - timedelta(seconds=ORDERS_THRESHOLD),
        computed_at=NOW,
        row_count=1,
    )

    assert entry["stale"] is False


def test_no_rows_is_not_reported_as_stale():
    """Absent data and stalled data are different faults and need different responses."""
    entry = build_source_freshness(source="silver.orders", as_of=None, computed_at=NOW, row_count=0)

    assert entry["as_of"] is None
    assert entry["age_seconds"] is None
    assert entry["stale"] is False


def test_naive_source_timestamps_are_treated_as_utc():
    """Order.update_time is `timestamp without time zone` holding UTC — comparing it
    to an aware computed_at raises unless it is normalised."""
    entry = build_source_freshness(
        source="silver.orders",
        as_of=datetime(2026, 8, 8, 11, 0),  # naive, no tzinfo
        computed_at=NOW,
        row_count=5,
    )

    assert entry["age_seconds"] == 3600
    assert entry["stale"] is False


def test_clock_skew_does_not_produce_negative_age():
    entry = build_source_freshness(
        source="silver.orders", as_of=NOW + timedelta(hours=2), computed_at=NOW, row_count=3
    )

    assert entry["age_seconds"] == 0
    assert entry["stale"] is False


def test_every_demo_kpi_is_mapped_to_a_source():
    from juli_backend.services.gold_kpi_envelope_contract import DEMO_MAIN_KPI_METRIC_IDS

    assert set(KPI_SOURCE) == set(DEMO_MAIN_KPI_METRIC_IDS)


def test_ctor_and_live_hours_do_not_depend_on_the_orders_feed():
    """The whole reason a TikTok outage must not block gold: these two read local rows."""
    assert KPI_SOURCE["ctor"] == "analytics_performance_intervals"
    assert KPI_SOURCE["live_hours"] == "analytics_performance_intervals"
    assert KPI_SOURCE["gmv_tiktok"] == "silver.orders"


def test_freshness_survives_masking():
    """meta is popped wholesale by the masker, so freshness must not live there."""
    payload = {
        "envelope_version": 1,
        "kind": "analytics",
        "shop_id": str(uuid.uuid4()),
        "computed_at": NOW.isoformat(),
        "currency": "VND",
        "identity": {"shop_display_name": "Test Shop"},
        "kpis": {
            "gmv_tiktok": {
                "availability": "available",
                "label": "GMV (TikTok)",
                "value": 1.0,
                "series": [],
                "source": "silver.orders",
                "as_of": NOW.isoformat(),
                "stale": True,
            }
        },
        "source_freshness": {
            "silver.orders": {
                "as_of": NOW.isoformat(),
                "age_seconds": 0,
                "stale": True,
                "row_count": 1,
            }
        },
        "meta": {"source_partitions": [], "notes": []},
    }

    masked = mask_public_analytics_envelope(payload)

    assert "meta" not in masked, "masking contract changed"
    assert masked["source_freshness"]["silver.orders"]["stale"] is True
    assert masked["kpis"]["gmv_tiktok"]["stale"] is True
    assert masked["kpis"]["gmv_tiktok"]["as_of"] == NOW.isoformat()


def test_daily_interval_rows_get_a_longer_threshold_than_the_hourly_feed():
    """A day-grain row is up to 24h old the moment it lands; the orders threshold
    would flag a healthy backfill every afternoon."""
    todays_row = NOW.replace(hour=0, minute=0)

    orders = build_source_freshness(
        source="silver.orders", as_of=todays_row, computed_at=NOW, row_count=1
    )
    intervals = build_source_freshness(
        source="analytics_performance_intervals",
        as_of=todays_row,
        computed_at=NOW,
        row_count=1,
    )

    assert orders["stale"] is True
    assert intervals["stale"] is False
    assert intervals["stale_after_seconds"] > orders["stale_after_seconds"]


def test_intervals_frozen_for_a_week_are_still_caught():
    entry = build_source_freshness(
        source="analytics_performance_intervals",
        as_of=NOW - timedelta(days=7),
        computed_at=NOW,
        row_count=4424,
    )

    assert entry["stale"] is True
