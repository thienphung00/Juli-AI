"""Wiring a lever-flow run into the worker, and driving its waits (fast track P10-B).

``wiring_for_run`` gives the worker's ``_construct_runner`` what differs for a
cover-image or promotion run: the playbook, the deterministic planner, and --
for the cover image -- the seller's photo bytes, the TikTok URI already staged
from them, and the recorder that keeps a newly staged URI.

``LeverFlowRunner`` wraps the ``WorkflowRunner`` the worker built. It forwards
``run`` / ``resume`` and adds ``resume_after_external_wait``; when the planner
raises ``AwaitSeller`` it records what the planner computed and suspends the run
through ``WorkflowRunner.enter_external_wait`` (``waiting_external`` + one
``workflow.status`` narration). The task shells in ``workers/tasks`` stay
branch-free: they call ``runner.run(...)`` exactly as before.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from juli_backend.models.lever_flows import (
    FLOW_PHOTO,
    FLOW_PROMOTION,
    PHOTO_AFTER,
    PHOTO_BEFORE,
    RunLeverFlow,
)
from juli_backend.models.models import Product
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.agent.playbooks.base import Playbook
from juli_backend.services.lever_flows import photos as photos_module
from juli_backend.services.lever_flows import promotion as promotion_module
from juli_backend.services.lever_flows.flows import (
    MAX_SCHEDULED_ROUNDS,
    AwaitSeller,
    awaiting_of,
    get_flow,
    touch,
)
from juli_backend.services.lever_flows.planner import (
    PHOTO_PLAYBOOK,
    PROMOTION_PLAYBOOK,
    PhotoPlanner,
    PromotionPlanner,
)

logger = logging.getLogger(__name__)

#: (run_id) -> enqueue a delayed re-check of a promotion not found yet.
RecheckScheduler = Callable[[uuid.UUID], None]


@dataclass
class FlowWiring:
    flow: RunLeverFlow
    playbook: Playbook
    planner: PhotoPlanner | PromotionPlanner
    pending_image_bytes: bytes | None = None
    staged_image_uri: str | None = None
    on_image_staged: Callable[[str], None] | None = None


async def wiring_for_run(
    session: AsyncSession,
    sync_session: Session,
    run: WorkflowRunRow,
    product: Product,
    *,
    product_detail: Callable[[], Mapping[str, Any] | None],
) -> FlowWiring | None:
    """The flow pieces for ``run``, or ``None`` for an ordinary run.

    Raises ``PromotionRulesMissing`` for a promotion run of a product with no
    cost: the card should never have been produced, and the run fails loudly
    (the worker's crash path) rather than proposing a discount blind.
    """
    flow = await get_flow(session, run.shop_id, run.id)
    if flow is None:
        return None
    if flow.kind == FLOW_PHOTO:
        after = await photos_module.get_photo(session, run.shop_id, run.id, PHOTO_AFTER)
        return FlowWiring(
            flow=flow,
            playbook=PHOTO_PLAYBOOK,
            planner=PhotoPlanner(photo_ready=after is not None),
            pending_image_bytes=after.data if after is not None else None,
            staged_image_uri=after.tiktok_uri if after is not None else None,
            on_image_staged=photos_module.SqlStagedUriRecorder(
                sync_session, shop_id=run.shop_id, workflow_run_id=run.id
            ),
        )
    if flow.kind == FLOW_PROMOTION:
        try:
            rules = await promotion_module.load_rules(
                session, run.shop_id, product.tiktok_product_id
            )
        except promotion_module.PromotionRulesMissing:
            logger.error(
                "promotion_run_without_cost",
                extra={"shop_id": str(run.shop_id), "run_id": str(run.id), "lever": flow.lever},
            )
            raise
        return FlowWiring(
            flow=flow,
            playbook=PROMOTION_PLAYBOOK,
            planner=PromotionPlanner(
                lever=flow.lever,
                rules=rules,
                product_detail=product_detail,
                verify_round=flow.verify_attempts,
            ),
        )
    return None


def _shop_today() -> date:
    return (datetime.now(UTC) + timedelta(hours=7)).date()


class LeverFlowRunner:
    """A ``WorkflowRunner`` for a lever-flow run (see module docstring)."""

    def __init__(
        self,
        runner: Any,
        *,
        session: AsyncSession,
        wiring: FlowWiring,
        product_detail: Callable[[], Mapping[str, Any] | None],
        fetch_image: photos_module.ImageFetcher = photos_module.fetch_image,
        schedule_recheck: RecheckScheduler | None = None,
    ) -> None:
        self._runner = runner
        self._session = session
        self._wiring = wiring
        self._product_detail = product_detail
        self._fetch_image = fetch_image
        self._schedule_recheck = schedule_recheck

    @property
    def flow(self) -> RunLeverFlow:
        return self._wiring.flow

    async def run(self, workflow_run_id: uuid.UUID, *, product_ref: str) -> Any:
        return await self._drive(
            workflow_run_id, self._runner.run(workflow_run_id, product_ref=product_ref)
        )

    async def resume(self, workflow_run_id: uuid.UUID, *, approved: bool) -> Any:
        return await self._drive(
            workflow_run_id, self._runner.resume(workflow_run_id, approved=approved)
        )

    async def resume_after_external_wait(self, workflow_run_id: uuid.UUID) -> Any:
        """Continue after the photo arrived / "Tôi đã áp dụng". A no-op when the run
        is no longer waiting (a duplicate or late re-check)."""
        from juli_backend.services.agent.runner import NoExternalWaitError

        run = await self._session.get(WorkflowRunRow, workflow_run_id)
        if run is None or awaiting_of(run) is None:
            logger.info(
                "lever_flow_resume_skipped_not_waiting",
                extra={"run_id": str(workflow_run_id)},
            )
            return None
        planner = self._wiring.planner
        if isinstance(planner, PromotionPlanner):
            self.flow.verify_attempts += 1
            planner.verify_round = self.flow.verify_attempts
            touch(self.flow)
            await self._session.flush()
        try:
            return await self._drive(
                workflow_run_id, self._runner.resume_after_external_wait(workflow_run_id)
            )
        except NoExternalWaitError:
            logger.info(
                "lever_flow_resume_raced",
                extra={"run_id": str(workflow_run_id)},
            )
            return None

    async def _drive(self, workflow_run_id: uuid.UUID, leg: Any) -> Any:
        try:
            result = await leg
        except AwaitSeller as signal:
            await self._on_wait(workflow_run_id, signal)
            return await self._runner.enter_external_wait(
                workflow_run_id, reason=signal.awaiting, narration=signal.narration
            )
        await self._on_result()
        return result

    async def _on_wait(self, workflow_run_id: uuid.UUID, signal: AwaitSeller) -> None:
        flow = self.flow
        if flow.kind == FLOW_PHOTO:
            await self._snapshot_before(workflow_run_id)
        if signal.proposal is not None:
            flow.proposal = dict(signal.proposal)
        if (
            signal.not_found
            and self._schedule_recheck is not None
            and flow.verify_attempts < MAX_SCHEDULED_ROUNDS
        ):
            self._schedule_recheck(workflow_run_id)
        touch(flow)
        await self._session.flush()

    async def _snapshot_before(self, workflow_run_id: uuid.UUID) -> None:
        """Keep the current cover once, so consent shows "before" from our storage."""
        shop_id = self.flow.shop_id
        if await photos_module.get_photo(self._session, shop_id, workflow_run_id, PHOTO_BEFORE):
            return
        snapshot = await asyncio.to_thread(
            photos_module.snapshot_cover, self._product_detail(), self._fetch_image
        )
        if snapshot is None:
            logger.info("lever_photo_before_unavailable", extra={"run_id": str(workflow_run_id)})
            return
        await photos_module.save_photo(
            self._session,
            shop_id=shop_id,
            run_id=workflow_run_id,
            role=PHOTO_BEFORE,
            data=snapshot.data,
            report=snapshot.report,
        )

    async def _on_result(self) -> None:
        planner = self._wiring.planner
        if not isinstance(planner, PromotionPlanner) or planner.found is None:
            return
        found = dict(planner.found)
        begin = found.get("begin_date")
        start = date.fromisoformat(begin) if isinstance(begin, str) else _shop_today()
        self.flow.found = found
        self.flow.measurement_start = start
        touch(self.flow)
        await self._session.flush()
        logger.info(
            "lever_flow_promotion_verified",
            extra={"run_id": str(self.flow.workflow_run_id), "start": start.isoformat()},
        )


__all__ = ["FlowWiring", "LeverFlowRunner", "RecheckScheduler", "wiring_for_run"]
