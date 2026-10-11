"""Ops "Mô phỏng" (D25.10, D25.11): baseline, trend, volatility, what-if GMV.

DATA. The daily shop-diagnosis job stores, per report, the four seller streams'
raw daily counts (``report.daily_streams``: impressions, clicks, SKU orders,
GMV per day) and the same per product for each stream's top products
(``report.daily_products``) -- added in P16 to ``services/shop_diagnosis/
report.py``. A report covers the 60 days before its ``end_date``; this module
merges every stored report of the shop (newest wins per day), so the history
grows past 60 days as the job keeps running. Nothing is invented: a window that
the stored days cannot cover is reported unavailable.

WINDOW ``N`` ∈ {7, 14, 30, 90} (D25.11) drives
- the baseline: per-day average over the last ``N`` days (impressions/day,
  CTR = clicks / impressions, CTOR = SKU orders / clicks, AOV = GMV / SKU
  orders -- the Phân tích definitions), and GMV/day;
- the ▲/▼ trend: those KPIs over the last ``N`` days vs the ``N`` days before
  (needs ``2N`` days of history, else ``comparable = False``);
- the volatility: p10–p90 of the daily values within the last ``N`` days, the
  "normal band" ``±band_pct`` (the larger distance of p10 / p90 from the mean,
  in % of the mean) and the coefficient of variation of daily impressions.

SIMULATION. GMV/day per stream = Hiển thị × CTR × CTOR × AOV; each cell moves
in ±5 % steps; Video CTOR, Video AOV and LIVE AOV are locked (D25.10 -- they
depend on the product page, not on the stream). A change whose size is within
the cell's ``band_pct`` is "trong dao động thường ngày" (not measurable).
"""

from __future__ import annotations

import math
import statistics
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.shop_diagnosis import ShopDiagnosisReport

STREAMS: tuple[str, ...] = ("product_card", "shop_tab", "seller_video", "seller_live")
STREAM_NAMES: dict[str, str] = {
    "product_card": "Thẻ sản phẩm",
    "shop_tab": "Tab cửa hàng",
    "seller_video": "Video",
    "seller_live": "LIVE",
}
#: What one volatility row is, per stream (rows are products by traffic source).
ROW_KINDS: dict[str, str] = {
    "product_card": "sản phẩm",
    "shop_tab": "sản phẩm",
    "seller_video": "sản phẩm (qua video)",
    "seller_live": "sản phẩm (qua LIVE)",
}
KPIS: tuple[str, ...] = ("impressions", "ctr", "ctor", "aov")
KPI_LABELS: dict[str, str] = {
    "impressions": "Hiển thị",
    "ctr": "CTR",
    "ctor": "CTOR",
    "aov": "AOV",
}
LOCKED: frozenset[tuple[str, str]] = frozenset(
    {("seller_video", "ctor"), ("seller_video", "aov"), ("seller_live", "aov")}
)
#: Hiển thị is algorithmic: moved only through ads, campaigns, content.
INDIRECT: frozenset[str] = frozenset({"impressions"})
WINDOWS: tuple[int, ...] = (7, 14, 30, 90)
DEFAULT_WINDOW = 30
STEP_PCT = 5
DELTA_RANGE = (-90, 300)
#: How far back stored reports are merged (2 × the longest window + slack).
HISTORY_DAYS = 2 * max(WINDOWS) + 10
#: Stable / medium thresholds on the coefficient of variation of impressions.
CV_STABLE = 0.15
CV_MEDIUM = 0.30

#: (stream, KPI) → the actions ("Hành động") that move it (D24 lever map).
LEVER_MAP: dict[str, dict[str, str]] = {
    "product_card": {
        "impressions": "từ khoá tiêu đề, chiến dịch sàn, GMV Max",
        "ctr": "ảnh bìa, tiêu đề",
        "ctor": "mô tả, giá, flash sale, voucher, phí ship",
        "aov": "mua nhiều giảm nhiều, combo",
    },
    "shop_tab": {
        "impressions": "trang trí shop, video kéo follow",
        "ctr": "sản phẩm nổi bật, banner",
        "ctor": "như Thẻ sản phẩm",
        "aov": "như Thẻ sản phẩm",
    },
    "seller_video": {
        "impressions": "đăng đều, GMV Max video",
        "ctr": "hook 3 giây, gắn link",
    },
    "seller_live": {
        "impressions": "thời lượng, số phiên, LIVE GMV Max",
        "ctr": "ghim sản phẩm, thứ tự giỏ",
        "ctor": "kịch bản host, flash sale LIVE",
    },
}


class SimulationError(ValueError):
    """Invalid window or deltas (422)."""


