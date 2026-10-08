"""Metric rankings: which rows moved a stream's clicked metric — ADR-109 decisions 4 and 5.

For every traffic stream × clickable metric of the Phân tích screen, the rows
(products, LIVE sessions, videos) ranked by the GMV per day their change in that
metric moved, last 30 vs prior 30 days. Pure over a loaded
:class:`~juli_backend.services.shop_diagnosis.snapshot.Snapshot`; the daily job
stores the result and nothing renders it here.

**Product rows** (Thẻ sản phẩm của người bán, Tab Cửa hàng). Each product's
GMV/day is split over the chain Lượt hiển thị sản phẩm → CTR → CTOR → AOV with
ADR-108's log shares (:func:`.decomposition.log_share`) when every factor is
> 0 on both sides, else by sequential substitution in that order
(:func:`.decomposition.sequential_share`, exact and defined at zero). A prior
rate that does not exist (no impressions, clicks or orders before) takes the
stream's prior median across products. On Thẻ sản phẩm the CTOR share is also
split into its two steps, Tỷ lệ thêm vào giỏ hàng × đơn/thêm giỏ (Tab Cửa hàng
reports no add-to-cart); a product whose orders exceed zero with no add-to-cart
on a side cannot be split and stays in the step tables' mix row.

**Content rows** (LIVE sessions, videos) are new rows, not one row in two
windows (d.5 last bullet), so each is measured against the stream's
prior-window value, later factors at their prior values:

- CTR: impressions/day × (row CTR − prior CTR) × prior CTOR × prior AOV;
- CTOR: clicks/day × (row CTOR − prior CTOR) × prior AOV;
- Lượt hiển thị sản phẩm: (row impressions − the prior window's mean per row)/day
  × prior CTR × prior CTOR × prior AOV — the prior "rate" of impressions is per
  session (per video).

**Confidence** (ADR-108 d.11 on the metric's own quantity): lượt hiển thị for
Lượt hiển thị sản phẩm with ``ranking_impressions_floor`` per window instead of
the order floors, lượt bấm for CTR, đơn hàng SKU for CTOR, its steps and AOV. A
row under the floor on both sides is not listed (it goes to "N … ít đơn");
otherwise *Rõ* when :func:`.confidence.label` says so, else *Tham khảo*.

**Tables.** Kéo xuống (negative) and kéo lên (positive), each Rõ first then
Tham khảo, by |GMV|, at most ``ranking_max_rows``; rows under
``ranking_fold_share`` of the stream's GMV change fold into "Các … khác". The
three closing rows make every table add up to the stream's own factor GMV: the
unlisted rows, the folded rows, and *Thay đổi cơ cấu* = stream factor − Σ every
row's factor (the mix effect; for content streams it also holds what the
session / video lists do not cover).
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

from juli_backend.services.shop_diagnosis.channels import (
    CHANNEL_LABELS,
    Channel,
    Counts,
    Series,
    build_series,
    window_sum,
)
from juli_backend.services.shop_diagnosis.confidence import (
    Confidence,
    label,
    rate_differs,
    series_differs,
)
from juli_backend.services.shop_diagnosis.config import ShopDiagnosisConfig
from juli_backend.services.shop_diagnosis.decomposition import log_share, sequential_share
from juli_backend.services.shop_diagnosis.snapshot import Snapshot, Windows, to_float

SHOP_UTC_OFFSET_HOURS = 7


class Metric(StrEnum):
    IMPRESSIONS = "impressions"
    CTR = "ctr"
    CTOR = "ctor"
    ADD_TO_CART_RATE = "add_to_cart_rate"
    ORDERS_PER_CART = "orders_per_cart"
    AOV = "aov"


#: As TikTok writes them (ADR-109 d.4; Tỷ lệ thêm vào giỏ hàng / đơn/thêm giỏ
#: are the two steps carried by the wide CTOR cell).
METRIC_LABELS: dict[Metric, str] = {
    Metric.IMPRESSIONS: "Lượt hiển thị sản phẩm",
    Metric.CTR: "CTR",
    Metric.CTOR: "CTOR",
    Metric.ADD_TO_CART_RATE: "Tỷ lệ thêm vào giỏ hàng",
    Metric.ORDERS_PER_CART: "đơn/thêm giỏ",
    Metric.AOV: "AOV",
}

#: ADR-109 d.4: the clickable cells of each stream.
STREAM_METRICS: dict[Channel, tuple[Metric, ...]] = {
    Channel.PRODUCT_CARD: (
        Metric.IMPRESSIONS,
        Metric.CTR,
        Metric.CTOR,
        Metric.ADD_TO_CART_RATE,
        Metric.ORDERS_PER_CART,
        Metric.AOV,
    ),
    Channel.SHOP_TAB: (Metric.IMPRESSIONS, Metric.CTR, Metric.CTOR, Metric.AOV),
    Channel.SELLER_LIVE: (Metric.IMPRESSIONS, Metric.CTR, Metric.CTOR),
    Channel.SELLER_VIDEO: (Metric.IMPRESSIONS, Metric.CTR),
}
STREAMS: tuple[Channel, ...] = tuple(STREAM_METRICS)

_FOUR: tuple[Metric, ...] = (Metric.IMPRESSIONS, Metric.CTR, Metric.CTOR, Metric.AOV)
_FIVE: tuple[Metric, ...] = (
    Metric.IMPRESSIONS,
    Metric.CTR,
    Metric.ADD_TO_CART_RATE,
    Metric.ORDERS_PER_CART,
    Metric.AOV,
)
_STEPS: tuple[Metric, ...] = (Metric.ADD_TO_CART_RATE, Metric.ORDERS_PER_CART)


class RowKind(StrEnum):
    PRODUCT = "product"
    LIVE_SESSION = "live_session"
    VIDEO = "video"


#: Closing-row nouns per row kind: (singular noun, "Các … khác", mix label).
_NOUNS: dict[RowKind, tuple[str, str, str]] = {
    RowKind.PRODUCT: ("sản phẩm", "Các sản phẩm khác", "Thay đổi cơ cấu sản phẩm"),
    RowKind.LIVE_SESSION: ("phiên LIVE", "Các phiên LIVE khác", "Thay đổi cơ cấu phiên LIVE"),
    RowKind.VIDEO: ("video", "Các video khác", "Thay đổi cơ cấu video"),
}
#: What "too little data" means for each metric's quantity.
_FEW: dict[Metric, str] = {
    Metric.IMPRESSIONS: "ít lượt hiển thị",
    Metric.CTR: "ít lượt bấm",
}


@dataclass(frozen=True)
class VideoWindowCounts:
    """One seller video's totals in the two 30-day windows — the optional video input.

    Built from the per-video fetch (fast track P8-B,
    ``shop_diagnosis_daily.video_windows.ranking_videos``). ``last`` / ``prior``
    are window **totals** (not daily averages) of product impressions, product
    clicks, SKU orders and GMV; ``None`` when the video had no activity in that
    window (``prior``: not posted yet; ``last``: only counts toward the prior
    baseline). Without this input no video ranking is built.
    """

    video_id: str
    title: str
    posted_on: date | None
    last: Counts | None
    prior: Counts | None = None


@dataclass(frozen=True)
class MetricRanking:
    """One stream × metric table, as stored (``payload`` is JSON-ready)."""

    stream: Channel
    metric: Metric
    payload: dict[str, Any]


# ---------------------------------------------------------------------------
# Factor chains
# ---------------------------------------------------------------------------


def metric_values(counts: Counts) -> dict[Metric, float | None]:
    return {
        Metric.IMPRESSIONS: counts.impressions,
        Metric.CTR: counts.ctr,
        Metric.CTOR: counts.ctor,
        Metric.ADD_TO_CART_RATE: counts.add_to_cart_rate,
        Metric.ORDERS_PER_CART: counts.orders_per_add_to_cart,
        Metric.AOV: counts.aov,
    }


def split(
    chain: Sequence[Metric],
    before: dict[Metric, float | None],
    after: dict[Metric, float | None],
    fallback: dict[Metric, float | None],
) -> tuple[dict[Metric, float], str]:
    """GMV/day per factor of ``chain``: log shares, else sequential substitution.

    A missing prior value takes ``fallback`` (the stream's prior median), then
    the last value. A missing last value (its denominator is zero, so every
    later term is multiplied by zero) takes the prior value.
    """
    b: list[float] = []
    a: list[float] = []
    for metric in chain:
        prior = before[metric]
        if prior is None:
            prior = fallback.get(metric)
        if prior is None:
            prior = after[metric]
        prior = float(prior or 0.0)
        last = after[metric]
        b.append(prior)
        a.append(prior if last is None else float(last))
    complete = all(before[m] is not None and after[m] is not None for m in chain)
    shares = log_share(b, a) if complete else None
    if shares is not None:
        return dict(zip(chain, shares, strict=True)), "log_share"
    return dict(zip(chain, sequential_share(b, a), strict=True)), "sequential"


def _splits_steps(counts: Counts) -> bool:
    """CTOR = add-to-cart rate × orders per add-to-cart holds on this side."""
    if counts.add_to_cart is None or counts.sku_orders is None:
        return False
    return counts.add_to_cart > 0 or counts.sku_orders == 0


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


@dataclass
class _Row:
    id: str
    name: str
    gmv: float
    listed: bool
    confidence: Confidence | None
    prior: float | None
    last: float | None
    quantity_prior: float | None
    quantity_last: float
    day: str | None = None
    method: str | None = None
    steps: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "gmv_per_day": self.gmv,
            "confidence": self.confidence.value if self.confidence else None,
            "prior": self.prior,
            "last": self.last,
            "quantity_prior": self.quantity_prior,
            "quantity_last": self.quantity_last,
        }
        if self.day is not None:
            out["date"] = self.day
        if self.method is not None:
            out["method"] = self.method
        if self.steps is not None:
            out["steps"] = self.steps
        return out


def _floors(metric: Metric, config: ShopDiagnosisConfig) -> ShopDiagnosisConfig:
    """The config whose order floors apply to ``metric``'s quantity."""
    if metric is Metric.IMPRESSIONS:
        floor = config.ranking_impressions_floor
        return replace(config, reference_min_orders=floor, clear_min_orders=floor)
    return config


def _quantity(metric: Metric, counts: Counts) -> float:
    if metric is Metric.IMPRESSIONS:
        return counts.impressions
    if metric is Metric.CTR:
        return counts.clicks
    return counts.sku_orders or 0.0


def _confidence(
    metric: Metric, q0: float, q1: float, differs: bool, config: ShopDiagnosisConfig
) -> tuple[bool, Confidence | None]:
    """Listed (≥ the reference floor on a side) and its label, *Rõ* or *Tham khảo*."""
    floors = _floors(metric, config)
    if max(q0, q1) < floors.reference_min_orders:
        return False, None
    verdict = label(q0, q1, differs, floors)
    return True, Confidence.CLEAR if verdict is Confidence.CLEAR else Confidence.REFERENCE


def _rate_terms(metric: Metric, counts: Counts) -> tuple[float, float]:
    """(successes, trials) of a rate metric, as window totals."""
    if metric is Metric.CTR:
        return counts.clicks, counts.impressions
    if metric is Metric.CTOR:
        return counts.sku_orders or 0.0, counts.clicks
    if metric is Metric.ADD_TO_CART_RATE:
        return counts.add_to_cart or 0.0, counts.clicks
    return counts.sku_orders or 0.0, counts.add_to_cart or 0.0  # ORDERS_PER_CART


def _daily_aov(days: Iterable[Counts]) -> list[float]:
    return [d.gmv / d.sku_orders for d in days if d.sku_orders]


def _product_differs(
    metric: Metric,
    total0: Counts,
    total1: Counts,
    days0: list[Counts],
    days1: list[Counts],
    config: ShopDiagnosisConfig,
) -> bool:
    if metric is Metric.IMPRESSIONS:
        return series_differs(
            [d.impressions for d in days0], [d.impressions for d in days1], config.z_value
        )
    if metric is Metric.AOV:
        return series_differs(_daily_aov(days0), _daily_aov(days1), config.z_value)
    s0, t0 = _rate_terms(metric, total0)
    s1, t1 = _rate_terms(metric, total1)
    return rate_differs(s0, t0, s1, t1, config.z_value)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def _table(
    rows: list[_Row],
    *,
    stream_factor: float,
    stream_change: float,
    kind: RowKind,
    metric: Metric,
    config: ShopDiagnosisConfig,
) -> dict[str, Any]:
    """Kéo xuống / kéo lên lists and the three closing rows that reconcile to the factor."""
    noun, others_label, mix_label = _NOUNS[kind]
    few_word = _FEW.get(metric, "ít đơn")
    unlisted = [r for r in rows if not r.listed]
    threshold = config.ranking_fold_share * abs(stream_change)
    candidates = [r for r in rows if r.listed and r.gmv != 0 and abs(r.gmv) >= threshold]

    def ordered(sign: float) -> list[_Row]:
        side = [r for r in candidates if r.gmv * sign > 0]
        side.sort(key=lambda r: (r.confidence is not Confidence.CLEAR, -abs(r.gmv)))
        return side[: config.ranking_max_rows]

    down, up = ordered(-1.0), ordered(1.0)
    shown = {id(r) for r in (*down, *up)}
    others = [r for r in rows if r.listed and id(r) not in shown]
    few_sum = sum(r.gmv for r in unlisted)
    others_sum = sum(r.gmv for r in others)
    mix = stream_factor - sum(r.gmv for r in rows)
    return {
        "down": [r.to_dict() for r in down],
        "up": [r.to_dict() for r in up],
        "closing": {
            "few": {
                "label": f"{len(unlisted)} {noun} {few_word}",
                "count": len(unlisted),
                "gmv_per_day": few_sum,
            },
            "others": {"label": others_label, "count": len(others), "gmv_per_day": others_sum},
            "mix": {"label": mix_label, "gmv_per_day": mix},
        },
    }


def _payload(
    *,
    stream: Channel,
    metric: Metric,
    kind: RowKind,
    windows: Windows,
    prior: Counts,
    last: Counts,
    factor: float,
    method: str,
    table: dict[str, Any],
) -> dict[str, Any]:
    p, q = metric_values(prior), metric_values(last)
    return {
        "stream": stream.value,
        "stream_label": CHANNEL_LABELS[stream],
        "metric": metric.value,
        "metric_label": METRIC_LABELS[metric],
        "row_kind": kind.value,
        "windows": {
            "prior": [windows.prior_first.isoformat(), windows.prior_last.isoformat()],
            "last": [windows.last_first.isoformat(), windows.last_last.isoformat()],
        },
        "unit": "₫/ngày",
        "stream_prior": p[metric],
        "stream_last": q[metric],
        "stream_gmv_prior": prior.gmv,
        "stream_gmv_last": last.gmv,
        "stream_gmv_change": last.gmv - prior.gmv,
        "stream_factor_gmv": factor,
        "method": method,
        "orders_estimated": prior.orders_estimated or last.orders_estimated,
        **table,
    }


# ---------------------------------------------------------------------------
# Product streams
# ---------------------------------------------------------------------------


def _median(values: Iterable[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return statistics.median(present) if present else None


@dataclass
class _ProductData:
    pid: str
    total0: Counts
    total1: Counts
    prior: Counts
    last: Counts
    days0: list[Counts]
    days1: list[Counts]


def _product_rankings(
    snapshot: Snapshot,
    series: Series,
    stream: Channel,
    windows: Windows,
    prior_days: list[date],
    last_days: list[date],
    config: ShopDiagnosisConfig,
) -> list[MetricRanking]:
    n0, n1 = len(prior_days), len(last_days)
    stream_prior = window_sum(series, stream, prior_days).scaled(1 / n0)
    stream_last = window_sum(series, stream, last_days).scaled(1 / n1)
    products: list[_ProductData] = []
    for pid, per_day in series.get(stream, {}).items():
        t0 = window_sum(series, stream, prior_days, [pid])
        t1 = window_sum(series, stream, last_days, [pid])
        if not any((t0.impressions, t0.clicks, t0.gmv, t1.impressions, t1.clicks, t1.gmv)):
            continue
        products.append(
            _ProductData(
                pid,
                t0,
                t1,
                t0.scaled(1 / n0),
                t1.scaled(1 / n1),
                [per_day[d] for d in prior_days if d in per_day],
                [per_day[d] for d in last_days if d in per_day],
            )
        )
    metrics = STREAM_METRICS[stream]
    with_steps = Metric.ADD_TO_CART_RATE in metrics
    chain = _FIVE if with_steps else _FOUR
    medians = {m: _median(metric_values(p.prior)[m] for p in products) for m in (*_FOUR, *_FIVE)}

    stream_four, method = split(
        _FOUR, metric_values(stream_prior), metric_values(stream_last), metric_values(stream_last)
    )
    stream_factor = dict(stream_four)
    if with_steps:
        if _splits_steps(stream_prior) and _splits_steps(stream_last):
            five, _ = split(
                _FIVE,
                metric_values(stream_prior),
                metric_values(stream_last),
                metric_values(stream_last),
            )
            stream_factor.update({m: five[m] for m in _STEPS})
        else:
            metrics = tuple(m for m in metrics if m not in _STEPS)

    rows: dict[Metric, list[_Row]] = {m: [] for m in metrics}
    for p in products:
        before, after = metric_values(p.prior), metric_values(p.last)
        four, row_method = split(_FOUR, before, after, medians)
        shares: dict[Metric, float] = dict(four)
        steps: dict[str, float] | None = None
        if chain is _FIVE and _splits_steps(p.total0) and _splits_steps(p.total1):
            five, _ = split(_FIVE, before, after, medians)
            steps = {m.value: five[m] for m in _STEPS}
            shares.update({m: five[m] for m in _STEPS})
        name = snapshot.title(p.pid) or f"Sản phẩm {p.pid}"
        for metric in metrics:
            if metric not in shares:
                continue  # no add-to-cart split for this product: stays in the mix row
            q0, q1 = _quantity(metric, p.total0), _quantity(metric, p.total1)
            differs = _product_differs(metric, p.total0, p.total1, p.days0, p.days1, config)
            listed, confidence = _confidence(metric, q0, q1, differs, config)
            rows[metric].append(
                _Row(
                    id=p.pid,
                    name=name,
                    gmv=shares[metric],
                    listed=listed,
                    confidence=confidence,
                    prior=before[metric],
                    last=after[metric],
                    quantity_prior=q0,
                    quantity_last=q1,
                    method=row_method,
                    steps=steps if metric is Metric.CTOR else None,
                )
            )
    change = stream_last.gmv - stream_prior.gmv
    return [
        MetricRanking(
            stream,
            metric,
            _payload(
                stream=stream,
                metric=metric,
                kind=RowKind.PRODUCT,
                windows=windows,
                prior=stream_prior,
                last=stream_last,
                factor=stream_factor[metric],
                method=method,
                table=_table(
                    rows[metric],
                    stream_factor=stream_factor[metric],
                    stream_change=change,
                    kind=RowKind.PRODUCT,
                    metric=metric,
                    config=config,
                ),
            ),
        )
        for metric in metrics
    ]


# ---------------------------------------------------------------------------
# Content streams (LIVE sessions, videos)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ContentItem:
    id: str
    name: str
    day: date | None
    last: Counts | None
    prior: Counts | None = field(default=None)


def _local_day(value: object) -> date | None:
    text = str(value or "").strip()
    if not text.isdigit():
        return None
    zone = timezone(timedelta(hours=SHOP_UTC_OFFSET_HOURS))
    return datetime.fromtimestamp(int(text), tz=UTC).astimezone(zone).date()


def _block(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def live_items(sessions: list[dict], windows: Windows) -> list[_ContentItem]:
    """LIVE sessions (``live/sessions.json``) placed in the window they started in."""
    items: list[_ContentItem] = []
    for session in sessions:
        day = _local_day(session.get("start_time"))
        if day is None or not windows.prior_first <= day <= windows.last_last:
            continue
        traffic = _block(session.get("interaction_performance"))
        sales = _block(session.get("sales_performance"))
        counts = Counts(
            impressions=to_float(traffic.get("product_impressions")),
            clicks=to_float(traffic.get("product_clicks")),
            add_to_cart=None,
            sku_orders=to_float(sales.get("sku_orders")),
            gmv=to_float(sales.get("gmv")),
        )
        title = str(session.get("title") or "LIVE")
        in_last = day >= windows.last_first
        items.append(
            _ContentItem(
                id=str(session.get("id") or ""),
                name=f"{title} · {day.strftime('%d/%m/%Y')}",
                day=day,
                last=counts if in_last else None,
                prior=None if in_last else counts,
            )
        )
    return items


def video_items(videos: Sequence[VideoWindowCounts]) -> list[_ContentItem]:
    return [
        _ContentItem(
            id=v.video_id,
            name=v.title or f"Video {v.video_id}",
            day=v.posted_on,
            last=v.last,
            prior=v.prior,
        )
        for v in videos
    ]


def _content_rankings(
    items: list[_ContentItem],
    series: Series,
    stream: Channel,
    kind: RowKind,
    windows: Windows,
    prior_days: list[date],
    last_days: list[date],
    config: ShopDiagnosisConfig,
) -> list[MetricRanking]:
    n0, n1 = len(prior_days), len(last_days)
    total_prior = window_sum(series, stream, prior_days)
    stream_prior = total_prior.scaled(1 / n0)
    stream_last = window_sum(series, stream, last_days).scaled(1 / n1)
    base = metric_values(stream_prior)
    stream_shares, method = split(
        _FOUR, base, metric_values(stream_last), metric_values(stream_last)
    )
    # Prior values a content row is measured against; a missing one takes the last.
    ref = {m: base[m] if base[m] is not None else metric_values(stream_last)[m] for m in _FOUR}
    ctr0, ctor0, aov0 = (float(ref[m] or 0.0) for m in (Metric.CTR, Metric.CTOR, Metric.AOV))
    prior_items = [i.prior for i in items if i.prior is not None and i.prior.impressions > 0]
    baseline = sum(c.impressions for c in prior_items) / len(prior_items) if prior_items else 0.0
    current = [i for i in items if i.last is not None]
    metrics = STREAM_METRICS[stream]
    rows: dict[Metric, list[_Row]] = {m: [] for m in metrics}
    for item in current:
        s = item.last
        assert s is not None  # narrowed by ``current``
        values = metric_values(s)
        values[Metric.IMPRESSIONS] = s.impressions / n1
        for metric in metrics:
            if metric is Metric.IMPRESSIONS:
                gmv = (s.impressions / n1 - baseline / n0) * ctr0 * ctor0 * aov0
                prior_value: float | None = baseline / n0
                differs = s.impressions != baseline
            elif metric is Metric.CTR:
                gmv = 0.0 if s.ctr is None else s.impressions / n1 * (s.ctr - ctr0) * ctor0 * aov0
                prior_value = ref[Metric.CTR]
                differs = rate_differs(
                    total_prior.clicks,
                    total_prior.impressions,
                    s.clicks,
                    s.impressions,
                    config.z_value,
                )
            else:  # CTOR
                gmv = 0.0 if s.ctor is None else s.clicks / n1 * (s.ctor - ctor0) * aov0
                prior_value = ref[Metric.CTOR]
                differs = rate_differs(
                    total_prior.sku_orders or 0.0,
                    total_prior.clicks,
                    s.sku_orders or 0.0,
                    s.clicks,
                    config.z_value,
                )
            q = _quantity(metric, s)
            listed, confidence = _confidence(metric, q, q, differs, config)
            rows[metric].append(
                _Row(
                    id=item.id,
                    name=item.name,
                    gmv=gmv,
                    listed=listed,
                    confidence=confidence,
                    prior=prior_value,
                    last=values[metric],
                    quantity_prior=None,
                    quantity_last=q,
                    day=item.day.isoformat() if item.day else None,
                )
            )
    change = stream_last.gmv - stream_prior.gmv
    return [
        MetricRanking(
            stream,
            metric,
            _payload(
                stream=stream,
                metric=metric,
                kind=kind,
                windows=windows,
                prior=stream_prior,
                last=stream_last,
                factor=stream_shares[metric],
                method=method,
                table=_table(
                    rows[metric],
                    stream_factor=stream_shares[metric],
                    stream_change=change,
                    kind=kind,
                    metric=metric,
                    config=config,
                ),
            ),
        )
        for metric in metrics
    ]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_rankings(
    snapshot: Snapshot,
    videos: Sequence[VideoWindowCounts] | None = None,
    config: ShopDiagnosisConfig | None = None,
) -> list[MetricRanking]:
    """Every stream × clickable metric table for the snapshot; videos only when given."""
    config = config or ShopDiagnosisConfig()
    windows = Windows.ending(snapshot.end, config.window_days)
    present = set(snapshot.daily)
    prior_days = [d for d in windows.prior_days() if d in present]
    last_days = [d for d in windows.last_days() if d in present]
    if not prior_days or not last_days:
        raise ValueError("the snapshot needs daily files in both 30-day windows")
    series = build_series(snapshot.daily)
    out: list[MetricRanking] = []
    for stream in (Channel.PRODUCT_CARD, Channel.SHOP_TAB):
        out += _product_rankings(snapshot, series, stream, windows, prior_days, last_days, config)
    out += _content_rankings(
        live_items(snapshot.live_sessions, windows),
        series,
        Channel.SELLER_LIVE,
        RowKind.LIVE_SESSION,
        windows,
        prior_days,
        last_days,
        config,
    )
    if videos is not None:
        out += _content_rankings(
            video_items(videos),
            series,
            Channel.SELLER_VIDEO,
            RowKind.VIDEO,
            windows,
            prior_days,
            last_days,
            config,
        )
    return out


def reconciles(payload: dict[str, Any], tolerance: float = 1e-6) -> bool:
    """Listed rows + the three closing rows == the stream's factor GMV."""
    listed = sum(r["gmv_per_day"] for r in (*payload["down"], *payload["up"]))
    closing = sum(c["gmv_per_day"] for c in payload["closing"].values())
    factor = payload["stream_factor_gmv"]
    return abs(listed + closing - factor) <= tolerance * max(1.0, abs(factor))


__all__ = [
    "METRIC_LABELS",
    "STREAMS",
    "STREAM_METRICS",
    "Metric",
    "MetricRanking",
    "RowKind",
    "VideoWindowCounts",
    "build_rankings",
    "live_items",
    "metric_values",
    "reconciles",
    "split",
    "video_items",
]
