"""The seller's polled run list (ADR-083 T4, #1310).

A read model, not a resource: each item is assembled from ``workflow_runs``,
the bound product, the latest ``workflow.status`` narration, and -- for a
run paused on a CONFIRM -- its pending confirmation. No tool names, playbook
keys or internal identifiers leave this function.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Exists, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import (
    WRITE_MODE_SIMULATED,
    Product,
    RunConfirmation,
    ToolExecution,
)
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.models import WorkflowRunEvent as WorkflowRunEventRow
from juli_backend.services import lever_flows
from juli_backend.services.agent_runs.confirmations import (
    PENDING_CONFIRMATION_STATUS,
    WAITING_APPROVAL_RUN_STATUS,
)
from juli_backend.services.agent_runs.listing_quality import (
    MAX_RUNS,
    ListingQuality,
    current_readings,
    day0_reading,
)

STATUS_EVENT_TYPE = "workflow.status"


@dataclass(frozen=True)
class PendingDecision:
    tool_call_id: str
    expires_at: str


@dataclass(frozen=True)
class RunListItem:
    id: uuid.UUID
    status: str
    stop_reason: str | None
    product_name: str
    created_at: str
    completed_at: str | None
    running_seconds_elapsed: int
    latest_narration: str | None
    decision_summary: PendingDecision | None
    #: Fast track P10-B (contract §4/§5): ``photo`` / ``seller_action`` while the
    #: run waits for the seller, else ``None``.
    awaiting: str | None = None
    #: P10 integration: the Quyết định card (``action_cards.id``) this run came
    #: from, so the UI joins runs to cards by id rather than by product name.
    decision_id: uuid.UUID | None = None
    #: Fast track P61-B (D71.2): the run's writes went to the sandbox merchant,
    #: not the seller's shop. The run surface says "chạy thử" instead of
    #: "Đã áp dụng". True only for a run that actually wrote.
    simulated: bool = False
    #: P66 (D20-D22): ``create`` / ``promotion`` for the sandbox create workflows, else
    #: ``None`` -- so the run panel picks its step plan and header from the run itself,
    #: also after a reload when the card it came from is no longer on the desk. A flow
    #: name, not the playbook key.
    run_flow: str | None = None
    #: P66: for a sandbox reviewer, whether the reviewer started this run (approved its
    #: card) -- "Hoàn tác" is offered only then. ``None`` for every other viewer.
    started_by_viewer: bool | None = None
    #: P67 (D75 Q2): for a sandbox reviewer, what this run wrote on TikTok and when
    #: TikTok confirmed it (Đo lường lists every such run). ``None`` for every other viewer.
    confirmed_write: ConfirmedWrite | None = None
    #: P71: for a sandbox reviewer's listing-edit run TikTok confirmed, TikTok's own
    #: listing diagnosis at Ngày 0 and now (``listing_quality``). ``None`` otherwise.
    listing_quality: ListingQuality | None = None


#: ``ConfirmedWrite.kind`` values.
WRITE_CREATE_PRODUCT = "create_product"
WRITE_CREATE_PROMOTION = "create_promotion"
WRITE_LISTING_EDIT = "listing_edit"
WRITE_PRICE_EDIT = "price_edit"
#: The WRITE tools a run's confirmed write is read from (tool name -> kind). The image
#: upload only stages a picture for a listing edit; it is not a change of its own.
_WRITE_KINDS: dict[str, str] = {
    "create_product": WRITE_CREATE_PRODUCT,
    "create_product_discount": WRITE_CREATE_PROMOTION,
    "update_product_listing": WRITE_LISTING_EDIT,
    "update_product_price": WRITE_PRICE_EDIT,
}


@dataclass(frozen=True)
class ConfirmedWrite:
    """P67 (D75 Q2): one run's last WRITE TikTok confirmed (ledger ``succeeded``).

    ``tiktok_id``: the new product's id (create), the promotion activity id (discount),
    the edited product's id (listing / price edit). ``fields``: what a listing edit
    changed (``title`` / ``description``).
    """

    kind: str
    tiktok_id: str | None
    confirmed_at: str | None
    discount_pct: int | None = None
    fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunViewer:
    """P66: a sandbox reviewer reads only its own runs and the shop's runs since the
    reviewer account was created -- never the team's older verification runs."""

    user_id: uuid.UUID
    since: datetime | None


#: The workflows whose runs carry a ``run_flow``.
_RUN_FLOWS: dict[str, str] = {"create_product": "create", "create_promotion": "promotion"}


#: A ledger row the agent wrote for a WRITE that went through.
_SUCCEEDED = "succeeded"


