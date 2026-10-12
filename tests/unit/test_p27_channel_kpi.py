"""Fast track P27 (D32): a card's KPI is set and measured on the lever's channel.

Synthetic fixtures only. One test (or a small group) per rule: the lever ->
channel map and seller copy; the per-channel projection of the stored A-33
breakdown; the KPI window on the channel and each fallback to all channels;
the plan's card (narrower band, channel confidence, channel medians, channel
GMV); the re-score of a pre-D29 card; the day-14 measurement on the same
channel; the read model / API contract carrying ``kpi.channel``.
"""

from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest

from juli_backend.services.action_cards.optimize_product_cards import (
    _channel_traffic,
    d29_payload,
)
from juli_backend.services.optimize_product.config import StageDiagnosisConfig
from juli_backend.services.optimize_product.daily_funnel import (
    ChannelTraffic,
    ProductDay,
    product_funnel,
)
from juli_backend.services.optimize_product.decision_cards import (
    CatalogProduct,
    plan_shop_cards,
)
from juli_backend.services.optimize_product.kpi_channel import (
    CHANNEL_PRODUCT_CARD,
    CHANNEL_TOTAL,
    FALLBACK_LOW_DATA,
    FALLBACK_METRIC_NOT_PER_CHANNEL,
    FALLBACK_NO_CHANNEL_DATA,
    LEVER_CHANNEL,
    channel_days,
    channel_gmv_per_day,
    kpi_window,
    lever_channel,
    measured_on_vi,
)
from juli_backend.services.optimize_product.listing_signals import Evidence, EvidenceSource
from juli_backend.services.optimize_product.rescore import rescore_legacy_payload
from juli_backend.services.optimize_product.tunables import DiagTunables
from juli_backend.services.optimize_product.volatility import select_window

AS_OF = date(2026, 10, 6)
CONFIG = StageDiagnosisConfig()
TUNABLES = DiagTunables()


def _mixed(
    days: int = 60,
    *,
    seed: int = 7,
    card_impressions: float = 3000,
    card_ctr: float = 0.05,
    card_ctr_after: float = 0.03,
    change_days: int = 14,
    with_channels: bool = True,
) -> list[ProductDay]:
    """A product sold on Thẻ sản phẩm (steady) and Video (noisy CTR every day).

    The last ``change_days`` days carry ``card_ctr_after`` on the product card.
    SKU orders = all clicks × 6 %, AOV 200.000 ₫; channel GMV splits the same way.
    """
    rng = random.Random(seed)
    rows: list[ProductDay] = []
    for offset in range(days):
        ctr = card_ctr_after if offset < change_days else card_ctr
        c_imp = round(card_impressions * (1 + rng.uniform(-0.1, 0.1)))
        c_clicks = round(c_imp * ctr * (1 + rng.uniform(-0.08, 0.08)))
        v_imp = round(3000 * (1 + rng.uniform(-0.4, 0.4)))
        v_clicks = round(v_imp * rng.uniform(0.005, 0.045))
        clicks = c_clicks + v_clicks
        orders = round(clicks * 0.06, 2)
        gmv = round(orders * 200_000)
        c_gmv = round(c_clicks * 0.06 * 200_000)
        rows.append(
            ProductDay(
                day=AS_OF - timedelta(days=offset),
                impressions=Decimal(c_imp + v_imp),
                clicks=Decimal(clicks),
                sku_orders=Decimal(str(orders)),
                items_sold=Decimal(str(orders)),
                gmv=Decimal(gmv),
                channels=(
                    {
                        "PRODUCT_CARD": ChannelTraffic(
                            Decimal(c_imp), Decimal(c_clicks), Decimal(c_gmv)
                        ),
                        "VIDEO": ChannelTraffic(
                            Decimal(v_imp), Decimal(v_clicks), Decimal(gmv - c_gmv)
                        ),
                    }
                    if with_channels
                    else {}
                ),
            )
        )
    return sorted(rows, key=lambda r: r.day)


