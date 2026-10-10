"""Wiring a content run into the worker, and driving its waits (P14-E).

``wiring_for_run`` gives the worker's ``_construct_runner`` what differs for a
content run: the deterministic planner with the run's content state, the
seller's rules and the product facts read from the database, and the drafter.
``ContentRunner`` wraps the ``WorkflowRunner``: it forwards ``run`` /
``resume_after_external_wait``, turns the planner's ``AwaitSeller`` into
``enter_external_wait``, and writes the content state back to
``workflow_runs.state`` whenever a leg suspends or ends (see ``run_state``).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCard, InventoryItem, Product
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.content_cards import run_state
from juli_backend.services.content_cards.constants import SPEC_BY_WORKFLOW
from juli_backend.services.content_cards.drafter import ContentDrafter
from juli_backend.services.content_cards.emission import payload_of
from juli_backend.services.content_cards.guardrails import ContentRules, DraftFacts
from juli_backend.services.content_cards.planner import ContentPlanner, DraftGate
from juli_backend.services.lever_flows.flows import AwaitSeller, awaiting_of

logger = logging.getLogger(__name__)

#: Other products the LIVE basket may list after the product itself.
MAX_BASKET_OTHERS = 5


@dataclass
class ContentWiring:
    planner: ContentPlanner


async def load_rules(
    session: AsyncSession, shop_id: uuid.UUID, *, discount_cap_pct: float | None
) -> ContentRules:
    """The seller's rules a content run obeys (D24.21 (5)).

    Exactly the validated ``shop_rules`` keys ``content_tone`` ("Giọng văn") and
    ``banned_terms`` ("Từ không được dùng"), plus the protected terms.
    """
    from juli_backend.services import shop_rules

    return ContentRules(
        tone=await shop_rules.content_tone(session, shop_id),
        banned_terms=tuple(await shop_rules.banned_terms(session, shop_id)),
        protected_terms=tuple(await shop_rules.protected_terms(session, shop_id)),
        discount_cap_pct=discount_cap_pct,
    )


async def _basket_others(session: AsyncSession, shop_id: uuid.UUID, exclude: str) -> list[str]:
    rows = (
        await session.execute(
            select(InventoryItem.seller_sku, InventoryItem.tiktok_product_id)
            .where(
                InventoryItem.shop_id == shop_id,
                InventoryItem.seller_sku.isnot(None),
                InventoryItem.tiktok_product_id != exclude,
            )
            .order_by(InventoryItem.tiktok_product_id.asc())
            .limit(50)
        )
    ).all()
    seen: dict[str, str] = {}
    for sku, product_id in rows:
        if sku and product_id not in seen:
            seen[product_id] = str(sku)
    return list(seen.values())[:MAX_BASKET_OTHERS]


async def wiring_for_run(
    session: AsyncSession,
    run: WorkflowRunRow,
    product: Product,
    *,
    drafter: ContentDrafter | None = None,
) -> ContentWiring | None:
    """The content pieces for ``run``, or ``None`` for any other run."""
    spec = SPEC_BY_WORKFLOW.get(run.workflow_key)
    if spec is None:
        return None
    card = await session.get(ActionCard, run.action_card_id) if run.action_card_id else None
    content = payload_of(card).get("content") if card is not None else None
    content = content if isinstance(content, dict) else {}
    label = str(content.get("product_label") or product.title or product.name or "sản phẩm")
    title = str(product.title or product.name or content.get("product_title") or label)
    state = run_state.state_of(run)
    if state is None:
        target = content.get("target")
        current = content.get("current")
        state = run_state.new_state(
            spec.kind,
            label=label,
            title=title,
            target=float(target) if isinstance(target, int | float) else None,
            current=float(current) if isinstance(current, int | float) else None,
        )
    cap = content.get("discount_cap_pct")
    rules = await load_rules(
        session, run.shop_id, discount_cap_pct=float(cap) if isinstance(cap, int | float) else None
    )
    others = await _basket_others(session, run.shop_id, str(product.tiktok_product_id))
    facts = DraftFacts(
        product_label=label,
        product_title=title,
        basket_skus=(label, *others),
    )
    analyses: list[dict[str, Any]] = []
    try:
        from juli_backend.services.content_analysis.context import load_summaries

        async with session.begin_nested():  # a failed read must not poison the run's session
            analyses = await load_summaries(
                session, run.shop_id, str(product.tiktok_product_id), spec.kind
            )
    except Exception:  # P15 context is optional: never fail a run over it
        logger.warning("content_run_analyses_unavailable", exc_info=True)
    if drafter is None:
        from juli_backend.services.content_cards.drafter import OpenAIContentDrafter

        drafter = OpenAIContentDrafter()
    return ContentWiring(
        planner=ContentPlanner(
            kind=spec.kind,
            state=state,
            drafter=drafter,
            rules=rules,
            facts=facts,
            analyses=analyses,
            draft_gate=await draft_gate_for(session, run.shop_id),
        )
    )


async def draft_gate_for(session: AsyncSession, shop_id: uuid.UUID) -> DraftGate:
    """Juli Ops' model override and monthly-cap verdict for this shop (D25.4, D25.8)."""
    from juli_backend.services.ops import overrides as ops_overrides

    current = await ops_overrides.shop_overrides(session, shop_id)
    cap = await ops_overrides.openai_cap_status(session, shop_id, overrides=current)
    return DraftGate(
        model=current.openai_model,
        cap_reached=cap.reached,
        spent_usd=float(cap.spent_usd),
        cap_usd=float(cap.cap_usd),
    )