# -- pure math ------------------------------------------------------------------


def _ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator <= 0 else numerator / denominator


@dataclass(frozen=True)
class DayCounts:
    impressions: float
    clicks: float
    orders: float | None
    gmv: float

    @classmethod
    def from_row(cls, row: Any) -> DayCounts | None:
        if not isinstance(row, list | tuple) or len(row) < 4:
            return None
        impressions, clicks, orders, gmv = row[:4]
        return cls(
            float(impressions or 0),
            float(clicks or 0),
            None if orders is None else float(orders),
            float(gmv or 0),
        )

    def kpi(self, name: str) -> float | None:
        if name == "impressions":
            return self.impressions
        if name == "ctr":
            return _ratio(self.clicks, self.impressions)
        if name == "ctor":
            return None if self.orders is None else _ratio(self.orders, self.clicks)
        if name == "aov":
            return None if self.orders is None else _ratio(self.gmv, self.orders)
        raise KeyError(name)


def window_kpis(days: list[DayCounts]) -> dict[str, float | None]:
    """Per-day averages / ratio-of-sums over ``days`` (empty → all ``None``)."""
    if not days:
        return {k: None for k in (*KPIS, "gmv")}
    n = len(days)
    impressions = sum(d.impressions for d in days)
    clicks = sum(d.clicks for d in days)
    gmv = sum(d.gmv for d in days)
    has_orders = all(d.orders is not None for d in days)
    orders = sum(d.orders or 0 for d in days) if has_orders else None
    return {
        "impressions": impressions / n,
        "ctr": _ratio(clicks, impressions),
        "ctor": None if orders is None else _ratio(orders, clicks),
        "aov": None if orders is None else _ratio(gmv, orders),
        "gmv": gmv / n,
    }


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile (``q`` in 0..1) of a non-empty list."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


@dataclass(frozen=True)
class Band:
    p10: float
    p90: float
    mean: float
    band_pct: float | None
    cv: float | None
    days: int

    def to_json(self) -> dict[str, Any]:
        return {
            "p10": self.p10,
            "p90": self.p90,
            "mean": self.mean,
            "band_pct": self.band_pct,
            "cv": self.cv,
            "days": self.days,
        }


def band(values: Iterable[float | None]) -> Band | None:
    """p10–p90 of the daily values, the ±band in % of the mean, and the CV."""
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not clean:
        return None
    mean = statistics.fmean(clean)
    p10 = percentile(clean, 0.10)
    p90 = percentile(clean, 0.90)
    if mean > 0:
        band_pct = max(p90 - mean, mean - p10) / mean * 100
        cv = statistics.pstdev(clean) / mean if len(clean) > 1 else 0.0
    else:
        band_pct = None
        cv = None
    return Band(p10=p10, p90=p90, mean=mean, band_pct=band_pct, cv=cv, days=len(clean))


def stability(cv: float | None) -> str:
    if cv is None:
        return "unknown"
    if cv < CV_STABLE:
        return "stable"
    if cv < CV_MEDIUM:
        return "medium"
    return "volatile"


def trend_pct(last: float | None, prior: float | None) -> float | None:
    if last is None or prior is None or prior == 0:
        return None
    return (last - prior) / prior * 100