def _plan(daily: dict[str, list[ProductDay]], evidence: dict[str, list[Evidence]]):
    funnels = [
        product_funnel(pid, pid, rows, as_of=AS_OF, config=CONFIG) for pid, rows in daily.items()
    ]
    catalog = {
        pid: CatalogProduct(
            pid, f"Sản phẩm {pid} có tiêu đề đủ dài để không bị đánh dấu", "ACTIVATE"
        )
        for pid in daily
    }
    return plan_shop_cards(
        funnels,
        catalog,
        CONFIG,
        daily=daily,
        as_of=AS_OF,
        tunables=TUNABLES,
        tiktok_evidence=evidence,
    )


def _shop(target: list[ProductDay]) -> dict[str, list[ProductDay]]:
    daily = {"p1": target}
    for seed, pid in enumerate(("p2", "p3", "p4"), start=20):
        daily[pid] = _mixed(seed=seed, card_ctr_after=0.05)
    return daily


def _tiktok(*codes: str) -> list[Evidence]:
    return [Evidence(code, EvidenceSource.TIKTOK) for code in codes]


# =========================================================================== map + copy


def test_listing_levers_act_on_the_product_card_and_price_levers_everywhere():
    assert {k for k, v in LEVER_CHANNEL.items() if v == CHANNEL_PRODUCT_CARD} == {
        "cover_image",
        "title",
        "description",
    }
    for lever in ("product_discount", "flash_sale", "shipping_discount", "buy_more_save_more"):
        assert lever_channel(lever) == CHANNEL_TOTAL
    assert lever_channel(None) == CHANNEL_TOTAL
    assert lever_channel("video_script") == CHANNEL_TOTAL


def test_seller_copy_names_the_channel_without_backend_terms():
    assert measured_on_vi("product_card") == "đo trên kênh Thẻ sản phẩm"
    assert measured_on_vi("video") == "đo trên kênh Video"
    assert measured_on_vi("total") == "đo trên tất cả kênh"
    assert measured_on_vi(None) == "đo trên tất cả kênh"


# =========================================================================== projection


def test_channel_projection_reads_the_breakdown_and_skips_unknown_days():
    day = date(2026, 10, 1)
    rows = [
        ProductDay(
            day=day,
            impressions=Decimal(5000),
            clicks=Decimal(150),
            sku_orders=Decimal(9),
            gmv=Decimal(1_800_000),
            channels={
                "PRODUCT_CARD": ChannelTraffic(Decimal(2000), Decimal(100), Decimal(1_200_000))
            },
        ),
        # A breakdown without PRODUCT_CARD: the channel showed nothing that day.
        ProductDay(
            day=day + timedelta(days=1),
            impressions=Decimal(900),
            clicks=Decimal(20),
            channels={"VIDEO": ChannelTraffic(Decimal(900), Decimal(20))},
        ),
        # No breakdown at all: unknown, left out (never a zero day).
        ProductDay(day=day + timedelta(days=2), impressions=Decimal(800), clicks=Decimal(30)),
    ]
    projected = channel_days(rows, CHANNEL_PRODUCT_CARD)
    assert [(r.day, r.impressions, r.clicks, r.gmv, r.sku_orders) for r in projected] == [
        (day, Decimal(2000), Decimal(100), Decimal(1_200_000), Decimal(0)),
        (day + timedelta(days=1), Decimal(0), Decimal(0), Decimal(0), Decimal(0)),
    ]
    assert channel_days(rows, CHANNEL_TOTAL) == rows
    gmv = channel_gmv_per_day(rows, CHANNEL_PRODUCT_CARD, day + timedelta(days=1), 2)
    assert gmv == pytest.approx(600_000)


def test_stored_rows_become_channel_traffic():
    row = SimpleNamespace(
        traffic_breakdown={
            "A34_TOTAL": {"add_cart_count": 4, "clicks": 50},
            "PRODUCT_CARD": {"impressions": 2000, "ctr": 0.05, "clicks": 100},
            "VIDEO": {"impressions": 900, "ctr": None, "clicks": None},
        },
        sales_breakdown={
            "PRODUCT_CARD": {"gmv": "1200000.00", "items_sold": 6},
            "LIVE": {"gmv": "300000.00", "items_sold": 1},
        },
    )
    channels = _channel_traffic(cast(Any, row))
    assert channels["PRODUCT_CARD"] == ChannelTraffic(
        Decimal(2000), Decimal(100), Decimal("1200000.00")
    )
    # A content type with no click count is unknown; one with sales only has zero traffic.
    assert "VIDEO" not in channels
    assert channels["LIVE"] == ChannelTraffic(gmv=Decimal("300000.00"))
    empty = SimpleNamespace(traffic_breakdown=None, sales_breakdown=None)
    assert _channel_traffic(cast(Any, empty)) == {}