async def list_runs(
    session: AsyncSession, shop_id: uuid.UUID, *, limit: int, viewer: RunViewer | None = None
) -> list[RunListItem]:
    """The shop's runs, newest first. A queued run with no events is still listed.

    At most three statements whatever the number of runs (P22, P69): the runs -- each
    with its product, its latest narration and (for a sandbox reviewer) whether the
    viewer approved its card, all in ONE statement -- every waiting run's pending
    confirmation (only when one waits), and the ledger rows the confirmed / simulated
    write flags are read from (only when a viewer or a simulated run needs them). This
    used to read the narration (and the confirmation) once PER RUN -- up to 200
    sequential round trips for the default limit, ~220 ms each in production.
    """
    narration = (
        select(WorkflowRunEventRow.payload)
        .where(
            WorkflowRunEventRow.workflow_run_id == WorkflowRunRow.id,
            WorkflowRunEventRow.event_type == STATUS_EVENT_TYPE,
        )
        .order_by(WorkflowRunEventRow.sequence_number.desc())
        .limit(1)
        .correlate(WorkflowRunRow)
        .scalar_subquery()
    )
    statement = (
        select(WorkflowRunRow, Product, narration.label("narration"))
        .where(WorkflowRunRow.shop_id == shop_id)
        .join(Product, WorkflowRunRow.product_id == Product.id)
        .order_by(WorkflowRunRow.created_at.desc())
        .limit(limit)
    )
    if viewer is not None:
        statement = statement.add_columns(_approved_by(viewer.user_id).label("started_by_viewer"))
    result = await session.execute(statement)
    rows: list[tuple[WorkflowRunRow, Product]] = []
    narrations: dict[uuid.UUID, str | None] = {}
    mine: set[uuid.UUID] = set()
    for row in result.all():
        run, product = row[0], row[1]
        rows.append((run, product))
        narrations[run.id] = _narration_of(row[2])
        if viewer is not None and row[3]:
            mine.add(run.id)
    if viewer is not None:
        rows = [
            (run, product)
            for run, product in rows
            if run.id in mine or (viewer.since is not None and run.created_at >= viewer.since)
        ]
    waiting = [run.id for run, _ in rows if run.status == WAITING_APPROVAL_RUN_STATUS]
    decisions = await _pending_decisions(session, waiting)
    written, simulated = await _ledger_flags(
        session,
        rows if viewer is not None else [],
        [run.id for run, _ in rows if run.write_mode == WRITE_MODE_SIMULATED],
    )
    quality = await _listing_quality(session, shop_id, rows, written) if viewer is not None else {}
    items: list[RunListItem] = []
    for run, product in rows:
        items.append(
            RunListItem(
                id=run.id,
                status=run.status,
                stop_reason=run.stop_reason,
                product_name=product.name,
                created_at=_iso(run.created_at) or "",
                completed_at=_iso(run.completed_at),
                running_seconds_elapsed=run.running_seconds_elapsed,
                latest_narration=narrations.get(run.id),
                decision_summary=decisions.get(run.id),
                awaiting=lever_flows.awaiting_of(run),
                decision_id=run.action_card_id,
                simulated=run.id in simulated,
                run_flow=_RUN_FLOWS.get(run.workflow_key),
                started_by_viewer=(run.id in mine) if viewer is not None else None,
                confirmed_write=written.get(run.id),
                listing_quality=quality.get(run.id),
            )
        )
    return items


async def _listing_quality(
    session: AsyncSession,
    shop_id: uuid.UUID,
    rows: list[tuple[WorkflowRunRow, Product]],
    written: dict[uuid.UUID, ConfirmedWrite],
) -> dict[uuid.UUID, ListingQuality]:
    """P71: TikTok's listing diagnosis before / now for the newest listing-edit runs
    TikTok confirmed (sandbox reviewer only; :mod:`.listing_quality`)."""
    edits = [
        (run, written[run.id].tiktok_id or product.tiktok_product_id)
        for run, product in rows
        if run.id in written and written[run.id].kind == WRITE_LISTING_EDIT
    ][:MAX_RUNS]
    edits = [(run, product_id) for run, product_id in edits if product_id]
    if not edits:
        return {}
    now = await current_readings(session, shop_id, [product_id for _, product_id in edits])
    return {
        run.id: ListingQuality(before=day0_reading(run.state), after=now.get(product_id))
        for run, product_id in edits
    }