def validate_deltas(deltas: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    """``{stream: {kpi: pct}}`` with ±5 % steps, known cells, nothing locked."""
    if not isinstance(deltas, Mapping):
        raise SimulationError("deltas must be an object")
    clean: dict[str, dict[str, int]] = {}
    for stream, cells in deltas.items():
        if stream not in STREAMS:
            raise SimulationError(f"unknown stream {stream!r}")
        if not isinstance(cells, Mapping):
            raise SimulationError(f"deltas.{stream} must be an object")
        for kpi, value in cells.items():
            if kpi not in KPIS:
                raise SimulationError(f"unknown KPI {kpi!r}")
            if isinstance(value, bool) or not isinstance(value, int):
                raise SimulationError(f"{stream}.{kpi} must be a whole percent")
            if value == 0:
                continue
            if (stream, kpi) in LOCKED:
                raise SimulationError(f"{STREAM_NAMES[stream]} {KPI_LABELS[kpi]} is locked")
            if value % STEP_PCT != 0:
                raise SimulationError(f"{stream}.{kpi} must move in {STEP_PCT} % steps")
            if not DELTA_RANGE[0] <= value <= DELTA_RANGE[1]:
                raise SimulationError(f"{stream}.{kpi} is out of range")
            clean.setdefault(stream, {})[kpi] = value
    return clean


def stream_gmv(base: Mapping[str, float | None], deltas: Mapping[str, int] | None = None) -> float:
    """GMV/day = Hiển thị × CTR × CTOR × AOV, each scaled by its delta."""
    moves = deltas or {}
    total = 1.0
    for kpi in KPIS:
        value = base.get(kpi)
        if value is None:
            return 0.0
        total *= value * (1 + moves.get(kpi, 0) / 100)
    return total


def simulate(
    baseline: Mapping[str, Mapping[str, float | None]],
    deltas: Mapping[str, Mapping[str, int]],
) -> dict[str, Any]:
    """Per-stream and shop GMV/day before and after; month ≈ 30 days."""
    clean = validate_deltas(deltas)
    streams: dict[str, Any] = {}
    total_base = total_new = 0.0
    for stream in STREAMS:
        base = baseline.get(stream) or {}
        g0 = stream_gmv(base)
        g1 = stream_gmv(base, clean.get(stream))
        total_base += g0
        total_new += g1
        streams[stream] = {
            "gmv_base": g0,
            "gmv_new": g1,
            "delta_pct": None if g0 == 0 else (g1 - g0) / g0 * 100,
        }
    return {
        "streams": streams,
        "total_base": total_base,
        "total_new": total_new,
        "delta_pct": None if total_base == 0 else (total_new - total_base) / total_base * 100,
        "delta_per_day": total_new - total_base,
        "delta_per_month": (total_new - total_base) * 30,
    }


def actions_for(deltas: Mapping[str, Mapping[str, int]]) -> list[dict[str, Any]]:
    """The lever-map actions for every changed cell."""
    out: list[dict[str, Any]] = []
    for stream in STREAMS:
        for kpi in KPIS:
            value = (deltas.get(stream) or {}).get(kpi, 0)
            what = LEVER_MAP.get(stream, {}).get(kpi)
            if value and what:
                out.append({"stream": stream, "kpi": kpi, "delta": value, "actions": what})
    return out


# -- data -----------------------------------------------------------------------


@dataclass
class History:
    """Merged daily counts of the shop's stored reports."""

    streams: dict[str, dict[date, DayCounts]]
    products: dict[str, dict[str, dict[date, DayCounts]]]
    titles: dict[str, str]
    seller_skus: dict[str, str]
    last_day: date | None
    first_day: date | None

    @property
    def days_available(self) -> int:
        if self.last_day is None or self.first_day is None:
            return 0
        return (self.last_day - self.first_day).days + 1


def _day(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


def merge_reports(reports: Iterable[Mapping[str, Any]]) -> History:
    """Oldest first; a newer report's day replaces an older one's."""
    streams: dict[str, dict[date, DayCounts]] = {s: {} for s in STREAMS}
    products: dict[str, dict[str, dict[date, DayCounts]]] = {s: {} for s in STREAMS}
    titles: dict[str, str] = {}
    skus: dict[str, str] = {}
    for report in reports:
        for stream, by_day in (report.get("daily_streams") or {}).items():
            if stream not in streams or not isinstance(by_day, Mapping):
                continue
            for raw, row in by_day.items():
                day, counts = _day(raw), DayCounts.from_row(row)
                if day is not None and counts is not None:
                    streams[stream][day] = counts
        for stream, by_product in (report.get("daily_products") or {}).items():
            if stream not in products or not isinstance(by_product, Mapping):
                continue
            for pid, by_day in by_product.items():
                if not isinstance(by_day, Mapping):
                    continue
                target = products[stream].setdefault(str(pid), {})
                for raw, row in by_day.items():
                    day, counts = _day(raw), DayCounts.from_row(row)
                    if day is not None and counts is not None:
                        target[day] = counts
        titles.update({str(k): str(v) for k, v in (report.get("titles") or {}).items() if v})
        skus.update({str(k): str(v) for k, v in (report.get("seller_skus") or {}).items() if v})
    all_days = [d for by_day in streams.values() for d in by_day]
    return History(
        streams=streams,
        products=products,
        titles=titles,
        seller_skus=skus,
        last_day=max(all_days) if all_days else None,
        first_day=min(all_days) if all_days else None,
    )


async def load_history(
    session: AsyncSession, shop_id: uuid.UUID, *, today: date | None = None
) -> History:
    """Every stored report of the shop over the last ``HISTORY_DAYS`` (caller sets scope)."""
    current = today or date.today()
    reports = (
        (
            await session.execute(
                select(ShopDiagnosisReport.report)
                .where(
                    ShopDiagnosisReport.shop_id == shop_id,
                    ShopDiagnosisReport.end_date >= current - timedelta(days=HISTORY_DAYS),
                )
                .order_by(ShopDiagnosisReport.end_date.asc(), ShopDiagnosisReport.built_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return merge_reports(r for r in reports if isinstance(r, Mapping))


def _days(last_day: date, count: int, offset: int = 0) -> list[date]:
    end = last_day - timedelta(days=offset)
    return [end - timedelta(days=i) for i in range(count - 1, -1, -1)]


def _present(by_day: Mapping[date, DayCounts], days: list[date]) -> list[DayCounts]:
    return [by_day[d] for d in days if d in by_day]


def window_status(history: History, window: int) -> dict[str, Any]:
    available = history.days_available
    return {
        "days": window,
        "baseline_available": available >= window,
        "comparable": available >= 2 * window,
        "needs_days": 2 * window,
        "history_days": available,
    }


def _row_label(history: History, pid: str) -> str:
    sku = history.seller_skus.get(pid)
    title = history.titles.get(pid) or pid
    return f"{sku} {title}" if sku else title


def baseline(history: History, window: int) -> dict[str, Any]:
    """Everything the page needs for one window (no deltas applied)."""
    if window not in WINDOWS:
        raise SimulationError(f"window must be one of {', '.join(map(str, WINDOWS))}")
    status = window_status(history, window)
    streams: list[dict[str, Any]] = []
    volatility: dict[str, Any] = {}
    if history.last_day is not None and status["baseline_available"]:
        last_days = _days(history.last_day, window)
        prior_days = _days(history.last_day, window, offset=window)
        for stream in STREAMS:
            by_day = history.streams.get(stream, {})
            present = _present(by_day, last_days)
            last = window_kpis(present)
            prior = window_kpis(_present(by_day, prior_days)) if status["comparable"] else None
            cells = []
            for kpi in KPIS:
                cell_band = band(d.kpi(kpi) for d in present)
                cells.append(
                    {
                        "kpi": kpi,
                        "label": KPI_LABELS[kpi],
                        "value": last[kpi],
                        "trend_pct": trend_pct(last[kpi], prior[kpi]) if prior else None,
                        "band": cell_band.to_json() if cell_band else None,
                        "locked": (stream, kpi) in LOCKED,
                        "indirect": kpi in INDIRECT,
                        "actions": LEVER_MAP.get(stream, {}).get(kpi),
                    }
                )
            imp_band = band(d.impressions for d in present)
            cv = imp_band.cv if imp_band else None
            streams.append(
                {
                    "stream": stream,
                    "name": STREAM_NAMES[stream],
                    "days_present": len(present),
                    "gmv_per_day": last["gmv"],
                    "gmv_model_per_day": stream_gmv(last),
                    "impressions_cv": cv,
                    "stability": stability(cv),
                    "cells": cells,
                }
            )
            rows = []
            for pid, per_day in history.products.get(stream, {}).items():
                row_days = _present(per_day, last_days)
                if len(row_days) < max(3, window // 3):
                    continue
                imp = band(d.impressions for d in row_days)
                if imp is None or imp.mean <= 0:
                    continue
                ctr = band(d.kpi("ctr") for d in row_days)
                ctor = band(d.kpi("ctor") for d in row_days)
                rows.append(
                    {
                        "id": pid,
                        "name": _row_label(history, pid),
                        "impressions": imp.to_json(),
                        "ctr": ctr.to_json() if ctr else None,
                        "ctor": ctor.to_json() if ctor else None,
                        "impressions_cv": imp.cv,
                        "stability": stability(imp.cv),
                    }
                )
            rows.sort(key=lambda r: (r["impressions_cv"] is None, r["impressions_cv"] or 0))
            volatility[stream] = {"row_kind": ROW_KINDS[stream], "rows": rows}
    first = _days(history.last_day, window)[0] if history.last_day else None
    return {
        "window": window,
        "windows": [window_status(history, w) for w in WINDOWS],
        "from": first.isoformat() if first and status["baseline_available"] else None,
        "to": history.last_day.isoformat() if history.last_day else None,
        "status": status,
        "streams": streams,
        "volatility": volatility,
        "locked": [{"stream": s, "kpi": k} for s, k in sorted(LOCKED)],
        "lever_map": LEVER_MAP,
        "step_pct": STEP_PCT,
    }


def baseline_values(payload: Mapping[str, Any]) -> dict[str, dict[str, float | None]]:
    """``{stream: {kpi: value}}`` from :func:`baseline`'s payload, for :func:`simulate`."""
    return {
        row["stream"]: {cell["kpi"]: cell["value"] for cell in row["cells"]}
        for row in payload.get("streams", [])
    }