# =========================================================================== KPI window + fallback


def test_kpi_window_uses_the_levers_channel_when_it_has_enough_clicks():
    rows = _mixed()
    kw = kpi_window(rows, as_of=AS_OF, metric="ctr", lever="cover_image", tunables=TUNABLES)
    assert kw.channel == CHANNEL_PRODUCT_CARD and kw.fallback is None
    assert kw.window.events is not None and kw.window.events >= TUNABLES.min_events
    total = select_window(rows, AS_OF, "ctr", TUNABLES)
    # The steady product card has a far narrower window-mean band than the mixture.
    assert kw.window.band_pct is not None and total.band_pct is not None
    assert kw.window.band_pct < total.band_pct / 3


def test_a_thin_channel_falls_back_to_all_channels():
    # ~0,4 product-card clicks a day: under 30 clicks even on the 60-day window.
    rows = _mixed(card_impressions=20, card_ctr=0.02, card_ctr_after=0.02)
    kw = kpi_window(rows, as_of=AS_OF, metric="ctr", lever="title", tunables=TUNABLES)
    assert kw.channel == CHANNEL_TOTAL
    assert kw.requested == CHANNEL_PRODUCT_CARD
    assert kw.fallback == FALLBACK_LOW_DATA
    assert kw.window == select_window(rows, AS_OF, "ctr", TUNABLES)


def test_no_breakdown_and_order_metrics_stay_on_all_channels():
    plain = _mixed(with_channels=False)
    kw = kpi_window(plain, as_of=AS_OF, metric="ctr", lever="cover_image", tunables=TUNABLES)
    assert (kw.channel, kw.fallback) == (CHANNEL_TOTAL, FALLBACK_NO_CHANNEL_DATA)
    # CTOR needs per-channel SKU orders, which TikTok's breakdown does not carry.
    kw = kpi_window(_mixed(), as_of=AS_OF, metric="ctor", lever="description", tunables=TUNABLES)
    assert (kw.channel, kw.fallback) == (CHANNEL_TOTAL, FALLBACK_METRIC_NOT_PER_CHANNEL)
    # A price lever acts everywhere: all channels by design, not a fallback.
    kw = kpi_window(_mixed(), as_of=AS_OF, metric="ctr", lever="flash_sale", tunables=TUNABLES)
    assert (kw.channel, kw.fallback) == (CHANNEL_TOTAL, None)


# =========================================================================== the plan's card


def test_a_cover_image_card_gets_its_kpi_band_and_confidence_on_the_product_card():
    daily = _shop(_mixed())
    plan = _plan(daily, {"p1": _tiktok("MAIN_IMG_DUPLICATE")})
    [card] = [p for p in plan.proposals if p.product_id == "p1"]
    assert card.target_metric == "ctr" and card.kpi is not None
    assert card.kpi.channel == CHANNEL_PRODUCT_CARD
    channel = kpi_window(
        daily["p1"], as_of=AS_OF, metric="ctr", lever="cover_image", tunables=TUNABLES
    ).window
    assert card.kpi.current == pytest.approx(channel.value)
    assert card.kpi.band_pct == pytest.approx(channel.band_pct)
    # The clamp is 1–3 bands of the CHANNEL band.
    band_abs = card.kpi.current * card.kpi.band_pct / 100
    assert card.kpi.current + band_abs <= card.kpi.target_min + 1e-12
    assert card.kpi.target_max <= card.kpi.current + 3 * band_abs + 1e-12
    # Steady product-card traffic: high confidence, although the product's
    # all-channel traffic is noisier.
    assert card.confidence == "high"
    assert card.recoverable_basis is not None
    assert card.recoverable_basis["channel"] == CHANNEL_PRODUCT_CARD
    assert card.recoverable_basis["current_rate"] == pytest.approx(channel.value)

    payload = d29_payload(card)
    assert payload["kpi"]["channel"] == CHANNEL_PRODUCT_CARD
    assert payload["confidence"] == "high"


