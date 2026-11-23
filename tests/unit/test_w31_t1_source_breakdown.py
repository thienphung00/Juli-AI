"""W3.1 t1 (decision #28 Q2/Q3): a TikTok source without the A-34 breakdown is "—", never 0.

Pure: the channel table (Tổng quan) and the metric view (Phân tích) over synthetic source rows.
A day with the breakdown stores the five sources + the residual; a day without it stores the
residual alone (its whole đơn / GMV).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from juli_backend.services.metrics.registry import (
    REASON_SOURCE_BREAKDOWN_MISSING,
    Platform,
    counts_in_total,
    source_available,
    source_reason,
)
from juli_backend.services.shopee_analytics import funnel, metric_view
from juli_backend.services.shopee_analytics.channel_split import (
    breakdown_missing,
    split_rows,
)
from juli_backend.services.shopee_analytics.funnel import (
    FunnelRows,
    ScopeDay,
    SourceDay,
    base_from_rows,
)
from juli_backend.services.shopee_analytics.windows import Window

D = Decimal
D1, D2 = date(2026, 11, 10), date(2026, 11, 11)
W = Window(D1, D2)
TIKTOK = "tiktok"
SUMMED = ("the_san_pham_khac", "video", "live", "lien_ket")


def _with_breakdown(day, gap=(0, D(0))):
    spec = {
        "the_san_pham_khac": (2000, 100, 4, D(400_000)),
        "video": (800, 40, 2, D(200_000)),
        "live": (0, 0, 0, D(0)),
        "lien_ket": (300, 20, 1, D(300_000)),
        "trang_shop": (600, 30, 0, D(240_000)),
    }
    rows = [SourceDay(day, None, k, v, c, o, g, None) for k, (v, c, o, g) in spec.items()]
    rows.append(SourceDay(day, None, "chenh_lech_nguon", None, None, gap[0], gap[1], None))
    return rows


def _without_breakdown(day, orders, gmv):
    return [SourceDay(day, None, "chenh_lech_nguon", None, None, orders, gmv, None)]


def _window(*groups):
    sources = tuple(r for g in groups for r in g)
    days = {}
    for r in sources:
        o, g = days.get(r.day, (0, D(0)))
        days[r.day] = (o + (0 if r.source == "trang_shop" else r.orders),
                       g + (D(0) if r.source == "trang_shop" else r.gmv))  # fmt: skip
    shop_days = tuple(ScopeDay(d, None, o, g, None) for d, (o, g) in sorted(days.items()))
    return FunnelRows(W, sources, shop_days=shop_days)


def _by(rows):
    return {r["key"]: r for r in rows}


def test_registry_residual_is_on_tiktok_and_counts_in_its_total():
    assert source_available(Platform.tiktok, "chenh_lech_nguon")
    assert counts_in_total(Platform.tiktok, "chenh_lech_nguon")
    assert source_reason(Platform.tiktok, "chenh_lech_nguon") is None
    assert REASON_SOURCE_BREAKDOWN_MISSING == "source_breakdown_missing"


def test_a_window_without_any_breakdown_is_null_with_a_reason_and_the_gap_is_the_total():
    """V-2a: no 0 anywhere; Chênh lệch nguồn = the shop total."""
    rows = _window(_without_breakdown(D1, 3, D(500_000)), _without_breakdown(D2, 5, D(900_000)))
    base = base_from_rows(rows, "s")
    assert breakdown_missing(base, TIKTOK)
    table = _by(split_rows(base, platform=TIKTOK))
    for key in ("organic", "organic_card", "organic_shop", "organic_video", "organic_live",
                "affiliate"):  # fmt: skip
        r = table[key]
        assert all(r[m] is None for m in ("views", "clicks", "orders", "gmv", "aov", "ctr", "ctor"))
        assert r["unavailable"]["gmv"] == REASON_SOURCE_BREAKDOWN_MISSING
        assert r["share"] is None
    gap = table["chenh_lech_nguon"]
    assert (gap["orders"], gap["gmv"]) == (8, 1_400_000)
    assert gap["share"] == 1.0


def test_a_mixed_window_sums_the_breakdown_days_and_the_gap_takes_the_rest():
    """V-2b: sources = sum over the days WITH the breakdown; sources + gap = shop total."""
    rows = _window(_with_breakdown(D1, gap=(1, D(50_000))), _without_breakdown(D2, 8, D(900_000)))
    base = base_from_rows(rows, "s")
    assert not breakdown_missing(base, TIKTOK)
    table = _by(split_rows(base, platform=TIKTOK))
    assert table["organic_card"]["gmv"] == 400_000 and table["organic_video"]["gmv"] == 200_000
    assert table["organic_live"]["gmv"] == 0 and "unavailable" not in table["organic_card"]
    assert table["affiliate"]["gmv"] == 300_000
    gap = table["chenh_lech_nguon"]
    assert (gap["orders"], gap["gmv"]) == (9, 950_000)
    total_gmv = 900_000 + 950_000  # D1: 4 sources 900k + gap 50k; D2: all in the gap
    assert 400_000 + 200_000 + 0 + 300_000 + gap["gmv"] == 1_850_000 == total_gmv
    assert 4 + 2 + 0 + 1 + gap["orders"] == 16 == 8 + 8
    assert table["organic_shop"]["gmv"] == 240_000, "Tab cửa hàng stays outside the sum"


def test_a_window_with_the_breakdown_on_every_day_has_no_gap_row():
    """Q5 rule: a zero gap is no row ("0 ₫ Chênh lệch nguồn" never shows)."""
    rows = _window(_with_breakdown(D1), _with_breakdown(D2))
    table = _by(split_rows(base_from_rows(rows, "s"), platform=TIKTOK))
    assert "chenh_lech_nguon" not in table


def test_shopee_rows_are_unchanged():
    rows = _window(_with_breakdown(D1, gap=(1, D(50_000))))
    table = _by(split_rows(base_from_rows(rows, "s")))
    assert "chenh_lech_nguon" not in table and "unavailable" not in table["organic_card"]
    assert not breakdown_missing(base_from_rows(rows, "s"), "shopee")


def _view(now, before, platform=TIKTOK, metric="gmv"):
    return metric_view.assemble(
        metric,
        now=now,
        before=before,
        shop_key="s",
        ad_types_now=None,
        ad_types_before=None,
        item_ids=(),
        names={},
        margin_now={},
        margin_before={},
        platform=platform,
    )


def test_phan_tich_has_null_channels_and_the_gap_row_without_a_breakdown():
    now = _window(_without_breakdown(D1, 3, D(500_000)))
    before = FunnelRows(Window(D1 - timedelta(days=2), D1 - timedelta(days=1)), ())
    body = _view(now, before)
    chans = {c["key"]: c for c in body["channels"]}
    for key in ("the_san_pham", "trang_shop", "video", "live", "lien_ket"):
        assert chans[key]["now"] is None, key
    gap = chans["chenh_lech_nguon"]
    assert gap["now"] == 500_000
    assert body["total"]["now"] == 500_000, "the total holds the gap"


def test_phan_tich_has_no_gap_row_with_a_full_breakdown_and_shopee_never():
    now = _window(_with_breakdown(D1))
    before = FunnelRows(Window(D1 - timedelta(days=2), D1 - timedelta(days=1)), ())
    assert "chenh_lech_nguon" not in {c["key"] for c in _view(now, before)["channels"]}
    assert "chenh_lech_nguon" not in {
        c["key"] for c in _view(now, before, platform="shopee")["channels"]
    }


def test_funnel_base_lists_every_source_so_the_helper_reads_traffic_not_presence():
    base = base_from_rows(_window(_without_breakdown(D1, 1, D(10))), "s")
    assert {s.source for s in base.sources} >= set(SUMMED)
    assert funnel.known_total(base, "views") is None
