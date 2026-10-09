"""Which runs are lever flows, what they wait for, and the flow row (fast track P10-B).

A **lever flow** is a run of a card whose change Juli cannot simply write after
one consent (contract §4-§5, ADR-109 Amendment 1 d.3):

- ``cover_image`` -> ``photo``: Juli never picks or generates an image; the run
  waits for the seller's photo (``awaiting = "photo"``), checks it, then takes
  the ordinary consent and writes it.
- ``product_discount`` / ``flash_sale`` / ``shipping_discount`` /
  ``buy_more_save_more`` -> ``promotion``: the seller applies the promotion on
  Seller Center (``awaiting = "seller_action"``); Juli only verifies it, read-only
  (D13), and the measurement clock starts at the promotion's start date.

Both waits are the runner's existing ``waiting_external`` state
(``workflow_runs.external_wait_reason`` = the ``awaiting`` value), so the
reaper ends an unanswered wait with ``external_wait_expired`` -> ``timed_out``
under the flow's own ``external_wait_timeout_h``.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.lever_flows import FLOW_PHOTO, FLOW_PROMOTION, RunLeverFlow
from juli_backend.models.models import WorkflowRun as WorkflowRunRow

PHOTO_LEVERS: frozenset[str] = frozenset({"cover_image"})
PROMOTION_LEVERS: tuple[str, ...] = (
    "product_discount",
    "flash_sale",
    "shipping_discount",
    "buy_more_save_more",
)

AWAITING_PHOTO = "photo"
AWAITING_SELLER_ACTION = "seller_action"
AWAITING_VALUES: frozenset[str] = frozenset({AWAITING_PHOTO, AWAITING_SELLER_ACTION})

#: ``workflow.status`` narrations (VI) for the two waits and the failed check.
NARRATION_AWAITING_PHOTO = "Đang chờ ảnh từ bạn"
NARRATION_AWAITING_SELLER = "Đang chờ bạn áp dụng trên Seller Center"
NARRATION_NOT_FOUND = "Chưa tìm thấy trên TikTok"

#: The photo request expires after 3 days (contract §4).
PHOTO_WAIT_HOURS = 72
#: A promotion not applied (or not found) within 14 days ends the run.
PROMOTION_WAIT_HOURS = 14 * 24

WAITING_EXTERNAL_STATUS = "waiting_external"

#: "Tôi đã áp dụng" checks per promotion run (clicks and scheduled re-checks).
MAX_VERIFY_ROUNDS = 12
#: Scheduled re-checks after a "not found": every 30 minutes, up to 4 rounds.
RECHECK_DELAY_S = 30 * 60
MAX_SCHEDULED_ROUNDS = 4


def flow_kind_for_lever(lever_code: str | None) -> str | None:
    """``photo`` / ``promotion`` for a lever that needs a flow, else ``None``."""
    if lever_code in PHOTO_LEVERS:
        return FLOW_PHOTO
    if lever_code in PROMOTION_LEVERS:
        return FLOW_PROMOTION
    return None


def is_promotion_lever(lever_code: str | None) -> bool:
    return lever_code in PROMOTION_LEVERS


def awaiting_of(run: WorkflowRunRow) -> str | None:
    """What the seller must do for this run to continue, or ``None``.

    Only while the run is actually waiting: the column keeps its last value
    after a resume, the status does not.
    """
    if run.status != WAITING_EXTERNAL_STATUS:
        return None
    reason = run.external_wait_reason
    return reason if reason in AWAITING_VALUES else None


def wait_timeout_hours(awaiting: str | None) -> int | None:
    if awaiting == AWAITING_PHOTO:
        return PHOTO_WAIT_HOURS
    if awaiting == AWAITING_SELLER_ACTION:
        return PROMOTION_WAIT_HOURS
    return None


@dataclass
class AwaitSeller(Exception):
    """Raised by a flow planner when the run must wait for the seller.

    The runner never catches it; ``LeverFlowRunner`` does, records what the
    planner computed (``proposal``) and suspends the run with
    ``WorkflowRunner.enter_external_wait`` (``awaiting`` + ``narration``). A
    control-flow signal rather than a new runner block type, so the runner's
    loop, events and persistence stay exactly as they are.
    """

    awaiting: str
    narration: str
    proposal: Mapping[str, Any] | None = None
    #: A verification that did not find the promotion (schedule a re-check).
    not_found: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(f"await seller: {self.awaiting}")


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def register_flow(
    session: AsyncSession, *, shop_id: uuid.UUID, run_id: uuid.UUID, lever_code: str | None
) -> RunLeverFlow | None:
    """Insert the flow row for a run whose lever needs one. Flush, no commit."""
    kind = flow_kind_for_lever(lever_code)
    if kind is None or lever_code is None:
        return None
    flow = RunLeverFlow(shop_id=shop_id, workflow_run_id=run_id, kind=kind, lever=lever_code)
    session.add(flow)
    await session.flush()
    return flow


async def get_flow(
    session: AsyncSession, shop_id: uuid.UUID, run_id: uuid.UUID
) -> RunLeverFlow | None:
    result = await session.execute(
        select(RunLeverFlow).where(
            RunLeverFlow.shop_id == shop_id, RunLeverFlow.workflow_run_id == run_id
        )
    )
    return result.scalar_one_or_none()


async def flows_for_runs(
    session: AsyncSession, shop_id: uuid.UUID, run_ids: list[uuid.UUID]
) -> dict[uuid.UUID, RunLeverFlow]:
    if not run_ids:
        return {}
    result = await session.execute(
        select(RunLeverFlow).where(
            RunLeverFlow.shop_id == shop_id, RunLeverFlow.workflow_run_id.in_(run_ids)
        )
    )
    return {flow.workflow_run_id: flow for flow in result.scalars().all()}


def touch(flow: RunLeverFlow) -> None:
    flow.updated_at = _now()


__all__ = [
    "AWAITING_PHOTO",
    "AWAITING_SELLER_ACTION",
    "AWAITING_VALUES",
    "MAX_SCHEDULED_ROUNDS",
    "MAX_VERIFY_ROUNDS",
    "NARRATION_AWAITING_PHOTO",
    "NARRATION_AWAITING_SELLER",
    "NARRATION_NOT_FOUND",
    "PHOTO_LEVERS",
    "PHOTO_WAIT_HOURS",
    "PROMOTION_LEVERS",
    "PROMOTION_WAIT_HOURS",
    "RECHECK_DELAY_S",
    "AwaitSeller",
    "awaiting_of",
    "flow_kind_for_lever",
    "flows_for_runs",
    "get_flow",
    "is_promotion_lever",
    "register_flow",
    "touch",
    "wait_timeout_hours",
]