class ContentRunner:
    """A ``WorkflowRunner`` for a content run (see module docstring)."""

    def __init__(self, runner: Any, *, session: AsyncSession, wiring: ContentWiring) -> None:
        self._runner = runner
        self._session = session
        self._wiring = wiring

    @property
    def planner(self) -> ContentPlanner:
        return self._wiring.planner

    async def run(self, workflow_run_id: uuid.UUID, *, product_ref: str) -> Any:
        return await self._drive(
            workflow_run_id, self._runner.run(workflow_run_id, product_ref=product_ref)
        )

    async def resume(self, workflow_run_id: uuid.UUID, *, approved: bool) -> Any:
        return await self._drive(
            workflow_run_id, self._runner.resume(workflow_run_id, approved=approved)
        )

    async def resume_after_external_wait(self, workflow_run_id: uuid.UUID) -> Any:
        """Continue after Dùng / Soạn lại / "Tôi đã đăng" / auto-detect. A no-op when
        the run no longer waits (a duplicate or late resume)."""
        from juli_backend.services.agent.runner import NoExternalWaitError

        run = await self._session.get(WorkflowRunRow, workflow_run_id)
        if run is None or awaiting_of(run) is None:
            logger.info(
                "content_run_resume_skipped_not_waiting", extra={"run_id": str(workflow_run_id)}
            )
            return None
        try:
            return await self._drive(
                workflow_run_id, self._runner.resume_after_external_wait(workflow_run_id)
            )
        except NoExternalWaitError:
            logger.info("content_run_resume_raced", extra={"run_id": str(workflow_run_id)})
            return None

    async def _save(self, workflow_run_id: uuid.UUID) -> None:
        run = await self._session.get(WorkflowRunRow, workflow_run_id)
        if run is None:
            return
        run_state.save_state(run, self.planner.state)
        await self._session.flush()

    async def _drive(self, workflow_run_id: uuid.UUID, leg: Any) -> Any:
        try:
            result = await leg
        except AwaitSeller as signal:
            # Written BEFORE the suspension persists: ``enter_external_wait``
            # loads the state blob afresh and keeps this key (unknown fields
            # round-trip), so the drafts and stage survive the wait.
            await self._save(workflow_run_id)
            return await self._runner.enter_external_wait(
                workflow_run_id, reason=signal.awaiting, narration=signal.narration
            )
        # The run ended (measurement starts, or no script passed the checks):
        # the runner has persisted its last state; the content state goes on top.
        await self._save(workflow_run_id)
        return result


__all__ = ["ContentRunner", "ContentWiring", "load_rules", "wiring_for_run"]