def test_before_and_after_band_on_a_synthetic_product():
    """The P27 report's example: all-channel vs product-card CTR KPI for one card."""
    rows = _mixed()
    total = select_window(rows, AS_OF, "ctr", TUNABLES)
    channel = kpi_window(rows, as_of=AS_OF, metric="ctr", lever="cover_image", tunables=TUNABLES)
    assert total.value is not None and total.band_pct is not None
    assert channel.window.value is not None and channel.window.band_pct is not None
    # Before (all channels): CTR ≈ 2,55 %, band ≈ ±7,2 % -> clamp 2,74–3,10 %.
    assert total.value == pytest.approx(0.0255, abs=5e-4)
    assert total.band_pct == pytest.approx(7.16, abs=0.05)
    # After (Thẻ sản phẩm): CTR ≈ 2,96 %, band ≈ ±1,6 % -> clamp 3,00–3,10 %.
    assert channel.window.value == pytest.approx(0.0296, abs=5e-4)
    assert channel.window.band_pct == pytest.approx(1.59, abs=0.05)


def test_the_cards_gmv_is_the_channels_gmv():
    daily = _shop(_mixed())
    plan = _plan(daily, {"p1": _tiktok("MAIN_IMG_DUPLICATE")})
    [card] = [p for p in plan.proposals if p.product_id == "p1"]
    assert card.kpi is not None and card.gmv_estimate is not None
    days = card.kpi.window_days
    channel_gmv = channel_gmv_per_day(daily["p1"], CHANNEL_PRODUCT_CARD, AS_OF, days)
    expected = channel_gmv * max(card.kpi.target / card.kpi.current - 1, 0.0)
    assert float(card.recoverable_gmv_per_day) == pytest.approx(expected)


def test_a_thin_product_card_card_falls_back_to_all_channels_in_the_plan():
    daily = _shop(_mixed(with_channels=False))
    plan = _plan(daily, {"p1": _tiktok("MAIN_IMG_DUPLICATE")})
    [card] = [p for p in plan.proposals if p.product_id == "p1"]
    assert card.kpi is not None and card.kpi.channel == CHANNEL_TOTAL
    total = select_window(daily["p1"], AS_OF, "ctr", TUNABLES)
    assert card.kpi.band_pct == pytest.approx(total.band_pct)
    # All-channel: the product's own confidence (D29.6), unchanged.
    assert card.confidence == card.assessment.confidence


# =========================================================================== re-score


def _legacy_payload(lever: str, stage_rate: str = "ctr") -> dict:
    return {
        "workflow_name": "Tối ưu sản phẩm",
        "diagnosis": {
            "tiktok_product_id": "p1",
            "lever": {"code": lever},
            "stage": {"code": "card"},
            "recoverable_gmv_per_day": 100_000.0,
            "recoverable_gmv_basis": {
                "stage_rate": stage_rate,
                "current_rate": 0.025,
                # An all-channel shop median: not comparable with a channel value.
                "reference_rate": 0.2,
                "reference": "shop_median",
            },
        },
    }


def test_rescore_reads_the_levers_channel_and_drops_the_all_channel_reference():
    rows = _mixed()
    out = rescore_legacy_payload(_legacy_payload("title"), rows, as_of=AS_OF, tunables=TUNABLES)
    assert out is not None
    assert out["kpi"]["channel"] == CHANNEL_PRODUCT_CARD
    assert out["diagnosis"]["recoverable_gmv_basis"]["channel"] == CHANNEL_PRODUCT_CARD
    assert out["diagnosis"]["recoverable_gmv_basis"]["reference"] == "own_earlier"
    channel = kpi_window(rows, as_of=AS_OF, metric="ctr", lever="title", tunables=TUNABLES).window
    assert out["kpi"]["current"] == pytest.approx(channel.value)


def test_rescore_of_a_price_card_stays_on_all_channels():
    rows = _mixed()
    out = rescore_legacy_payload(
        _legacy_payload("product_discount", "ctor"), rows, as_of=AS_OF, tunables=TUNABLES
    )
    assert out is not None and out["kpi"]["channel"] == CHANNEL_TOTAL
    assert out["diagnosis"]["recoverable_gmv_basis"]["reference"] == "shop_median"