async def _ledger_flags(
    session: AsyncSession,
    confirmed_rows: list[tuple[WorkflowRunRow, Product]],
    simulated_run_ids: list[uuid.UUID],
) -> tuple[dict[uuid.UUID, ConfirmedWrite], set[uuid.UUID]]:
    """Each of ``confirmed_rows``' last WRITE TikTok confirmed, and which of
    ``simulated_run_ids`` wrote something -- both from ONE ledger statement (P69; was two).

    A refused write (``ok: false``, P64 D10) never counts as confirmed.
    """
    if not confirmed_rows and not simulated_run_ids:
        return {}, set()
    from juli_backend.services.agent import composition

    products = {run.id: product for run, product in confirmed_rows}
    measurable = set(composition.measurable_write_tool_names()) if simulated_run_ids else set()
    run_ids = set(products) | set(simulated_run_ids)
    tool_names = (set(_WRITE_KINDS) if products else set()) | measurable
    result = await session.execute(
        select(ToolExecution)
        .where(
            ToolExecution.workflow_run_id.in_(list(run_ids)),
            ToolExecution.status == _SUCCEEDED,
            ToolExecution.tool_name.in_(sorted(tool_names)),
        )
        .order_by(ToolExecution.updated_at)
    )
    simulated_wanted = set(simulated_run_ids)
    found: dict[uuid.UUID, ConfirmedWrite] = {}
    simulated: set[uuid.UUID] = set()
    for execution in result.scalars().all():
        run_id = execution.workflow_run_id
        if run_id is None:
            continue
        if run_id in simulated_wanted and execution.tool_name in measurable:
            simulated.add(run_id)
        if run_id not in products or execution.tool_name not in _WRITE_KINDS:
            continue
        outcome = _outcome(execution.outcome_json)
        if outcome.get("ok") is False:
            continue
        found[run_id] = _confirmed_write(
            execution, outcome, product_tiktok_id=products[run_id].tiktok_product_id
        )
    return found, simulated


def _outcome(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _confirmed_write(
    execution: ToolExecution, outcome: dict[str, Any], *, product_tiktok_id: str | None
) -> ConfirmedWrite:
    kind = _WRITE_KINDS[execution.tool_name]
    confirmed_at = outcome.get("confirmed_at")
    if not isinstance(confirmed_at, str) or not confirmed_at:
        confirmed_at = _iso(execution.updated_at)
    if kind == WRITE_CREATE_PRODUCT:
        tiktok_id = outcome.get("tiktok_product_id")
    elif kind == WRITE_CREATE_PROMOTION:
        tiktok_id = outcome.get("activity_id")
    else:
        tiktok_id = product_tiktok_id
    pct = outcome.get("discount_pct")
    fields = tuple(f for f in ("title", "description") if outcome.get(f))
    return ConfirmedWrite(
        kind=kind,
        tiktok_id=str(tiktok_id) if tiktok_id else None,
        confirmed_at=confirmed_at,
        discount_pct=pct if isinstance(pct, int) and not isinstance(pct, bool) else None,
        fields=fields if kind == WRITE_LISTING_EDIT else (),
    )


def _approved_by(user_id: uuid.UUID) -> Exists:
    """Whether ``user_id`` approved the run's card (P66), as a column of the runs read."""
    from juli_backend.models.models import ActionCardApproval

    return exists().where(
        ActionCardApproval.action_card_id == WorkflowRunRow.action_card_id,
        ActionCardApproval.approved_by_user_id == user_id,
    )


def _narration_of(payload: object) -> str | None:
    return payload.get("phase_narration") if isinstance(payload, dict) else None


async def _pending_decisions(
    session: AsyncSession, run_ids: list[uuid.UUID]
) -> dict[uuid.UUID, PendingDecision]:
    """Each waiting run's pending confirmation (one per run), in one statement."""
    if not run_ids:
        return {}
    result = await session.execute(
        select(RunConfirmation).where(
            RunConfirmation.workflow_run_id.in_(run_ids),
            RunConfirmation.status == PENDING_CONFIRMATION_STATUS,
        )
    )
    found: dict[uuid.UUID, PendingDecision] = {}
    for confirmation in result.scalars().all():
        found.setdefault(confirmation.workflow_run_id, _decision_of(confirmation))
    return found


def _decision_of(confirmation: RunConfirmation) -> PendingDecision:
    return PendingDecision(
        tool_call_id=confirmation.tool_call_id,
        expires_at=_iso(confirmation.expires_at) or str(confirmation.expires_at),
    )


async def _latest_narration(session: AsyncSession, run_id: uuid.UUID) -> str | None:
    result = await session.execute(
        select(WorkflowRunEventRow.payload)
        .where(
            WorkflowRunEventRow.workflow_run_id == run_id,
            WorkflowRunEventRow.event_type == STATUS_EVENT_TYPE,
        )
        .order_by(WorkflowRunEventRow.sequence_number.desc())
        .limit(1)
    )
    return _narration_of(result.scalars().first())


async def _pending_decision(session: AsyncSession, run_id: uuid.UUID) -> PendingDecision | None:
    result = await session.execute(
        select(RunConfirmation)
        .where(
            RunConfirmation.workflow_run_id == run_id,
            RunConfirmation.status == PENDING_CONFIRMATION_STATUS,
        )
        .limit(1)
    )
    confirmation = result.scalars().first()
    return None if confirmation is None else _decision_of(confirmation)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


async def latest_narration(session: AsyncSession, run_id: uuid.UUID) -> str | None:
    return await _latest_narration(session, run_id)


async def pending_decision(session: AsyncSession, run_id: uuid.UUID) -> PendingDecision | None:
    return await _pending_decision(session, run_id)


__all__ = [
    "ConfirmedWrite",
    "PendingDecision",
    "RunListItem",
    "STATUS_EVENT_TYPE",
    "latest_narration",
    "list_runs",
    "pending_decision",
]
