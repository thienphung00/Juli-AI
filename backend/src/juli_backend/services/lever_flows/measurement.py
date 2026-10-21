"""Đo lường for one run: target, allowed band, day 7 and day 14 (fast track P10-B, §6).

ADR-109 Amendment 1 d.6, D14, D16/D22. For a run that changed a listing (title,
description, cover image) or whose Seller Center promotion Juli verified:

- **Day 0 (``T``).** A listing run: the day its write succeeded (the impact
  reader's own ``T``, ``tool_executions.updated_at``). A promotion run: the
  promotion's start date (``run_lever_flows.measurement_start``).
- **Stage.** A listing run follows the impact reader: ``final`` once it wrote
  the day-14 (``final``) readings, ``day7`` once it wrote the ``preliminary``
  ones, ``waiting`` before. The reader does not measure promotion runs (they
  have no write), so a promotion run's stage follows the calendar (``T + 7``,
  ``T + 14``) -- DEBT P10-B.
- **Target** -- the card's own numbers: current rate → reference rate (the
  ``recoverable_gmv_basis`` that also prices GMV dự kiến). "Đang tiến triển" from
  ``current + 20 % × (target − current)``.
- **Bands** -- only the seller's ``stability_band`` rules (no default band: none
  set → ``bands = []`` and ``day7.within_band = null``), for every metric but the
  target. ``before`` is the 14 days before ``T``; the band is ``before ± band %``.
- **Rows** (day 7 / day 14): target, each band metric, GMV per day; values are
  daily averages from ``analytics_performance_intervals``, rates pooled
  (clicks ÷ impressions, orders ÷ clicks, GMV ÷ orders). Before day 7, ``[]``.
- **Day 7.** ``within_band``: every band metric with data inside its band.
  ``question_id``: P8-C's "Hoàn tác?" question for the run, when the impact
  reader raised one.
- **Day 14 (``final``).** GMV thực tế = GMV/day after − GMV/day before (not
  control-adjusted -- DEBT P10-B); % of GMV dự kiến. ``dat`` (target reached and
  ≥ 100 %), ``gan_dat`` (70–99 %, or ≥ 100 % without the target), ``khong_dat``
  (< 70 %), ``chua_ket_luan`` when the data is too thin (fewer than 10 of the 14
  days, or fewer than 20 orders after the change) or another change touched the
  product in the window (another run's write, a verified promotion, the impact
  reader's ``confounded``). Written once (``run_measurement_finals``); every
  label but ``chua_ket_luan`` moves the lever's calibration (realised ÷ expected,
  0.5 until the first reading) a quarter of the way to this run's ratio
  (clamped to 0..2).
- **Channel (D32).** A card whose ``kpi.channel`` is a channel (``product_card``)
  reads its TARGET metric -- before / after values, the 1-band verdicts, the
  strength and "target reached" -- on that channel's daily traffic
  (``traffic_breakdown``), the same series its KPI was set on; GMV, the guard
  bands and the data-sufficiency checks stay all-channel (the product's GMV must
  hold). The target label names the channel ("CTR · đo trên kênh Thẻ sản phẩm").
- **Strength (D31.7).** With a day-14 verdict, ``verdict.strength`` grades the
  target metric's change (post vs pre window mean, % of pre) against both
  windows' window-mean bands combined: ``clear`` / ``likely`` / ``noise``
  (``services.change_strength``); None without data. The verdict words and the
  external-change note are unchanged; the UI shows "Đạt · chưa chắc chắn" for a
  met verdict that is not ``clear``.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.lever_flows import (
    FLOW_PROMOTION,
    LeverCalibration,
    RunLeverFlow,
    RunMeasurementFinal,
)
from juli_backend.models.models import (
    WRITE_MODE_SIMULATED,
    ActionCard,
    AnalyticsPerformanceInterval,
    ImpactReading,
    Product,
    ToolExecution,
)
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.run_changes import RunRevertQuestion, RunWriteValue
from juli_backend.services import shop_rules
from juli_backend.services.change_strength import change_strength
from juli_backend.services.optimize_product.kpi_channel import (
    CHANNEL_METRICS,
    CHANNEL_TOTAL,
    CONTENT_TYPE,
    measured_on_vi,
)
from juli_backend.services.run_changes.default_bands import default_bands, effective_bands
from juli_backend.services.shop_rules.diag_tunables import diag_tunables

STAGE_WAITING = "waiting"
STAGE_DAY7 = "day7"
STAGE_FINAL = "final"

LABEL_DAT = "dat"
LABEL_GAN_DAT = "gan_dat"
LABEL_KHONG_DAT = "khong_dat"
LABEL_CHUA_KET_LUAN = "chua_ket_luan"

#: V5 (D31.8): the stored codes stay; on screen only Đạt / Một phần / Không đạt
#: (``gan_dat`` and ``chua_ket_luan`` both read "Một phần").
LABELS_VI: Mapping[str, str] = {
    LABEL_DAT: "Đạt",
    LABEL_GAN_DAT: "Một phần",
    LABEL_KHONG_DAT: "Không đạt",
    LABEL_CHUA_KET_LUAN: "Một phần",
}
_LABEL_TONE: Mapping[str, str] = {
    LABEL_DAT: "ok",
    LABEL_GAN_DAT: "ok",
    LABEL_KHONG_DAT: "warn",
    LABEL_CHUA_KET_LUAN: "muted",
}

DEFAULT_CALIBRATION = Decimal("0.5")
CALIBRATION_STEP = Decimal("0.25")
MIN_POST_DAYS = 10
MIN_POST_ORDERS = 20
MIN_PRE_DAYS = 7
PROGRESS_SHARE = Decimal("0.2")
_DAILY_PRODUCT_GRAIN = "product"
_SHOP_OFFSET = timedelta(hours=7)

#: Card main-KPI key -> the impact metric it is measured on.
KPI_METRIC: Mapping[str, str] = {
    "ctr": "ctr",
    "ctor": "conversion_rate",
    "aov": "gmv_per_order",
    # P23 (D29): a card whose GMV fall is explained by Hiển thị.
    "impressions": "impressions",
}
_KPI_TARGET_LABEL: Mapping[str, str] = {
    "ctr": "CTR Thẻ sản phẩm",
    "ctor": "CTOR Thẻ sản phẩm",
    "aov": "AOV (SKU)",
    "impressions": "Lượt hiển thị/ngày",
}
_KPI_SHORT: Mapping[str, str] = {
    "ctr": "CTR",
    "ctor": "CTOR",
    "aov": "AOV",
    "impressions": "Lượt hiển thị",
}

#: D29.8 verdict labels (contract P23 ``verdict``).
VERDICT_RISING = "rising"
VERDICT_UNCLEAR = "unclear"
VERDICT_MET = "met"
VERDICT_PARTIAL = "partial"
VERDICT_NOT_MET = "not_met"

METRIC_LABELS_VI: Mapping[str, str] = {
    "impressions": "Lượt hiển thị/ngày",
    "ctr": "CTR",
    "conversion_rate": "CTOR",
    "items_sold": "Sản phẩm bán/ngày",
    "gmv": "GMV/ngày",
    "sku_orders": "Đơn hàng SKU/ngày",
    "gmv_per_order": "AOV",
}
METRIC_UNITS: Mapping[str, str] = {
    "impressions": "count",
    "ctr": "ratio",
    "conversion_rate": "ratio",
    "items_sold": "count",
    "gmv": "vnd",
    "sku_orders": "count",
    "gmv_per_order": "vnd",
}


class NotMeasurable(LookupError):
    """The run changed nothing measurable (yet); ``message_vi`` says why."""

    def __init__(self, code: str, message_vi: str) -> None:
        super().__init__(f"{code}: {message_vi}")
        self.code = code
        self.message_vi = message_vi


# --- window aggregates ---------------------------------------------------------------


@dataclass(frozen=True)
class WindowTotals:
    days: int = 0
    impressions: Decimal = Decimal(0)
    clicks: Decimal = Decimal(0)
    sku_orders: Decimal = Decimal(0)
    items_sold: Decimal = Decimal(0)
    gmv: Decimal = Decimal(0)
    #: Fallback rates when the click counts are missing (mean of the daily ratios).
    ctr_mean: Decimal | None = None
    ctor_mean: Decimal | None = None

    def value(self, metric: str) -> Decimal | None:
        if self.days <= 0:
            return None
        per_day = Decimal(self.days)
        if metric == "impressions":
            return self.impressions / per_day
        if metric == "items_sold":
            return self.items_sold / per_day
        if metric == "sku_orders":
            return self.sku_orders / per_day
        if metric == "gmv":
            return self.gmv / per_day
        if metric == "ctr":
            return self.clicks / self.impressions if self.impressions > 0 else self.ctr_mean
        if metric == "conversion_rate":
            return self.sku_orders / self.clicks if self.clicks > 0 else self.ctor_mean
        if metric == "gmv_per_order":
            return self.gmv / self.sku_orders if self.sku_orders > 0 else None
        return None


def _dec(value: object) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal(0)


@dataclass(frozen=True)
class ChannelRow:
    """One product-day projected onto one channel (D32): traffic only, no orders."""

    start_date: date
    impressions: Decimal
    clicks: Decimal
    sku_orders: Decimal | None = None
    items_sold: Decimal | None = None
    gmv: Decimal | None = None
    ctr: Decimal | None = None
    conversion_rate: Decimal | None = None
    click_to_order_rate: Decimal | None = None


def channel_rows(rows: Iterable[AnalyticsPerformanceInterval], channel: str) -> list[ChannelRow]:
    """The rows' ``channel`` traffic (A-33 ``traffic_breakdown``), one per stored day.

    A day stored with a breakdown but without this content type showed nothing on
    it (zeros); a day with no breakdown at all, or whose content type has no click
    count, is unknown and left out.
    """
    key = CONTENT_TYPE.get(channel)
    if key is None:
        return []
    out: list[ChannelRow] = []
    for row in rows:
        breakdown = row.traffic_breakdown if isinstance(row.traffic_breakdown, dict) else {}
        if not any(k in breakdown for k in CONTENT_TYPE.values()):
            continue
        block = breakdown.get(key)
        if block is None:
            out.append(ChannelRow(row.start_date, Decimal(0), Decimal(0)))
            continue
        if not isinstance(block, dict) or block.get("clicks") is None:
            continue
        out.append(
            ChannelRow(
                row.start_date,
                _dec(block.get("impressions")),
                _dec(block.get("clicks")),
            )
        )
    return out


def window_totals(
    rows: Iterable[AnalyticsPerformanceInterval | ChannelRow], start: date, end: date
) -> WindowTotals:
    """Sum one product's daily rows over the inclusive ``[start, end]``."""
    picked = [row for row in rows if start <= row.start_date <= end]
    ctrs = [Decimal(str(r.ctr)) for r in picked if r.ctr is not None]
    ctors = [
        Decimal(str(r.conversion_rate if r.conversion_rate is not None else r.click_to_order_rate))
        for r in picked
        if r.conversion_rate is not None or r.click_to_order_rate is not None
    ]
    return WindowTotals(
        days=len({row.start_date for row in picked}),
        impressions=sum((_dec(r.impressions) for r in picked), Decimal(0)),
        clicks=sum((_dec(r.clicks) for r in picked), Decimal(0)),
        sku_orders=sum((_dec(r.sku_orders) for r in picked), Decimal(0)),
        items_sold=sum((_dec(r.items_sold) for r in picked), Decimal(0)),
        gmv=sum((_dec(r.gmv) for r in picked), Decimal(0)),
        ctr_mean=sum(ctrs, Decimal(0)) / len(ctrs) if ctrs else None,
        ctor_mean=sum(ctors, Decimal(0)) / len(ctors) if ctors else None,
    )


