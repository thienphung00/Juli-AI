"""Measure executed Shopee proposals against their own history (ADR-118 §3, D81.1-D81.3).

For every ``executed`` item proposal with a verified execution, compare the item's
impressions / clicks / CTR in the 7 days after day 0 with the 28 days before it
(:mod:`.self_baseline` holds the rules) and append a ``shop_proposal_results`` row per
metric. A conclusive verdict (``dat`` / ``khong_dat``) on the targeted metric moves the
proposal to ``measured``; ``chua_ket_luan`` leaves it ``executed``.

- **Advance only.** A new row is written only when ``data_through`` moves past the newest
  stored row of that proposal + metric (the table is append-only). ``force`` (the
  operator's "Tính lại") also writes when the verdict or numbers changed at the same
  ``data_through``, e.g. after the contract's excluded days were edited.
- **Egress.** Before any item row is read, one ``max(day)`` over the shop's item exports
  says how far they reach; a proposal whose window cannot reach past its newest stored
  ``data_through`` is skipped without reading its rows. The rows read are
  ``(day, impressions, clicks)`` of one item, 56 days before day 0 to 7 after.
- **Ops-only.** Nothing here is shown to a seller yet (D42 G4).

Nothing commits here: the caller (the Ops route or :func:`measure_all`) commits. Reads and
writes run under the shop's own scope; the contract's excluded days come through
:func:`~juli_backend.services.shopee_kpi.contract_excluded_days` (Ops role).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.shop_proposals import (
    METHOD_SELF_BASELINE,
    STATUS_EXECUTED,
    STATUS_MEASURED,
    SUBJECT_ITEM,
    ShopProposal,
    ShopProposalExecution,
    ShopProposalResult,
)
from juli_backend.services.ops.overview import list_shops
from juli_backend.services.shop_proposals import self_baseline
from juli_backend.services.shop_proposals.self_baseline import DayTotals, Outcome
from juli_backend.services.shopee_kpi import contract_excluded_days

logger = logging.getLogger(__name__)

PLATFORM = "shopee"
#: The legacy name of the table's pre/post method; ``job_version`` tells the rule set.
METHOD = METHOD_SELF_BASELINE
JOB_VERSION = "self_baseline_v1"
DATASET = "item_performance"
STREAM = "total"
SEGMENT = "all"
ORDER_TYPE = "confirmed"
DECIMAL_PLACES = Decimal("0.000001")

#: Kinds that change what a shopper sees in the listing: they move CTR; the rest, clicks.
CTR_KINDS = frozenset({"title", "images"})
TARGET_METRICS = frozenset({"ctr", "clicks"})

SessionFactory = Callable[[], Any]


@dataclass(frozen=True)
class MeasureCounts:
    """What one run did (counts only; logged by the beat)."""

    considered: int = 0
    unchanged: int = 0
    no_data: int = 0
    written: int = 0
    measured: int = 0

    def __add__(self, other: MeasureCounts) -> MeasureCounts:
        return MeasureCounts(
            self.considered + other.considered,
            self.unchanged + other.unchanged,
            self.no_data + other.no_data,
            self.written + other.written,
            self.measured + other.measured,
        )


@dataclass(frozen=True)
class FleetSummary:
    shops: int
    failed: int
    counts: MeasureCounts


@dataclass(frozen=True)
class _Stored:
    """The columns of a stored result row that the advance rule compares."""

    data_through: date | None
    verdict: str
    value: Decimal | None
    comparison: Decimal | None


@dataclass(frozen=True)
class _Due:
    """An executed item proposal and where its newest stored result stands."""

    proposal_id: uuid.UUID
    item_id: str
    target: str
    day0: date
    newest: dict[str, _Stored]

    @property
    def through(self) -> date | None:
        """The ``data_through`` every stored metric row has reached (the smallest)."""
        stored = [r.data_through for r in self.newest.values()]
        return None if not stored or None in stored else min(d for d in stored if d)


def target_metric(kind: str, change_after: dict[str, Any]) -> str:
    """CTR for listing changes, clicks otherwise; ``change_after["target_metric"]`` overrides."""
    named = change_after.get("target_metric")
    if named in TARGET_METRICS:
        return str(named)
    return "ctr" if kind in CTR_KINDS else "clicks"


def _dec(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(repr(float(value))).quantize(DECIMAL_PLACES)


async def _due(
    session: AsyncSession, shop_id: uuid.UUID, proposal_id: uuid.UUID | None
) -> list[_Due]:
    """Executed item proposals with a verified execution, and their newest result per metric."""
    query = (
        select(
            ShopProposal.id,
            ShopProposal.item_id,
            ShopProposal.kind,
            ShopProposal.change_after,
            func.min(ShopProposalExecution.executed_at),
        )
        .join(ShopProposalExecution, ShopProposalExecution.proposal_id == ShopProposal.id)
        .where(
            ShopProposal.shop_id == shop_id,
            ShopProposal.platform == PLATFORM,
            ShopProposal.status == STATUS_EXECUTED,
            ShopProposal.subject_type == SUBJECT_ITEM,
            ShopProposalExecution.verified_at.is_not(None),
        )
        .group_by(
            ShopProposal.id, ShopProposal.item_id, ShopProposal.kind, ShopProposal.change_after
        )
    )
    if proposal_id is not None:
        query = query.where(ShopProposal.id == proposal_id)
    proposals = (await session.execute(query)).all()
    if not proposals:
        return []
    r = ShopProposalResult
    newest: dict[uuid.UUID, dict[str, _Stored]] = {}
    for pid, metric, through, verdict, value, comparison in await session.execute(
        select(r.proposal_id, r.metric, r.data_through, r.verdict, r.value, r.comparison)
        .where(r.proposal_id.in_([p[0] for p in proposals]), r.job_version == JOB_VERSION)
        .order_by(r.computed_at)
    ):
        newest.setdefault(pid, {})[metric] = _Stored(through, verdict, value, comparison)
    return [
        _Due(
            pid,
            str(item),
            target_metric(kind, after or {}),
            executed_at.date(),
            newest.get(pid, {}),
        )
        for pid, item, kind, after, executed_at in proposals
    ]


def _could_advance(due: _Due, covered_through: date | None) -> bool:
    """Whether the exports reach past what the newest stored rows already used."""
    if covered_through is None:
        return False
    if due.through is None:
        return True
    potential = min(covered_through, due.day0 + timedelta(self_baseline.POST_DAYS))
    return potential > due.through


async def _read_series(
    session: AsyncSession, shop_id: uuid.UUID, due: _Due
) -> dict[date, DayTotals]:
    """One item's (impressions, clicks) per day around day 0; the only item rows read."""
    m = PlatformDailyMetric
    rows = await session.execute(
        select(m.day, m.impressions, m.clicks).where(
            m.shop_id == shop_id,
            m.platform == PLATFORM,
            m.dataset == DATASET,
            m.stream == STREAM,
            m.segment == SEGMENT,
            m.order_type == ORDER_TYPE,
            m.item_id == due.item_id,
            m.day >= due.day0 - timedelta(self_baseline.WEEKS * 7),
            m.day <= due.day0 + timedelta(self_baseline.POST_DAYS),
        )
    )
    return {day: (float(imp or 0), float(clk or 0)) for day, imp, clk in rows}


