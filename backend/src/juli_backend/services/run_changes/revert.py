"""Start a "Hoàn tác" run for a finished run (fast track P8-C, ADR-109 d.9, S-FR-8).

``start_revert`` checks, in order, and refuses with an honest Vietnamese
message (``RevertRefused``) when:

1. the run is itself a revert -- a revert is not revertible (to redo the
   change, approve the original recommendation again);
2. the run has not finished;
3. the run wrote nothing (no ``run_write_values`` rows);
4. the run changed a price -- Juli never reverts prices on its own (D13);
5. a revert of this run is already running, or already restored something;
6. the live listing no longer holds Juli's after-value for a field it would
   restore -- someone changed it after Juli's write, and Juli does not
   overwrite that (S-FR-8).

Otherwise it inserts the revert ``workflow_runs`` row (status ``queued``,
``reverts_run_id`` set, the plan in its state) and marks an open day-7
question for the run as answered. No commit: the route commits, then enqueues
``run_agent_workflow`` exactly as approving a card does.

The same live-value check runs again inside the revert run, immediately before
the write (``ProductToolExecutor``'s ``revert_expected``), so a change made
while the seller is deciding is caught too.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Product
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.models.run_changes import (
    QUESTION_OPEN,
    QUESTION_REVERTED,
    RunRevertQuestion,
    RunWriteValue,
)
from juli_backend.services.agent.runner.write_capture import (
    LISTING_OPERATION,
    changed_fields,
    field_values,
)
from juli_backend.services.agent.status import (
    NON_TERMINAL_STATUSES,
    SUSPENDED_STATUSES,
)
from juli_backend.services.run_changes.planner import (
    FIELD_LABELS_VI,
    RESTORABLE_FIELDS,
    STATE_KEY,
    RevertPlan,
)

logger = logging.getLogger(__name__)

#: Statuses in which a run still holds its subject (queued, running, waiting).
ACTIVE_STATUSES: frozenset[str] = frozenset(
    str(status) for status in (*NON_TERMINAL_STATUSES, *SUSPENDED_STATUSES)
)

#: Reads the live product from TikTok: ``(session, shop_id, tiktok_product_id)``.
LiveProductReader = Callable[[AsyncSession, uuid.UUID, str], Awaitable[Mapping[str, Any]]]

REFUSED_IS_REVERT = "is_revert"
REFUSED_NOT_FINISHED = "not_finished"
REFUSED_NOTHING_WRITTEN = "nothing_written"
REFUSED_PRICE = "price_not_reverted"
REFUSED_IN_PROGRESS = "revert_in_progress"
REFUSED_ALREADY_REVERTED = "already_reverted"
REFUSED_EXTERNAL_CHANGE = "external_change"
REFUSED_LIVE_READ_FAILED = "live_read_failed"

_MESSAGES_VI: Mapping[str, str] = {
    REFUSED_IS_REVERT: (
        "Đây là một lần hoàn tác. Juli không hoàn tác một lần hoàn tác; nếu cần, "
        "hãy duyệt lại đề xuất ban đầu."
    ),
    REFUSED_NOT_FINISHED: "Lượt chạy này chưa kết thúc. Chỉ hoàn tác được lượt chạy đã xong.",
    REFUSED_NOTHING_WRITTEN: (
        "Lượt chạy này chưa ghi thay đổi nào lên TikTok Shop, nên không có gì để hoàn tác."
    ),
    REFUSED_PRICE: "Juli không tự hoàn tác giá. Bạn khôi phục giá trên Seller Center.",
    REFUSED_IN_PROGRESS: "Một lần hoàn tác cho lượt chạy này đang chạy.",
    REFUSED_ALREADY_REVERTED: "Lượt chạy này đã được hoàn tác.",
    REFUSED_LIVE_READ_FAILED: (
        "Juli không đọc được sản phẩm từ TikTok Shop lúc này nên chưa hoàn tác. "
        "Bạn thử lại sau ít phút."
    ),
}


class RevertRunNotFound(LookupError):
    """No such run for this shop (another shop's run reads the same)."""


class RevertRefused(Exception):
    """The run cannot be reverted; ``message_vi`` says why, for the seller."""

    def __init__(self, code: str, message_vi: str, *, fields: tuple[str, ...] = ()) -> None:
        super().__init__(f"{code}: {message_vi}")
        self.code = code
        self.message_vi = message_vi
        self.fields = fields


def refusal_message(code: str) -> str | None:
    """The seller-facing Vietnamese reason for a refusal code (no live read needed)."""
    return _MESSAGES_VI.get(code)


def _refuse(code: str) -> RevertRefused:
    return RevertRefused(code, _MESSAGES_VI[code])


def external_change_message(fields: tuple[str, ...]) -> str:
    labels = ", ".join(FIELD_LABELS_VI.get(name, name) for name in fields)
    return (
        f"{labels[:1].upper()}{labels[1:]} của sản phẩm đã được thay đổi bên ngoài Juli sau "
        "lần ghi của Juli. Juli không ghi đè thay đổi đó, nên không hoàn tác."
    )


@dataclass(frozen=True)
class FieldChange:
    """One field a run changed, merged over every write of the run."""

    field: str
    before: Any
    after: Any
    after_source: str
    tool_name: str
    recorded_at: datetime | None


@dataclass(frozen=True)
class RevertStarted:
    run_id: uuid.UUID
    reverts_run_id: uuid.UUID
    product_id: uuid.UUID | None
    status: str
    fields: tuple[str, ...]


async def get_owned_run(
    session: AsyncSession, shop_id: uuid.UUID, run_id: uuid.UUID
) -> WorkflowRunRow:
    run = await session.get(WorkflowRunRow, run_id)
    if run is None or run.shop_id != shop_id:
        raise RevertRunNotFound(f"run {run_id} not found for shop {shop_id}")
    return run


async def load_run_changes(
    session: AsyncSession, shop_id: uuid.UUID, run_id: uuid.UUID
) -> list[FieldChange]:
    """Per field: the earliest before-value and the latest after-value of the run."""
    rows = (
        (
            await session.execute(
                select(RunWriteValue)
                .where(RunWriteValue.shop_id == shop_id, RunWriteValue.workflow_run_id == run_id)
                .order_by(RunWriteValue.recorded_at.asc(), RunWriteValue.id.asc())
            )
        )
        .scalars()
        .all()
    )
    merged: dict[str, FieldChange] = {}
    for row in rows:
        first = merged.get(row.field)
        merged[row.field] = FieldChange(
            field=row.field,
            before=first.before if first is not None else row.before_value,
            after=row.after_value,
            after_source=row.after_source,
            tool_name=row.tool_name,
            recorded_at=row.recorded_at,
        )
    return list(merged.values())


async def revert_runs_of(
    session: AsyncSession, shop_id: uuid.UUID, run_id: uuid.UUID
) -> list[WorkflowRunRow]:
    result = await session.execute(
        select(WorkflowRunRow)
        .where(WorkflowRunRow.shop_id == shop_id, WorkflowRunRow.reverts_run_id == run_id)
        .order_by(WorkflowRunRow.created_at.desc())
    )
    return list(result.scalars().all())


async def _revert_restored_something(
    session: AsyncSession, shop_id: uuid.UUID, revert_run_id: uuid.UUID
) -> bool:
    found = await session.execute(
        select(RunWriteValue.id)
        .where(RunWriteValue.shop_id == shop_id, RunWriteValue.workflow_run_id == revert_run_id)
        .limit(1)
    )
    return found.scalar_one_or_none() is not None


async def revert_block_reason(
    session: AsyncSession, run: WorkflowRunRow, changes: list[FieldChange]
) -> str | None:
    """Why ``run`` cannot be reverted, before any live read; ``None`` if it can."""
    if run.reverts_run_id is not None:
        return REFUSED_IS_REVERT
    if run.status in ACTIVE_STATUSES:
        return REFUSED_NOT_FINISHED
    if not changes:
        return REFUSED_NOTHING_WRITTEN
    if any(change.field not in RESTORABLE_FIELDS for change in changes):
        return REFUSED_PRICE
    for revert in await revert_runs_of(session, run.shop_id, run.id):
        if revert.status in ACTIVE_STATUSES:
            return REFUSED_IN_PROGRESS
        if await _revert_restored_something(session, run.shop_id, revert.id):
            return REFUSED_ALREADY_REVERTED
    return None


def build_plan(
    run: WorkflowRunRow, changes: list[FieldChange], *, started_by_user_id: uuid.UUID | None
) -> RevertPlan:
    return RevertPlan(
        reverts_run_id=str(run.id),
        restore={change.field: change.before for change in changes},
        expected={change.field: change.after for change in changes},
        started_by_user_id=str(started_by_user_id) if started_by_user_id else None,
    )


def _initial_state(run: WorkflowRunRow, plan: RevertPlan) -> dict[str, Any]:
    from juli_backend.services.agent import run_context as run_context_module

    labels = ", ".join(FIELD_LABELS_VI.get(name, name) for name in plan.fields)
    opening = run_context_module.build_opening_context_message(
        workflow_key=run.workflow_key,
        rationale=f"Hoàn tác lượt chạy trước: khôi phục {labels} về nội dung trước khi Juli sửa.",
    )
    state = run_context_module.initial_run_state(opening)
    state[STATE_KEY] = plan.to_state()
    return state


def _prompt_pin(workflow_key: str) -> tuple[str, str]:
    from juli_backend.services.agent import prompts as prompts_module

    version = prompts_module.production_version(workflow_key)
    return (
        prompts_module.prompt_version(workflow_key, version),
        prompts_module.prompt_sha256(workflow_key, version),
    )


async def start_revert(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    run_id: uuid.UUID,
    started_by_user_id: uuid.UUID | None,
    read_live_product: LiveProductReader,
    now: datetime | None = None,
) -> RevertStarted:
    """Insert the revert run for ``run_id`` (see module docstring). No commit."""
    run = await get_owned_run(session, shop_id, run_id)
    changes = await load_run_changes(session, shop_id, run.id)
    reason = await revert_block_reason(session, run, changes)
    if reason is not None:
        raise _refuse(reason)

    product = await session.get(Product, run.product_id) if run.product_id else None
    if product is None or product.shop_id != shop_id:
        raise _refuse(REFUSED_NOTHING_WRITTEN)

    plan = build_plan(run, changes, started_by_user_id=started_by_user_id)
    try:
        live = await read_live_product(session, shop_id, product.tiktok_product_id)
    except Exception:
        logger.warning(
            "run_revert_live_read_failed",
            extra={"shop_id": str(shop_id), "run_id": str(run.id)},
            exc_info=True,
        )
        raise _refuse(REFUSED_LIVE_READ_FAILED) from None
    changed = tuple(
        changed_fields(
            LISTING_OPERATION, live=field_values(LISTING_OPERATION, live), expected=plan.expected
        )
    )
    if changed:
        logger.info(
            "run_revert_refused_external_change",
            extra={"shop_id": str(shop_id), "run_id": str(run.id), "fields": list(changed)},
        )
        raise RevertRefused(
            REFUSED_EXTERNAL_CHANGE, external_change_message(changed), fields=changed
        )

    prompt_version, prompt_sha256 = _prompt_pin(run.workflow_key)
    revert = WorkflowRunRow(
        shop_id=shop_id,
        product_id=run.product_id,
        action_card_id=run.action_card_id,
        workflow_key=run.workflow_key,
        subject_type=run.subject_type,
        subject_ref=run.subject_ref,
        state=_initial_state(run, plan),
        status="queued",
        prompt_version=prompt_version,
        prompt_sha256=prompt_sha256,
        reverts_run_id=run.id,
    )
    session.add(revert)
    await session.flush()

    question = (
        await session.execute(
            select(RunRevertQuestion).where(
                RunRevertQuestion.shop_id == shop_id,
                RunRevertQuestion.workflow_run_id == run.id,
                RunRevertQuestion.status == QUESTION_OPEN,
            )
        )
    ).scalar_one_or_none()
    if question is not None:
        question.status = QUESTION_REVERTED
        question.revert_run_id = revert.id
        question.resolved_at = (now or datetime.now(UTC)).replace(tzinfo=None)
        await session.flush()

    return RevertStarted(
        run_id=revert.id,
        reverts_run_id=run.id,
        product_id=run.product_id,
        status=revert.status,
        fields=plan.fields,
    )
