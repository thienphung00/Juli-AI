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
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.lever_flows import (
    FLOW_PROMOTION,
    LeverCalibration,
    RunLeverFlow,
    RunMeasurementFinal,
)
from juli_backend.models.models import (
    ActionCard,
    AnalyticsPerformanceInterval,
    ImpactReading,
    Product,
    ToolExecution,
)
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.run_changes import RunRevertQuestion, RunWriteValue
from juli_backend.services import shop_rules

STAGE_WAITING = "waiting"
STAGE_DAY7 = "day7"
STAGE_FINAL = "final"

LABEL_DAT = "dat"
LABEL_GAN_DAT = "gan_dat"
LABEL_KHONG_DAT = "khong_dat"
LABEL_CHUA_KET_LUAN = "chua_ket_luan"

LABELS_VI: Mapping[str, str] = {
    LABEL_DAT: "Đạt",
    LABEL_GAN_DAT: "Gần đạt",
    LABEL_KHONG_DAT: "Không đạt",
    LABEL_CHUA_KET_LUAN: "Chưa kết luận",
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
}
_KPI_TARGET_LABEL: Mapping[str, str] = {
    "ctr": "CTR Thẻ sản phẩm",
    "ctor": "CTOR Thẻ sản phẩm",
    "aov": "AOV (SKU)",
}
_KPI_SHORT: Mapping[str, str] = {"ctr": "CTR", "ctor": "CTOR", "aov": "AOV"}

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


def window_totals(
    rows: Iterable[AnalyticsPerformanceInterval], start: date, end: date
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

    return CardTarget(
        lever=str(lever["code"]) if lever.get("code") else None,
        kpi_key=str(kpi_key) if kpi_key in KPI_METRIC else None,
        current=dec(basis.get("current_rate")),
        target=dec(basis.get("reference_rate")),
        expected_gmv_per_day=dec(diagnosis.get("recoverable_gmv_per_day")),
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
            select(RunWriteValue.recorded_at).where(
                RunWriteValue.shop_id == shop_id,
                RunWriteValue.tiktok_product_id == tiktok_product_id,
                RunWriteValue.workflow_run_id != run_id,
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
    progress_from = (
        target.current + PROGRESS_SHARE * (target.target - target.current)
        if target.current is not None and target.target is not None
        else None
    )
    target_body = {
        "label": _KPI_TARGET_LABEL.get(kpi_key or "", "Chỉ số mục tiêu"),
        "current": _number(target.current, unit),
        "target": _number(target.target, unit),
        "progress_from": _number(progress_from, unit),
        "unit": unit,
    }

    configured = await shop_rules.stability_bands(session, shop_id)
    bands: list[dict[str, Any]] = []
    band_status: dict[str, bool | None] = {}
    for metric, band in sorted(configured.items()):
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
            bands=bands,
            band_status=band_status,
            expected=expected,
            final=final,
        )

    return {
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


def _rows(
    *,
    stage: str,
    kpi_key: str | None,
    target_metric: str | None,
    target: CardTarget,
    progress_from: Decimal | None,
    pre: WindowTotals,
    post: WindowTotals,
    bands: list[dict[str, Any]],
    band_status: Mapping[str, bool | None],
    expected: Decimal | None,
    final: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if target_metric is not None and kpi_key is not None:
        unit = METRIC_UNITS[target_metric]
        actual = post.value(target_metric)
        if final is not None:
            verdict, tone = LABELS_VI[final["label"]], _LABEL_TONE[final["label"]]
        elif actual is None:
            verdict, tone = "Chưa đủ dữ liệu", "muted"
        elif target.target is not None and actual >= target.target:
            verdict, tone = "Đạt mục tiêu", "ok"
        elif progress_from is not None and actual >= progress_from:
            verdict, tone = "Đang tăng", "ok"
        else:
            verdict, tone = "Chưa tăng", "warn"
        rows.append(
            {
                "key": kpi_key,
                "label": f"{_KPI_SHORT[kpi_key]} (chỉ số chính)",
                "before": _number(pre.value(target_metric), unit),
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
            verdict, tone = "Ổn định", "muted"
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
    target_value = post.value(target_metric) if target_metric else None
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
    "WindowTotals",
    "card_target",
    "current_calibration",
    "shop_calibrations",
    "final_label",
    "format_value",
    "measure_run",
    "window_totals",
]