# =========================================================================== measurement


def test_measurement_projects_stored_rows_onto_the_channel():
    from juli_backend.services.lever_flows.measurement import channel_rows, window_totals

    day = date(2026, 9, 1)
    rows = [
        SimpleNamespace(
            start_date=day,
            traffic_breakdown={"PRODUCT_CARD": {"impressions": 2000, "clicks": 100}},
        ),
        SimpleNamespace(start_date=day + timedelta(days=1), traffic_breakdown={"VIDEO": {}}),
        SimpleNamespace(start_date=day + timedelta(days=2), traffic_breakdown=None),
    ]
    projected = channel_rows(cast(Any, rows), "product_card")
    assert [(r.start_date, r.impressions, r.clicks) for r in projected] == [
        (day, Decimal(2000), Decimal(100)),
        (day + timedelta(days=1), Decimal(0), Decimal(0)),
    ]
    totals = window_totals(projected, day, day + timedelta(days=2))
    assert totals.value("ctr") == Decimal("0.05")


T = date(2026, 9, 20)


def _measured_day(shop_id, product_id, day: date, *, card_clicks: int, video_clicks: int):
    from juli_backend.models.models import AnalyticsPerformanceInterval

    clicks = card_clicks + video_clicks
    return AnalyticsPerformanceInterval(
        shop_id=shop_id,
        snapshot_key=f"product:{product_id}:{day.isoformat()}",
        grain="product",
        start_date=day,
        tiktok_product_id=product_id,
        impressions=6000,
        clicks=clicks,
        sku_orders=30,
        items_sold=30,
        gmv=6_000_000,
        traffic_breakdown={
            "PRODUCT_CARD": {"impressions": 3000, "ctr": card_clicks / 3000, "clicks": card_clicks},
            "VIDEO": {"impressions": 3000, "ctr": video_clicks / 3000, "clicks": video_clicks},
        },
        update_time=datetime(2026, 10, 9),
    )


async def _channel_run(session, *, channel: str | None):
    import uuid

    from juli_backend.models.models import ImpactReading, ToolExecution
    from tests.support.lever_flows import PRODUCT_ID, seed_run, seed_shop

    shop, product = await seed_shop(session, f"p27-{channel}")
    payload = {
        "diagnosis": {
            "lever": {"code": "cover_image", "label": "ảnh bìa"},
            "main_kpi": {"key": "ctr", "label": "CTR"},
            "recoverable_gmv_per_day": 50_000,
            "recoverable_gmv_basis": {
                "stage_rate": "ctr",
                "current_rate": 0.03,
                "reference_rate": 0.033,
            },
        },
        "kpi": {"metric": "ctr", "current": 0.03, "target": 0.033, "day14_only": False},
    }
    if channel is not None:
        payload["kpi"]["channel"] = channel
    run = await seed_run(session, shop, product, payload=json.dumps(payload), status="completed")
    execution = ToolExecution(
        shop_id=shop.id,
        approval_id=str(uuid.uuid4()),
        tool_name="update_product_listing",
        payload_json="{}",
        status="succeeded",
        workflow_run_id=run.id,
        tool_call_id="c1",
        updated_at=datetime(T.year, T.month, T.day, 4, 0),
    )
    session.add(execution)
    await session.flush()
    # Before: product card 90 clicks/day (3 %); Video swings 30 / 150 clicks.
    for offset in range(1, 15):
        session.add(
            _measured_day(
                shop.id,
                PRODUCT_ID,
                T - timedelta(days=offset),
                card_clicks=90,
                video_clicks=30 if offset % 2 else 150,
            )
        )
    # After: product card 105 clicks/day (3,5 %); Video falls to 30 every day,
    # so the all-channel CTR FALLS while the lever's own channel rose.
    for offset in range(1, 15):
        session.add(
            _measured_day(
                shop.id, PRODUCT_ID, T + timedelta(days=offset), card_clicks=105, video_clicks=30
            )
        )
    for kind in ("preliminary", "final"):
        session.add(
            ImpactReading(
                run_id=run.id,
                tool_execution_id=execution.id,
                metric="ctr",
                kind=kind,
                confidence="trung_binh",
                control_set_json="{}",
                computed_at=datetime(2026, 10, 9),
                series_source="measured",
            )
        )
    await session.flush()
    return shop, run