def _changed(outcome: self_baseline.MetricOutcome, stored: _Stored) -> bool:
    return (outcome.verdict, _dec(outcome.value), _dec(outcome.comparison)) != (
        stored.verdict,
        stored.value,
        stored.comparison,
    )


def _rows(
    shop_id: uuid.UUID, due: _Due, outcome: Outcome, now: datetime, force: bool
) -> list[dict[str, Any]]:
    """The result rows to append: every metric whose ``data_through`` advanced."""
    out = []
    for m in outcome.metrics:
        stored = due.newest.get(m.metric)
        advanced = (
            stored is None
            or stored.data_through is None
            or outcome.data_through > stored.data_through
        )
        if not (advanced or (force and stored is not None and _changed(m, stored))):
            continue
        out.append(
            {
                "id": uuid.uuid4(),
                "shop_id": shop_id,
                "proposal_id": due.proposal_id,
                "method": METHOD,
                "metric": m.metric,
                "pre_from": outcome.pre_from,
                "pre_to": outcome.pre_to,
                "post_from": outcome.post_from,
                "post_to": outcome.post_to,
                "value": _dec(m.value),
                "comparison": _dec(m.comparison),
                "band": _dec(m.band),
                "verdict": m.verdict,
                "data_through": outcome.data_through,
                "job_version": JOB_VERSION,
                "detail": m.detail,
                "computed_at": now,
            }
        )
    return out


