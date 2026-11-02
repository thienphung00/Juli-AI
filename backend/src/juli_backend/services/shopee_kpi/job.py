"""The Shopee KPI job: read the contract and daily metrics, compute, store (ADR-117 step 3, G6).

- **Inputs.** The shop's current contract version (``kpi_contracts``, newest version not
  ``superseded``), its ``kpi_targets`` (flows, metrics, role) -- or ``params["flows"]``
  while no target exists --, its ``kpi_exclusions``, the ``kpi_adjustments`` of every
  version up to it, and the shop's base lever plan (``lever_plans`` with no scenario,
  enabled). All Ops-only: read under :func:`ops_role`. The daily series come from
  ``platform_daily_metrics`` under the shop's own scope (tenant-direct), order type
  ``confirmed``, shop level (``item_id = ''``), one exact (dataset, stream, segment) per
  KPI flow (:data:`FLOW_SOURCES`). ``shop_page`` is a child segment of the product card:
  it is its own flow and is never added to a total (G3).
- **Compute.** :mod:`.rules` (Phụ lục 01), :mod:`.expected_move` (milestones, both trend
  weights, flow GMV) and :mod:`.flow_glm` (CTR / CTOR band per flow).
- **Store.** One ``kpi_forecasts`` row per flow x metric x milestone x trend weight
  (``expected_move_v1``) and one per flow x rate metric for the GLM's next-14-day band
  (``flow_glm_v2``, milestone 0, trend weight NULL), all with the same ``run_at`` and
  ``inputs_sha256``. The first run of a contract version also writes its
  ``kpi_targets`` (baseline, ±D, pass / target levels, window) when none exist and
  every metric has a baseline -- append-only, so a later run never rewrites them. GLM
  parameters are never stored (client data, recomputed every run). A proposal run on
  another ``measure_start`` stores forecasts but never targets.

Nothing commits here; the caller (route or CLI) commits. Forecasts are internal (Ops),
never seller-facing (D42 G4).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.kpi_contracts import (
    CONTRACT_SUPERSEDED,
    TARGET_KPI,
    TARGET_TRACKING,
    KpiAdjustment,
    KpiContract,
    KpiExclusion,
    KpiForecast,
    KpiTarget,
    LeverPlan,
)
from juli_backend.services.ops import ops_role
from juli_backend.services.shopee_kpi import expected_move, flow_glm
from juli_backend.services.shopee_kpi.rules import (
    Adjustment,
    ContractTerms,
    DayTotals,
    FlowSpec,
    KpiReport,
    Series,
    flows_from_params,
    kpi_report,
)

PLATFORM = "shopee"
ORDER_TYPE = "confirmed"
SHOP_LEVEL_ITEM = ""
GLM_HORIZON_DAYS = 14
GLM_WINDOW_DAYS = 30
DECIMAL_PLACES = Decimal("0.000001")


@dataclass(frozen=True)
class FlowSource:
    """Where one KPI flow lives in ``platform_daily_metrics`` (ADR-117 §1, G3)."""

    dataset: str
    stream: str
    segment: str
    has_impressions: bool = True


#: KPI flow -> its exact row key. Stream / dataset names are services/ingest/mapping.py's.
FLOW_SOURCES: dict[str, FlowSource] = {
    "the_san_pham": FlowSource("traffic_overview", "product_card", "all"),
    "trang_shop": FlowSource("traffic_overview", "product_card", "shop_page"),
    "video": FlowSource("traffic_overview", "seller_video", "all"),
    "live": FlowSource("traffic_overview", "seller_live", "all"),
    "ca_shop": FlowSource("shop_overview", "total", "all", has_impressions=False),
}


class NoKpiContract(LookupError):
    """The shop has no current contract version."""


class MeasureStartMissing(ValueError):
    """The contract version has no ``measure_start`` and the run named none."""


class NoMetrics(LookupError):
    """No confirmed daily metrics for any KPI flow of the shop."""


@dataclass(frozen=True)
class KpiInputs:
    contract: KpiContract
    terms: ContractTerms
    has_targets: bool
    series: dict[str, Series]
    levers: list[expected_move.LeverEffect]

    def default_as_of(self) -> date:
        """The last day every contract flow with data has."""
        last = [max(s) for f in self.terms.flows if (s := self.series.get(f.flow))]
        if not last:
            raise NoMetrics(str(self.contract.shop_id))
        return min(last)


@dataclass(frozen=True)
class RunResult:
    contract_id: uuid.UUID
    run_at: datetime
    as_of: date
    report: KpiReport
    forecasts: list[expected_move.Forecast]
    bands: list[flow_glm.RateBand]
    targets_written: int
    inputs_sha256: str


# -- reads ---------------------------------------------------------------------------


async def current_contract(
    session: AsyncSession, shop_id: uuid.UUID, contract_id: uuid.UUID | None = None
) -> KpiContract:
    async with ops_role(session):
        stmt = select(KpiContract).where(KpiContract.shop_id == shop_id)
        if contract_id is not None:
            stmt = stmt.where(KpiContract.id == contract_id)
        else:
            stmt = stmt.where(KpiContract.status != CONTRACT_SUPERSEDED)
        row = (
            await session.execute(
                stmt.order_by(KpiContract.version.desc(), KpiContract.created_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
    if row is None:
        raise NoKpiContract(str(shop_id))
    return row


async def load_series(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, Series]:
    """flow -> day -> (impressions, clicks, orders, gmv), confirmed orders, shop level."""
    by_key = {(s.dataset, s.stream, s.segment): (f, s) for f, s in FLOW_SOURCES.items()}
    m = PlatformDailyMetric
    async with with_shop_scope(session, shop_id):
        rows = (
            await session.execute(
                select(
                    m.dataset, m.stream, m.segment, m.day, m.impressions, m.clicks, m.orders, m.gmv
                ).where(
                    m.shop_id == shop_id,
                    m.platform == PLATFORM,
                    m.order_type == ORDER_TYPE,
                    m.item_id == SHOP_LEVEL_ITEM,
                    m.dataset.in_({s.dataset for s in FLOW_SOURCES.values()}),
                    m.stream.in_({s.stream for s in FLOW_SOURCES.values()}),
                    m.segment.in_({s.segment for s in FLOW_SOURCES.values()}),
                )
            )
        ).all()
    out: dict[str, dict[date, DayTotals]] = {}
    for dataset, stream, segment, day, imp, clk, ordr, gmv in rows:
        hit = by_key.get((dataset, stream, segment))
        if hit is None:  # e.g. shop_overview x shop_page: not a KPI flow
            continue
        flow, source = hit
        out.setdefault(flow, {})[day] = (
            float(imp or 0) if source.has_impressions else 0.0,
            float(clk or 0),
            float(ordr or 0),
            float(gmv or 0),
        )
    return dict(out)


async def load_inputs(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    contract_id: uuid.UUID | None = None,
    measure_start: date | None = None,
) -> KpiInputs:
    contract = await current_contract(session, shop_id, contract_id)
    async with ops_role(session):
        targets = (
            (await session.execute(select(KpiTarget).where(KpiTarget.contract_id == contract.id)))
            .scalars()
            .all()
        )
        exclusions = (
            (
                await session.execute(
                    select(KpiExclusion.day).where(KpiExclusion.contract_id == contract.id)
                )
            )
            .scalars()
            .all()
        )
        version_ids = select(KpiContract.id).where(
            KpiContract.shop_id == shop_id,
            KpiContract.contract_ref == contract.contract_ref,
            KpiContract.version <= contract.version,
        )
        adjustments = (
            (
                await session.execute(
                    select(KpiAdjustment).where(KpiAdjustment.contract_id.in_(version_ids))
                )
            )
            .scalars()
            .all()
        )
        lever_rows = (
            (
                await session.execute(
                    select(LeverPlan).where(
                        LeverPlan.shop_id == shop_id,
                        LeverPlan.scenario_id.is_(None),
                        LeverPlan.enabled.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
    start = measure_start or contract.measure_start
    if start is None:
        raise MeasureStartMissing(str(contract.id))
    flows = _flows(targets) if targets else flows_from_params(contract.params or {})
    terms = ContractTerms.from_params(
        contract.params or {},
        measure_start=start,
        flows=flows,
        extra_excluded=exclusions,
        adjustments=[
            Adjustment(
                flow=a.flow,
                metric=a.metric,
                kind=a.kind,
                value=float(a.value),
                effective_on=a.effective_on,
            )
            for a in adjustments
            if a.flow and a.metric and a.value is not None
        ],
    )
    levers = [
        expected_move.LeverEffect(
            lever_key=r.lever_key,
            wave=int(r.wave),
            starts_on=r.starts_on,
            lag_days=int(r.lag_days or 0),
            flow=r.flow,
            metric=r.metric,
            low=float(r.low),
            high=float(r.high),
        )
        for r in lever_rows
    ]
    series = await load_series(session, shop_id)
    return KpiInputs(
        contract=contract, terms=terms, has_targets=bool(targets), series=series, levers=levers
    )


def _flows(targets: Sequence[KpiTarget]) -> list[FlowSpec]:
    """``kpi_targets`` rows -> one spec per flow, metrics in the reference order."""
    order = {"impressions": 0, "ctr": 1, "ctor": 2, "aov": 3}
    by_flow: dict[str, list[KpiTarget]] = {}
    for t in targets:
        by_flow.setdefault(t.flow, []).append(t)
    return [
        FlowSpec(
            flow=flow,
            metrics=tuple(sorted((t.metric for t in rows), key=lambda m: order.get(m, 9))),
            tracking=all(t.role == TARGET_TRACKING for t in rows),
        )
        for flow, rows in by_flow.items()
    ]


# -- compute + store ------------------------------------------------------------------


def inputs_sha256(inputs: KpiInputs, as_of: date) -> str:
    payload = {
        "terms": {k: v for k, v in inputs.terms.__dict__.items()},
        "as_of": as_of,
        "levers": [lv.__dict__ for lv in inputs.levers],
        "series": {f: sorted(s.items()) for f, s in sorted(inputs.series.items())},
    }
    blob = json.dumps(payload, sort_keys=True, default=_json_default).encode()
    return hashlib.sha256(blob).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, frozenset | set):
        return sorted(value, key=str)
    if hasattr(value, "__dict__"):
        return value.__dict__
    return str(value)


def _dec(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(repr(float(value))).quantize(DECIMAL_PLACES)


def compute_bands(series: Mapping[str, Series]) -> list[flow_glm.RateBand]:
    bands = []
    for flow in FLOW_SOURCES:
        s = series.get(flow)
        if not s:
            continue
        for metric in flow_glm.RATE_METRICS:
            model = flow_glm.fit_rate(flow, metric, s)
            if model is not None:
                bands.append(flow_glm.band(model, GLM_WINDOW_DAYS, GLM_HORIZON_DAYS))
    return bands


def _target_rows(contract_id: uuid.UUID, report: KpiReport) -> list[KpiTarget]:
    return [
        KpiTarget(
            contract_id=contract_id,
            flow=f.flow,
            metric=m.metric,
            role=TARGET_TRACKING if f.tracking else TARGET_KPI,
            baseline=_dec(m.baseline),
            d_pct=_dec(m.d_pct),
            pass_level=_dec(m.pass_level),
            target_level=_dec(m.target_level),
            window_days=m.window_days,
        )
        for f in report.flows
        for m in f.metrics
    ]


def _forecast_rows(
    shop_id: uuid.UUID,
    contract_id: uuid.UUID,
    run_at: datetime,
    sha: str,
    forecasts: Sequence[expected_move.Forecast],
    bands: Sequence[flow_glm.RateBand],
) -> list[KpiForecast]:
    rows = [
        KpiForecast(
            shop_id=shop_id,
            contract_id=contract_id,
            run_at=run_at,
            flow=f.flow,
            metric=f.metric,
            milestone=f.milestone,
            window_end=f.window_end,
            expected=_dec(f.expected),
            lo90=_dec(f.lo90),
            hi90=_dec(f.hi90),
            p_pass=_dec(min(max(f.p_pass, 0.0), 1.0)) if f.p_pass is not None else None,
            trend_weight=_dec(f.trend_weight),
            inputs_sha256=sha,
            method_version=expected_move.METHOD_VERSION,
        )
        for f in forecasts
    ]
    rows += [
        KpiForecast(
            shop_id=shop_id,
            contract_id=contract_id,
            run_at=run_at,
            flow=b.flow,
            metric=b.metric,
            milestone=0,
            window_end=b.last_day + timedelta(b.horizon_days),
            expected=_dec(b.forecast_mean),
            lo90=_dec(b.band90_low),
            hi90=_dec(b.band90_high),
            p_pass=None,
            trend_weight=None,
            inputs_sha256=sha,
            method_version=flow_glm.METHOD_VERSION,
        )
        for b in bands
    ]
    return rows


async def run_shop_kpi(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    now: datetime,
    as_of: date | None = None,
    measure_start: date | None = None,
    contract_id: uuid.UUID | None = None,
) -> RunResult:
    """Compute and store one run; the caller commits."""
    inputs = await load_inputs(
        session, shop_id, contract_id=contract_id, measure_start=measure_start
    )
    day = as_of or inputs.default_as_of()
    report = kpi_report(inputs.terms, inputs.series, day)
    forecasts = expected_move.ExpectedMove(inputs.terms, inputs.series, inputs.levers).forecasts()
    bands = compute_bands(inputs.series)
    sha = inputs_sha256(inputs, day)
    contract_pk = inputs.contract.id
    # Targets freeze the baseline: only once every metric has one (the baseline window
    # is fully exported), never for a proposal run on another start date.
    complete = all(m.baseline is not None for f in report.flows for m in f.metrics)
    write_targets = not inputs.has_targets and measure_start is None and complete
    targets = _target_rows(contract_pk, report) if write_targets else []
    async with ops_role(session):
        session.add_all(targets)
        session.add_all(_forecast_rows(shop_id, contract_pk, now, sha, forecasts, bands))
    return RunResult(
        contract_id=contract_pk,
        run_at=now,
        as_of=day,
        report=report,
        forecasts=forecasts,
        bands=bands,
        targets_written=len(targets),
        inputs_sha256=sha,
    )


async def latest_forecasts(session: AsyncSession, shop_id: uuid.UUID) -> list[KpiForecast]:
    """Every row of the shop's newest run."""
    async with ops_role(session):
        newest = (
            await session.execute(
                select(func.max(KpiForecast.run_at)).where(KpiForecast.shop_id == shop_id)
            )
        ).scalar_one_or_none()
        if newest is None:
            return []
        return list(
            (
                await session.execute(
                    select(KpiForecast)
                    .where(KpiForecast.shop_id == shop_id, KpiForecast.run_at == newest)
                    .order_by(
                        KpiForecast.method_version,
                        KpiForecast.flow,
                        KpiForecast.metric,
                        KpiForecast.milestone,
                        KpiForecast.trend_weight,
                    )
                )
            )
            .scalars()
            .all()
        )


async def current_report(
    session: AsyncSession, shop_id: uuid.UUID, *, as_of: date | None = None
) -> tuple[KpiContract, KpiReport]:
    """The KPI table now (pure arithmetic over stored rows; nothing written)."""
    inputs = await load_inputs(session, shop_id)
    return inputs.contract, kpi_report(inputs.terms, inputs.series, as_of or inputs.default_as_of())


def forecast_json(row: KpiForecast) -> dict[str, Any]:
    def num(v: Decimal | None) -> float | None:
        return None if v is None else float(v)

    return {
        "flow": row.flow,
        "metric": row.metric,
        "milestone": row.milestone,
        "window_end": row.window_end.isoformat(),
        "expected": num(row.expected),
        "lo90": num(row.lo90),
        "hi90": num(row.hi90),
        "p_pass": num(row.p_pass),
        "trend_weight": num(row.trend_weight),
        "method_version": row.method_version,
    }