@pytest.mark.asyncio
async def test_day14_measures_the_target_on_the_kpis_channel(session):
    from juli_backend.services import lever_flows

    shop, run = await _channel_run(session, channel="product_card")
    body = await lever_flows.measure_run(session, shop.id, run)
    assert body["stage"] == "final"
    assert body["target"]["label"] == "CTR · đo trên kênh Thẻ sản phẩm"
    assert body["target"]["channel"] == "product_card"
    [target_row] = [r for r in body["rows"] if r["key"] == "ctr"]
    assert target_row["before"] == pytest.approx(0.03)
    assert target_row["actual"] == pytest.approx(0.035)
    assert body["verdict"]["day14"] == "met"
    assert body["verdict"]["day7"] == "rising"


@pytest.mark.asyncio
async def test_day14_of_an_all_channel_kpi_reads_every_channel(session):
    from juli_backend.services import lever_flows

    shop, run = await _channel_run(session, channel="total")
    body = await lever_flows.measure_run(session, shop.id, run)
    assert body["target"]["label"] == "CTR · đo trên tất cả kênh"
    assert body["target"]["channel"] == "total"
    [target_row] = [r for r in body["rows"] if r["key"] == "ctr"]
    # All channels: (90 + 90) / 6000 = 3 % before, (105 + 30) / 6000 = 2,25 % after.
    assert target_row["before"] == pytest.approx(0.03)
    assert target_row["actual"] == pytest.approx(0.0225)
    assert body["verdict"]["day14"] == "not_met"


@pytest.mark.asyncio
async def test_a_card_from_before_d32_keeps_its_label_and_all_channel_reading(session):
    from juli_backend.services import lever_flows

    shop, run = await _channel_run(session, channel=None)
    body = await lever_flows.measure_run(session, shop.id, run)
    assert body["target"]["label"] == "CTR Thẻ sản phẩm"
    assert "channel" not in body["target"]
    [target_row] = [r for r in body["rows"] if r["key"] == "ctr"]
    assert target_row["actual"] == pytest.approx(0.0225)


# =========================================================================== read model / API


def test_the_seller_payload_and_card_carry_the_kpi_channel():
    from juli_backend.api.routes.demo_decisions import (
        DemoDecisionCard,
        DemoDecisionRecommendation,
    )
    from juli_backend.services.demo_decisions.read import _mask_recommendation_payload

    kpi = {
        "metric": "ctr",
        "current": 0.0296,
        "target": 0.031,
        "target_min": 0.03,
        "target_max": 0.031,
        "display": "point",
        "band_pct": 1.59,
        "window_days": 14,
        "low_data": False,
        "day14_only": False,
        "channel": "product_card",
    }
    masked = _mask_recommendation_payload({"target_metric": "ctr", "kpi": kpi})
    model = DemoDecisionRecommendation.model_validate(masked)
    assert model.kpi is not None and model.kpi.channel == "product_card"
    assert DemoDecisionCard.model_fields["kpi"].annotation is not None
    # A card written before D32 has no channel: all channels.
    legacy = DemoDecisionRecommendation.model_validate(
        {"kpi": {k: v for k, v in kpi.items() if k != "channel"}}
    )
    assert legacy.kpi is not None and legacy.kpi.channel == "total"


def test_the_card_kpi_label_names_the_channel_it_is_measured_on():
    from juli_backend.services.demo_decisions.card_view import _main_kpi

    def label(stage_rate: str, channel: str | None) -> str:
        basis: dict[str, Any] = {"stage_rate": stage_rate, "current_rate": 0.03}
        if channel is not None:
            basis["channel"] = channel
        return str(_main_kpi({"recoverable_gmv_basis": basis})["label"])

    assert label("ctr", "product_card") == "CTR - Thẻ sản phẩm"
    assert label("ctor", "total") == "CTOR"
    assert label("ctr", "total") == "CTR"
    # A card from before D32 keeps its label.
    assert label("ctor", None) == "CTOR - Thẻ sản phẩm"