async def measure_shop_proposals(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    now: datetime,
    proposal_id: uuid.UUID | None = None,
    force: bool = False,
) -> MeasureCounts:
    """Measure the shop's executed item proposals (or just ``proposal_id``); caller commits."""
    async with with_shop_scope(session, shop_id):
        dues = await _due(session, shop_id, proposal_id)
        if not dues:
            return MeasureCounts()
        m = PlatformDailyMetric
        covered_through = await session.scalar(
            select(func.max(m.day)).where(
                m.shop_id == shop_id,
                m.platform == PLATFORM,
                m.dataset == DATASET,
                m.stream == STREAM,
                m.segment == SEGMENT,
                m.order_type == ORDER_TYPE,
            )
        )
    todo = [d for d in dues if force or _could_advance(d, covered_through)]
    counts = MeasureCounts(considered=len(dues), unchanged=len(dues) - len(todo))
    if not todo or covered_through is None:
        return counts
    excluded = await contract_excluded_days(
        session,
        shop_id,
        min(d.day0 for d in todo) - timedelta(self_baseline.WEEKS * 7),
        max(d.day0 for d in todo) + timedelta(self_baseline.POST_DAYS),
    )
    written = measured = no_data = 0
    async with with_shop_scope(session, shop_id):
        for due in todo:
            series = await _read_series(session, shop_id, due)
            if not series:
                no_data += 1
                continue
            outcome = self_baseline.evaluate(
                series,
                day0=due.day0,
                target=due.target,
                first_day=min(series),
                covered_through=covered_through,
                excluded=excluded,
            )
            rows = _rows(shop_id, due, outcome, now, force)
            if not rows:
                continue
            await session.execute(insert(ShopProposalResult), rows)
            written += len(rows)
            if outcome.of(due.target).verdict != self_baseline.VERDICT_OPEN:
                await session.execute(
                    update(ShopProposal)
                    .where(
                        ShopProposal.id == due.proposal_id, ShopProposal.status == STATUS_EXECUTED
                    )
                    .values(status=STATUS_MEASURED, updated_at=now)
                )
                measured += 1
    return MeasureCounts(
        considered=counts.considered,
        unchanged=counts.unchanged,
        no_data=no_data,
        written=written,
        measured=measured,
    )


async def measure_all(
    session_factory: SessionFactory, *, now: datetime | None = None
) -> FleetSummary:
    """Every Shopee shop in its own session and transaction; one shop never stops the rest.

    The daily beat calls this after the KPI job. Logs carry counts and shop ids only; a
    failure logs the exception type, never its message (it can carry row values).
    """
    reference = now if now is not None else datetime.now(UTC).replace(tzinfo=None)
    async with session_factory() as session:
        shop_ids = sorted(
            (s.shop_id for s in await list_shops(session) if s.platform == PLATFORM), key=str
        )
    total = MeasureCounts()
    failed = 0
    for shop_id in shop_ids:
        try:
            async with session_factory() as session:
                counts = await measure_shop_proposals(session, shop_id, now=reference)
                await session.commit()
            total += counts
        except Exception as exc:
            failed += 1
            logger.error(
                "proposal_results_shop_failed",
                extra={"shop_id": str(shop_id), "error_type": type(exc).__name__},
            )
    summary = FleetSummary(shops=len(shop_ids), failed=failed, counts=total)
    logger.info(
        "proposal_results_complete",
        extra={
            "shops": summary.shops,
            "failed": summary.failed,
            "considered": total.considered,
            "unchanged": total.unchanged,
            "no_data": total.no_data,
            "written": total.written,
            "measured": total.measured,
        },
    )
    return summary