# --- formatting (VI) --------------------------------------------------------------------


def _group(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def format_value(value: Decimal | float | None, unit: str) -> str:
    if value is None:
        return "—"
    number = Decimal(str(value))
    if unit == "ratio":
        return f"{float(number * 100):.1f}".replace(".", ",") + " %"
    if unit == "vnd":
        return _short_vnd(number) + " ₫"
    return _group(int(number.to_integral_value(rounding=ROUND_HALF_UP)))


def _short_vnd(number: Decimal) -> str:
    amount = float(number)
    sign = "−" if amount < 0 else ""
    amount = abs(amount)
    if amount >= 1_000_000:
        return sign + f"{amount / 1_000_000:.1f}".replace(".", ",") + " tr"
    if amount >= 1000:
        return sign + f"{round(amount / 1000)}k"
    return sign + str(round(amount))


def format_range(low: Decimal, high: Decimal, unit: str) -> str:
    if unit == "ratio":
        return (
            f"{float(low * 100):.2f}".replace(".", ",")
            + " – "
            + f"{float(high * 100):.2f}".replace(".", ",")
            + " %"
        )
    if unit == "vnd":
        return f"{_short_vnd(low)} – {_short_vnd(high)} ₫"
    return f"{format_value(low, unit)} – {format_value(high, unit)}"


def _number(value: Decimal | None, unit: str) -> float | int | None:
    if value is None:
        return None
    if unit == "ratio":
        return float(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


# --- inputs -------------------------------------------------------------------------------


@dataclass(frozen=True)
class CardTarget:
    lever: str | None
    kpi_key: str | None
    current: Decimal | None
    target: Decimal | None
    expected_gmv_per_day: Decimal | None
    #: D29.10: a volatile product's card is judged at day 14 only.
    day14_only: bool = False
    #: D32: the channel its KPI was set on; ``None`` for a card written before D32.
    channel: str | None = None


def card_target(card: ActionCard | None) -> CardTarget:
    """The card's lever, main KPI and D22 numbers (``diagnosis`` of its payload)."""
    payload: Any = {}
    if card is not None:
        try:
            payload = json.loads(card.recommendation_payload or "{}")
        except json.JSONDecodeError:
            payload = {}
    diagnosis = payload.get("diagnosis") if isinstance(payload, Mapping) else None
    diagnosis = diagnosis if isinstance(diagnosis, Mapping) else {}

    def block(key: str) -> Mapping[str, Any]:
        value = diagnosis.get(key)
        return value if isinstance(value, Mapping) else {}

    lever = block("lever")
    kpi = block("main_kpi")
    basis = block("recoverable_gmv_basis")
    kpi_key = basis.get("stage_rate") or kpi.get("key")

    def dec(value: object) -> Decimal | None:
        return None if value is None else Decimal(str(value))

    kpi_block = payload.get("kpi") if isinstance(payload, Mapping) else None
    channel = kpi_block.get("channel") if isinstance(kpi_block, Mapping) else None
    return CardTarget(
        lever=str(lever["code"]) if lever.get("code") else None,
        kpi_key=str(kpi_key) if kpi_key in KPI_METRIC else None,
        current=dec(basis.get("current_rate")),
        target=dec(basis.get("reference_rate")),
        expected_gmv_per_day=dec(diagnosis.get("recoverable_gmv_per_day")),
        day14_only=bool(kpi_block.get("day14_only")) if isinstance(kpi_block, Mapping) else False,
        channel=str(channel) if isinstance(channel, str) and channel else None,
    )


#: Fast track P61-B: why a run that wrote to the sandbox merchant has no Đo lường.
SIMULATED_RUN_NOT_MEASURED_VI = (
    "Lượt chạy này là chạy thử, chưa thay đổi gì trên shop của bạn, nên Juli không đo kết quả."
)


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


async def _listing_day0(
    session: AsyncSession, shop_id: uuid.UUID, run_id: uuid.UUID
) -> date | None:
    executed = (
        await session.execute(
            select(func.min(ToolExecution.updated_at)).where(
                ToolExecution.shop_id == shop_id,
                ToolExecution.workflow_run_id == run_id,
                ToolExecution.tool_name == "update_product_listing",
                ToolExecution.status == "succeeded",
            )
        )
    ).scalar_one_or_none()
    if executed is not None:
        return _naive_utc(executed).date()
    recorded = (
        await session.execute(
            select(func.min(RunWriteValue.recorded_at)).where(
                RunWriteValue.shop_id == shop_id, RunWriteValue.workflow_run_id == run_id
            )
        )
    ).scalar_one_or_none()
    return _naive_utc(recorded).date() if recorded is not None else None


async def _reading_kinds(session: AsyncSession, run_id: uuid.UUID) -> tuple[set[str], bool]:
    rows = (
        await session.execute(
            select(ImpactReading.kind, ImpactReading.confidence).where(
                ImpactReading.run_id == run_id
            )
        )
    ).all()
    return {kind for kind, _ in rows}, any(conf == "confounded" for _, conf in rows)


async def _other_changes(
    session: AsyncSession,
    shop_id: uuid.UUID,
    run_id: uuid.UUID,
    tiktok_product_id: str,
    start: date,
    end: date,
) -> bool:
    """Another run wrote to the product, or another promotion started, in ``[start, end]``."""
    writes = (
        await session.execute(
            select(RunWriteValue.recorded_at)
            .join(WorkflowRunRow, WorkflowRunRow.id == RunWriteValue.workflow_run_id)
            .where(
                RunWriteValue.shop_id == shop_id,
                RunWriteValue.tiktok_product_id == tiktok_product_id,
                RunWriteValue.workflow_run_id != run_id,
                # P61-B: another run's sandbox write did not change the shop's product.
                or_(
                    WorkflowRunRow.write_mode.is_(None),
                    WorkflowRunRow.write_mode != WRITE_MODE_SIMULATED,
                ),
            )
        )
    ).scalars()
    if any(start <= _naive_utc(at).date() <= end for at in writes):
        return True
    promotions = (
        await session.execute(
            select(RunLeverFlow.measurement_start)
            .join(WorkflowRunRow, WorkflowRunRow.id == RunLeverFlow.workflow_run_id)
            .join(Product, Product.id == WorkflowRunRow.product_id)
            .where(
                RunLeverFlow.shop_id == shop_id,
                RunLeverFlow.workflow_run_id != run_id,
                RunLeverFlow.measurement_start.is_not(None),
                Product.tiktok_product_id == tiktok_product_id,
            )
        )
    ).scalars()
    return any(day is not None and start <= day <= end for day in promotions)


async def _daily_rows(
    session: AsyncSession, shop_id: uuid.UUID, tiktok_product_id: str, start: date, end: date
) -> list[AnalyticsPerformanceInterval]:
    result = await session.execute(
        select(AnalyticsPerformanceInterval).where(
            AnalyticsPerformanceInterval.shop_id == shop_id,
            AnalyticsPerformanceInterval.grain == _DAILY_PRODUCT_GRAIN,
            AnalyticsPerformanceInterval.tiktok_product_id == tiktok_product_id,
            AnalyticsPerformanceInterval.start_date >= start,
            AnalyticsPerformanceInterval.start_date <= end,
        )
    )
    return list(result.scalars().all())


async def current_calibration(session: AsyncSession, shop_id: uuid.UUID, lever: str) -> Decimal:
    row = (
        await session.execute(
            select(LeverCalibration).where(
                LeverCalibration.shop_id == shop_id, LeverCalibration.lever == lever
            )
        )
    ).scalar_one_or_none()
    return Decimal(str(row.coefficient)) if row is not None else DEFAULT_CALIBRATION


async def shop_calibrations(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, Decimal]:
    """lever -> the shop's stored coefficient; a lever never measured is absent (0.5).

    Read by the nightly card ranking (D24.6,
    ``optimize_product.decision_cards.LeverHistory``).
    """
    rows = (
        await session.execute(select(LeverCalibration).where(LeverCalibration.shop_id == shop_id))
    ).scalars()
    return {row.lever: Decimal(str(row.coefficient)) for row in rows}


async def shop_calibration_stats(
    session: AsyncSession, shop_id: uuid.UUID
) -> dict[str, tuple[Decimal, int]]:
    """lever -> (coefficient, measured day-14 results) for the shop (D30.3 shrinkage)."""
    rows = (
        await session.execute(select(LeverCalibration).where(LeverCalibration.shop_id == shop_id))
    ).scalars()
    return {row.lever: (Decimal(str(row.coefficient)), int(row.readings or 0)) for row in rows}


async def fleet_calibration_stats(session: AsyncSession) -> dict[str, tuple[Decimal, int]]:
    """lever -> (results-weighted mean coefficient, results) over every shop the session sees.

    D30.3's fleet level. Under a shop-scoped session (row-level security) this
    sees only that shop, which degrades to the shop's own numbers -- never
    another shop's, and never an error.
    """
    rows = (
        await session.execute(
            select(
                LeverCalibration.lever,
                func.sum(LeverCalibration.coefficient * LeverCalibration.readings),
                func.sum(LeverCalibration.readings),
            )
            .where(LeverCalibration.readings > 0)
            .group_by(LeverCalibration.lever)
        )
    ).all()
    out: dict[str, tuple[Decimal, int]] = {}
    for lever, weighted, readings in rows:
        if not readings:
            continue
        out[str(lever)] = (Decimal(str(weighted)) / Decimal(int(readings)), int(readings))
    return out


async def _update_calibration(
    session: AsyncSession, shop_id: uuid.UUID, lever: str, ratio: Decimal
) -> tuple[Decimal, Decimal]:
    row = (
        await session.execute(
            select(LeverCalibration).where(
                LeverCalibration.shop_id == shop_id, LeverCalibration.lever == lever
            )
        )
    ).scalar_one_or_none()
    before = Decimal(str(row.coefficient)) if row is not None else DEFAULT_CALIBRATION
    clamped = min(max(ratio, Decimal(0)), Decimal(2))
    after = (before + CALIBRATION_STEP * (clamped - before)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    if row is None:
        session.add(
            LeverCalibration(
                shop_id=shop_id, lever=lever, coefficient=after, readings=1, updated_at=now
            )
        )
    else:
        row.coefficient = after
        row.readings = (row.readings or 0) + 1
        row.updated_at = now
    await session.flush()
    return before, after


# --- the read ---------------------------------------------------------------------------


def _round2(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def final_label(
    *,
    target_reached: bool,
    pct_of_expected: int | None,
    inconclusive: bool,
) -> str:
    """The contract's day-14 thresholds."""
    if inconclusive or pct_of_expected is None:
        return LABEL_CHUA_KET_LUAN
    if pct_of_expected >= 100 and target_reached:
        return LABEL_DAT
    if pct_of_expected >= 70:
        return LABEL_GAN_DAT
    return LABEL_KHONG_DAT


def daily_metric_series(
    rows: Iterable[AnalyticsPerformanceInterval | ChannelRow], start: date, end: date
) -> dict[str, list[float | None]]:
    """Each band metric's value per day over ``[start, end]`` (D29.9 default bands)."""
    by_day: dict[date, list[AnalyticsPerformanceInterval | ChannelRow]] = {}
    for row in rows:
        if start <= row.start_date <= end:
            by_day.setdefault(row.start_date, []).append(row)
    out: dict[str, list[float | None]] = {m: [] for m in METRIC_UNITS}
    for day in sorted(by_day):
        totals = window_totals(by_day[day], day, day)
        for metric in METRIC_UNITS:
            value = totals.value(metric)
            out[metric].append(None if value is None else float(value))
    return out


#: Aliases the seller rules payload also carries (the card's metric names).
_BAND_ALIASES: Mapping[str, str] = {"conversion_rate": "ctor", "gmv_per_order": "aov"}


async def shop_band_defaults(
    session: AsyncSession, shop_id: uuid.UUID, *, days: int = 14
) -> dict[str, float]:
    """D29.9 for the seller's "Ngưỡng giữ ổn định": metric -> default ± % band.

    The shop's products summed per day over the last ``days`` stored days, each
    metric's window-mean band × ``guard_band_mult``. Keyed by the band metrics
    (``impressions``, ``ctr``, ``conversion_rate``, ...) plus the card metric
    aliases ``ctor`` and ``aov``. A card's own measurement computes the same
    band on its product (``measure_run``); this is the shop-wide default shown
    before any card exists.
    """
    # One statement: the last stored day and the ``days`` before it.
    last_day_sq = (
        select(func.max(AnalyticsPerformanceInterval.start_date))
        .where(
            AnalyticsPerformanceInterval.shop_id == shop_id,
            AnalyticsPerformanceInterval.grain == _DAILY_PRODUCT_GRAIN,
        )
        .scalar_subquery()
    )
    rows = list(
        (
            await session.execute(
                select(AnalyticsPerformanceInterval).where(
                    AnalyticsPerformanceInterval.shop_id == shop_id,
                    AnalyticsPerformanceInterval.grain == _DAILY_PRODUCT_GRAIN,
                    AnalyticsPerformanceInterval.hour_index.is_(None),
                    AnalyticsPerformanceInterval.start_date > last_day_sq - timedelta(days=days),
                    AnalyticsPerformanceInterval.start_date <= last_day_sq,
                )
            )
        ).scalars()
    )
    if not rows:
        return {}
    last_day = max(r.start_date for r in rows)
    first = last_day - timedelta(days=days - 1)
    tunables = await diag_tunables(session, shop_id)
    bands = default_bands(
        daily_metric_series(rows, first, last_day),
        guard_band_mult=tunables.guard_band_mult,
    )
    out = {metric: float(band) for metric, band in bands.items()}
    for metric, alias in _BAND_ALIASES.items():
        if metric in out:
            out[alias] = out[metric]
    return out


def _moved_bands(before: Decimal | None, after: Decimal | None, band_pct: Decimal | None) -> bool:
    """The window mean moved up by more than ``band_pct`` % of the before value."""
    if before is None or after is None or band_pct is None or before <= 0:
        return False
    return (after - before) / before * 100 > band_pct


def _gmv_holds(before: Decimal | None, after: Decimal | None, band_pct: Decimal | None) -> bool:
    """GMV did not fall by more than its band (no GMV data: cannot tell, holds)."""
    if before is None or after is None or before <= 0:
        return True
    band = band_pct if band_pct is not None else Decimal(0)
    return (before - after) / before * 100 <= band


def day7_verdict(
    *,
    pre_value: Decimal | None,
    post_value: Decimal | None,
    band_pct: Decimal | None,
    pre_gmv: Decimal | None,
    post_gmv: Decimal | None,
    gmv_band_pct: Decimal | None,
) -> str:
    """D29.8 day 7: "rising" when the target moved > 1 band up and GMV held, else "unclear"."""
    rising = _moved_bands(pre_value, post_value, band_pct) and _gmv_holds(
        pre_gmv, post_gmv, gmv_band_pct
    )
    return VERDICT_RISING if rising else VERDICT_UNCLEAR


def day14_verdict(
    *,
    pre_value: Decimal | None,
    post_value: Decimal | None,
    band_pct: Decimal | None,
    target: Decimal | None,
    pre_gmv: Decimal | None,
    post_gmv: Decimal | None,
    gmv_band_pct: Decimal | None,
) -> str | None:
    """D29.8 day 14: "met" (moved > 1 band, at the KPI target, GMV held), "partial"
    (moved or reached, not both with GMV held), "not_met"; ``None`` without data."""
    if pre_value is None or post_value is None:
        return None
    moved = _moved_bands(pre_value, post_value, band_pct)
    reached = target is not None and post_value >= target
    holds = _gmv_holds(pre_gmv, post_gmv, gmv_band_pct)
    if moved and holds and (reached or target is None):
        return VERDICT_MET
    if moved or reached:
        return VERDICT_PARTIAL
    return VERDICT_NOT_MET


def day14_strength(
    *,
    pre_value: Decimal | None,
    post_value: Decimal | None,
    pre_band_pct: Decimal | None,
    post_band_pct: Decimal | None,
) -> str | None:
    """D31.7: the target metric's change (% of the pre-window value) graded against
    the pre and post windows' window-mean bands combined; None without data."""
    if pre_value is None or post_value is None or pre_value <= 0:
        return None
    change = float((post_value - pre_value) / pre_value * 100)
    return change_strength(
        change,
        None if pre_band_pct is None else float(pre_band_pct),
        None if post_band_pct is None else float(post_band_pct),
    )


def _today() -> date:
    return (datetime.now(UTC) + _SHOP_OFFSET).date()


async def measure_run(
    session: AsyncSession,
    shop_id: uuid.UUID,
    run: WorkflowRunRow,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """The contract §6 body for one of the shop's runs (see module docstring)."""
    if run.shop_id != shop_id:
        raise NotMeasurable("not_found", "Không tìm thấy lượt chạy.")
    if run.reverts_run_id is not None:
        raise NotMeasurable("revert_run", "Lượt hoàn tác không được đo riêng.")
    product = await session.get(Product, run.product_id) if run.product_id else None
    if product is None or product.shop_id != shop_id:
        raise NotMeasurable("no_product", "Lượt chạy này không gắn với sản phẩm nào.")
    flow = (
        await session.execute(
            select(RunLeverFlow).where(
                RunLeverFlow.shop_id == shop_id, RunLeverFlow.workflow_run_id == run.id
            )
        )
    ).scalar_one_or_none()
    is_promotion = flow is not None and flow.kind == FLOW_PROMOTION
    if is_promotion:
        assert flow is not None
        day0 = flow.measurement_start
        if day0 is None:
            raise NotMeasurable(
                "not_verified",
                "Juli chưa tìm thấy khuyến mãi trên TikTok, nên chưa bắt đầu đo.",
            )
    else:
        if run.write_mode == WRITE_MODE_SIMULATED:
            # Fast track P61-B (D71.2): the listing write went to the sandbox
            # merchant, not the seller's shop -- there is no change to measure.
            # (A promotion run writes nothing: the seller applies it, so its
            # write mode says nothing about it and it is measured as before.)
            raise NotMeasurable("simulated", SIMULATED_RUN_NOT_MEASURED_VI)
        day0 = await _listing_day0(session, shop_id, run.id)
        if day0 is None:
            raise NotMeasurable(
                "nothing_written", "Lượt chạy này chưa thay đổi gì trên TikTok Shop để đo."
            )

    card = await session.get(ActionCard, run.action_card_id) if run.action_card_id else None
    target = card_target(card if card is not None and card.shop_id == shop_id else None)
    lever = target.lever or (flow.lever if flow is not None else None)
    day7, day14 = day0 + timedelta(days=7), day0 + timedelta(days=14)
    now = today or _today()

    kinds, confounded = await _reading_kinds(session, run.id)
    if is_promotion:
        stage = STAGE_FINAL if now >= day14 else STAGE_DAY7 if now >= day7 else STAGE_WAITING
    else:
        stage = (
            STAGE_FINAL
            if "final" in kinds
            else STAGE_DAY7
            if "preliminary" in kinds
            else STAGE_WAITING
        )

    pre_start, pre_end = day0 - timedelta(days=14), day0 - timedelta(days=1)
    rows = await _daily_rows(session, shop_id, product.tiktok_product_id, pre_start, day14)
    pre = window_totals(rows, pre_start, pre_end)
    post_end = day14 if stage == STAGE_FINAL else day7
    post = window_totals(rows, day0 + timedelta(days=1), post_end)

    kpi_key = target.kpi_key
    target_metric = KPI_METRIC.get(kpi_key or "")
    unit = METRIC_UNITS.get(target_metric or "", "ratio")
    # D32: the target metric is read on the channel its KPI was set on.
    channel = target.channel
    on_channel = (
        channel is not None
        and channel != CHANNEL_TOTAL
        and channel in CONTENT_TYPE
        and kpi_key in CHANNEL_METRICS
    )
    target_rows: list[Any] = channel_rows(rows, channel) if on_channel and channel else list(rows)
    pre_t = window_totals(target_rows, pre_start, pre_end)
    post_t = window_totals(target_rows, day0 + timedelta(days=1), post_end)
    progress_from = (
        target.current + PROGRESS_SHARE * (target.target - target.current)
        if target.current is not None and target.target is not None
        else None
    )
    label = _KPI_TARGET_LABEL.get(kpi_key or "", "Chỉ số mục tiêu")
    if channel is not None and kpi_key is not None and kpi_key in _KPI_SHORT:
        measured = channel if on_channel else CHANNEL_TOTAL
        label = f"{_KPI_SHORT[kpi_key]} · {measured_on_vi(measured)}"
    target_body = {
        "label": label,
        "current": _number(target.current, unit),
        "target": _number(target.target, unit),
        "progress_from": _number(progress_from, unit),
        "unit": unit,
    }
    if channel is not None:
        target_body["channel"] = channel if on_channel else CHANNEL_TOTAL

    configured = await shop_rules.stability_bands(session, shop_id)
    tunables = await diag_tunables(session, shop_id)
    pre_series = daily_metric_series(rows, pre_start, pre_end)
    # D29.8: success is judged against 1 window-mean band; D29.9: the guard
    # default is guard_band_mult × that band, a seller band wins.
    window_bands = default_bands(pre_series)
    if on_channel and target_metric is not None:
        channel_series = daily_metric_series(target_rows, pre_start, pre_end)
        window_bands.pop(target_metric, None)
        window_bands.update(default_bands({target_metric: channel_series[target_metric]}))
    guard_defaults = default_bands(pre_series, guard_band_mult=tunables.guard_band_mult)
    effective = effective_bands(configured, guard_defaults)
    bands: list[dict[str, Any]] = []
    band_status: dict[str, bool | None] = {}
    for metric, (band, band_source) in sorted(effective.items()):
        if metric == target_metric or metric not in METRIC_LABELS_VI:
            continue
        m_unit = METRIC_UNITS[metric]
        before = pre.value(metric)
        low = high = None
        if before is not None:
            low = before * (1 - band / 100)
            high = before * (1 + band / 100)
        bands.append(
            {
                "key": metric,
                "label": METRIC_LABELS_VI[metric],
                "before": _number(before, m_unit),
                "band_pct": float(band) if band != band.to_integral_value() else int(band),
                "low": _number(low, m_unit),
                "high": _number(high, m_unit),
                "unit": m_unit,
                "source": band_source,
            }
        )
        actual = post.value(metric) if stage != STAGE_WAITING else None
        band_status[metric] = (
            None if actual is None or low is None or high is None else bool(low <= actual <= high)
        )

    expected = target.expected_gmv_per_day
    question = (
        await session.execute(
            select(RunRevertQuestion.id).where(
                RunRevertQuestion.shop_id == shop_id, RunRevertQuestion.workflow_run_id == run.id
            )
        )
    ).scalar_one_or_none()
    known = [ok for ok in band_status.values() if ok is not None]
    within = None if not bands or stage == STAGE_WAITING or not known else all(known)

    final: dict[str, Any] | None = None
    if stage == STAGE_FINAL:
        final = await _final(
            session,
            shop_id=shop_id,
            run=run,
            lever=lever,
            tiktok_product_id=product.tiktok_product_id,
            window=(pre_start, day14),
            pre=pre,
            post=post,
            target_post=post_t,
            target=target,
            target_metric=target_metric,
            confounded=confounded,
        )

    body_rows: list[dict[str, Any]] = []
    if stage != STAGE_WAITING:
        body_rows = _rows(
            stage=stage,
            kpi_key=kpi_key,
            target_metric=target_metric,
            target=target,
            progress_from=progress_from,
            pre=pre,
            post=post,
            target_pre=pre_t,
            target_post=post_t,
            bands=bands,
            band_status=band_status,
            expected=expected,
            final=final,
        )

    verdict: dict[str, Any] = {
        "day7": None,
        "day14": None,
        # D31.7: the day-14 target change against the pre/post bands combined.
        "strength": None,
        "affected_by_external_change": False,
    }
    if target_metric is not None and stage != STAGE_WAITING:
        target_band = window_bands.get(target_metric)
        gmv_band = window_bands.get("gmv")
        if not target.day14_only:
            post7 = window_totals(rows, day0 + timedelta(days=1), day7)
            post7_t = window_totals(target_rows, day0 + timedelta(days=1), day7)
            verdict["day7"] = day7_verdict(
                pre_value=pre_t.value(target_metric),
                post_value=post7_t.value(target_metric),
                band_pct=target_band,
                pre_gmv=pre.value("gmv"),
                post_gmv=post7.value("gmv"),
                gmv_band_pct=gmv_band,
            )
        if stage == STAGE_FINAL:
            verdict["day14"] = day14_verdict(
                pre_value=pre_t.value(target_metric),
                post_value=post_t.value(target_metric),
                band_pct=target_band,
                target=target.target,
                pre_gmv=pre.value("gmv"),
                post_gmv=post.value("gmv"),
                gmv_band_pct=gmv_band,
            )
            if verdict["day14"] is not None:
                post_series = daily_metric_series(target_rows, day0 + timedelta(days=1), post_end)
                verdict["strength"] = day14_strength(
                    pre_value=pre_t.value(target_metric),
                    post_value=post_t.value(target_metric),
                    pre_band_pct=target_band,
                    post_band_pct=default_bands({target_metric: post_series[target_metric]}).get(
                        target_metric
                    ),
                )

    body: dict[str, Any] = {
        "stage": stage,
        "dates": {"day7": day7.isoformat(), "day14": day14.isoformat()},
        "target": target_body,
        "expected_gmv_per_day": _number(expected, "vnd"),
        "bands": bands,
        "rows": body_rows,
        "day7": {
            "within_band": within,
            "question_id": str(question) if question is not None else None,
        },
        "final": final,
    }
    # D29.8 / D30.4: an external change overlapping the window (the measurement's
    # ``external_changes``, when present) marks the day-14 label.
    external = body.get("external_changes")
    verdict["affected_by_external_change"] = bool(external) and verdict["day14"] is not None
    body["verdict"] = verdict
    return body


def _rows(
    *,
    stage: str,
    kpi_key: str | None,
    target_metric: str | None,
    target: CardTarget,
    progress_from: Decimal | None,
    pre: WindowTotals,
    post: WindowTotals,
    target_pre: WindowTotals,
    target_post: WindowTotals,
    bands: list[dict[str, Any]],
    band_status: Mapping[str, bool | None],
    expected: Decimal | None,
    final: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if target_metric is not None and kpi_key is not None:
        unit = METRIC_UNITS[target_metric]
        actual = target_post.value(target_metric)
        if final is not None:
            verdict, tone = LABELS_VI[final["label"]], _LABEL_TONE[final["label"]]
        elif actual is None:
            verdict, tone = "Chưa đủ dữ liệu", "muted"
        elif target.target is not None and actual >= target.target:
            verdict, tone = "Đang lên", "ok"
        elif progress_from is not None and actual >= progress_from:
            verdict, tone = "Đang lên", "ok"
        else:
            verdict, tone = "Chưa rõ", "warn"
        rows.append(
            {
                "key": kpi_key,
                "label": f"{_KPI_SHORT[kpi_key]} (chỉ số chính)",
                "before": _number(target_pre.value(target_metric), unit),
                "expected": format_value(target.target, unit),
                "actual": _number(actual, unit),
                "verdict": verdict,
                "tone": tone,
            }
        )
    for band in bands:
        metric = band["key"]
        unit = band["unit"]
        status = band_status.get(metric)
        if status is None:
            verdict, tone = "Chưa đủ dữ liệu", "muted"
        elif status:
            verdict, tone = "Giữ ổn định", "muted"
        else:
            verdict, tone = "Ngoài khoảng", "warn"
        expected_range = (
            format_range(Decimal(str(band["low"])), Decimal(str(band["high"])), unit)
            if band["low"] is not None and band["high"] is not None
            else "—"
        )
        rows.append(
            {
                "key": metric,
                "label": band["label"],
                "before": band["before"],
                "expected": expected_range,
                "actual": _number(post.value(metric), unit),
                "verdict": verdict,
                "tone": tone,
            }
        )
    pre_gmv, post_gmv = pre.value("gmv"), post.value("gmv")
    incremental = post_gmv - pre_gmv if pre_gmv is not None and post_gmv is not None else None
    if final is not None:
        gmv_verdict, gmv_tone = LABELS_VI[final["label"]], _LABEL_TONE[final["label"]]
    else:
        gmv_verdict, gmv_tone = "Sơ bộ", "muted"
    rows.append(
        {
            "key": "gmv_per_day",
            "label": "GMV/ngày",
            "before": _number(pre_gmv, "vnd"),
            "expected": ("+" + format_value(expected, "vnd")) if expected is not None else "—",
            "actual": _number(incremental, "vnd"),
            "verdict": gmv_verdict,
            "tone": gmv_tone,
        }
    )
    return rows


async def _final(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    run: WorkflowRunRow,
    lever: str | None,
    tiktok_product_id: str,
    window: tuple[date, date],
    pre: WindowTotals,
    post: WindowTotals,
    target_post: WindowTotals,
    target: CardTarget,
    target_metric: str | None,
    confounded: bool,
) -> dict[str, Any]:
    """The stored verdict, or compute, store and calibrate it once."""
    stored = (
        await session.execute(
            select(RunMeasurementFinal).where(
                RunMeasurementFinal.shop_id == shop_id,
                RunMeasurementFinal.workflow_run_id == run.id,
            )
        )
    ).scalar_one_or_none()
    if stored is not None:
        return _final_body(stored)

    expected = target.expected_gmv_per_day
    pre_gmv, post_gmv = pre.value("gmv"), post.value("gmv")
    actual = post_gmv - pre_gmv if pre_gmv is not None and post_gmv is not None else None
    other = await _other_changes(session, shop_id, run.id, tiktok_product_id, *window)
    thin = post.days < MIN_POST_DAYS or pre.days < MIN_PRE_DAYS or post.sku_orders < MIN_POST_ORDERS
    pct = (
        int((actual / expected * 100).to_integral_value(rounding=ROUND_HALF_UP))
        if actual is not None and expected is not None and expected > 0
        else None
    )
    target_value = target_post.value(target_metric) if target_metric else None
    reached = (
        target_value is not None and target.target is not None and target_value >= target.target
    )
    label = final_label(
        target_reached=reached, pct_of_expected=pct, inconclusive=thin or other or confounded
    )
    calibration_from = calibration_to = None
    if lever is not None:
        if label == LABEL_CHUA_KET_LUAN or actual is None or expected is None or expected <= 0:
            calibration_from = calibration_to = await current_calibration(session, shop_id, lever)
        else:
            calibration_from, calibration_to = await _update_calibration(
                session, shop_id, lever, actual / expected
            )
    row = RunMeasurementFinal(
        shop_id=shop_id,
        workflow_run_id=run.id,
        lever=lever,
        label=label,
        gmv_actual_per_day=(
            actual.quantize(Decimal("1"), rounding=ROUND_HALF_UP) if actual is not None else None
        ),
        pct_of_expected=pct,
        calibration_from=calibration_from,
        calibration_to=calibration_to,
    )
    session.add(row)
    await session.flush()
    # Fast track P60-1a: the run's card gets its impact_final row (never raises).
    from juli_backend.services import card_events

    await card_events.record_measurement_final(session, row)
    return _final_body(row)


def _final_body(row: RunMeasurementFinal) -> dict[str, Any]:
    calibration = None
    if row.lever is not None and row.calibration_from is not None:
        calibration = {
            "lever": row.lever,
            "from": _round2(Decimal(str(row.calibration_from))),
            "to": _round2(Decimal(str(row.calibration_to))),
        }
    return {
        "label": row.label,
        "gmv_actual_per_day": (
            int(row.gmv_actual_per_day) if row.gmv_actual_per_day is not None else None
        ),
        "pct_of_expected": row.pct_of_expected,
        "calibration": calibration,
    }


__all__ = [
    "DEFAULT_CALIBRATION",
    "LABELS_VI",
    "NotMeasurable",
    "STAGE_DAY7",
    "STAGE_FINAL",
    "STAGE_WAITING",
    "ChannelRow",
    "WindowTotals",
    "card_target",
    "channel_rows",
    "current_calibration",
    "day14_strength",
    "fleet_calibration_stats",
    "shop_calibration_stats",
    "shop_band_defaults",
    "shop_calibrations",
    "final_label",
    "format_value",
    "measure_run",
    "window_totals",
]
