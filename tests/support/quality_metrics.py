"""Seeding harness for the three unconflated quality metrics (issue #1656,
W8-D / P10-4, parent PRD #1652).

The point of #1656's assertions is that three metrics read three *different*
sources, so the harness seeds each source independently and never through a
helper that writes two of them at once — a seeder that stamps a card and a
run together would make the isolation assertion vacuous.

Everything here drives the REAL ORM models, and the one helper that needs a
``tool_executions`` row (:func:`seed_recommendation_with_observed_outcome`)
gets it from the REAL ``WorkflowRunner`` + ``ToolExecutionLedger`` by
delegating to ``tests.support.outcome_chain``: ``impact_readings``' FK to
``tool_executions`` is NOT NULL, so an observed outcome cannot exist without
a real write behind it.

Column time zones on these two tables are genuinely mixed, and getting one
wrong is an asyncpg flush error rather than a wrong number, so the seeders
below take aware datetimes and normalise per column:

- ``action_cards.surfaced_at`` / ``dismissed_at`` are ``TIMESTAMPTZ`` (aware)
- ``action_cards.approved_at`` / ``executed_at`` are naive
  (``services/agent/approval.py`` says so at its own write site)
- ``workflow_runs.created_at`` is naive
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import update

from juli_backend.models.models import ActionCard, ImpactReading, WorkflowRun
from juli_backend.services.agent.runner.state import RunState
from tests.support.outcome_chain import (
    execution_id_for,
    run_a_real_write,
    seed_reading,
    stamped_prompt_pin,
)
from tests.support.outcome_chain import seed_run as seed_running_run

__all__ = [
    "aware",
    "naive",
    "seed_card",
    "seed_recommendation_with_observed_outcome",
    "seed_run",
    "set_run_outcome",
]


def aware(value: datetime) -> datetime:
    """UTC-aware, for the ``TIMESTAMPTZ`` columns."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def naive(value: datetime) -> datetime:
    """Naive UTC, for the ``TIMESTAMP WITHOUT TIME ZONE`` columns asyncpg
    refuses aware values on (#1138)."""
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


async def seed_card(
    factory,
    shop_id: uuid.UUID,
    *,
    status: str = "active",
    surfaced_at: datetime | None = None,
    approved_at: datetime | None = None,
    dismissed_at: datetime | None = None,
    suppressed_reason: str | None = None,
) -> uuid.UUID:
    """One ``action_cards`` row, exactly as the emission budget and the
    approval path leave it. ``surfaced_at=None`` is a card that was scored
    but never surfaced — outside "cards surfaced" by construction."""
    async with factory() as session:
        card = ActionCard(
            id=uuid.uuid4(),
            shop_id=shop_id,
            workflow_key=f"optimize_product_2_{uuid.uuid4().hex[:8]}",
            priority=1,
            severity="high",
            title="Giảm giá sản phẩm",
            description="Điều chỉnh giá để cạnh tranh hơn.",
            recommendation_payload=json.dumps({"kind": "price"}),
            status=status,
            surfaced_at=aware(surfaced_at) if surfaced_at else None,
            approved_at=naive(approved_at) if approved_at else None,
            dismissed_at=aware(dismissed_at) if dismissed_at else None,
            suppressed_reason=suppressed_reason,
        )
        session.add(card)
        await session.commit()
        return card.id


async def seed_run(
    factory,
    shop_id: uuid.UUID,
    product_id: uuid.UUID,
    *,
    action_card_id: uuid.UUID | None = None,
    status: str = "completed",
    stop_reason: str | None = None,
    required_steps_completed: bool | None = None,
    created_at: datetime | None = None,
) -> uuid.UUID:
    """One ``workflow_runs`` row. Defaults to a TERMINAL status because the
    partial unique index only allows one live run per ``(shop_id,
    product_id)`` (ADR-073), and these suites seed many runs on one product.
    """
    async with factory() as session:
        prompt_version, prompt_sha256 = stamped_prompt_pin()
        run = WorkflowRun(
            id=uuid.uuid4(),
            shop_id=shop_id,
            product_id=product_id,
            state=RunState().to_dict(),
            status=status,
            stop_reason=stop_reason,
            required_steps_completed=required_steps_completed,
            prompt_version=prompt_version,
            prompt_sha256=prompt_sha256,
            action_card_id=action_card_id,
        )
        session.add(run)
        await session.flush()
        if created_at is not None:
            await session.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == run.id)
                .values(created_at=naive(created_at))
            )
        await session.commit()
        return run.id


async def set_run_outcome(
    factory,
    run_id: uuid.UUID,
    *,
    stop_reason: str | None,
    required_steps_completed: bool | None,
) -> None:
    """Mutate ONLY the execution-quality source's two columns on one run."""
    async with factory() as session:
        await session.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run_id)
            .values(
                stop_reason=stop_reason,
                required_steps_completed=required_steps_completed,
            )
        )
        await session.commit()


async def seed_recommendation_with_observed_outcome(
    factory,
    sync_session,
    *,
    shop_id: uuid.UUID,
    product_id: uuid.UUID,
    tiktok_product_id: str,
    pre: Decimal,
    post: Decimal,
    confidence: str = "cao",
    metric: str = "gmv",
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A card, a run linked to it, a REAL write through the real runner and
    ledger, and one ``impact_readings`` row carrying the post-window value.

    Returns ``(card_id, run_id, execution_id)``. The write is real because
    ``impact_readings.tool_execution_id`` is NOT NULL: an observed outcome
    with no execution behind it is not a row Postgres will accept, and
    hand-building the ledger row would prove the SQL instead of the wiring.
    """
    card_id = await seed_card(
        factory,
        shop_id,
        status="approved",
        surfaced_at=datetime.now(UTC),
        approved_at=datetime.now(UTC),
    )
    run_id = await seed_running_run(factory, shop_id, product_id, action_card_id=card_id)
    await run_a_real_write(
        factory,
        sync_session,
        run_id=run_id,
        shop_id=shop_id,
        tiktok_product_id=tiktok_product_id,
    )
    execution_id = await execution_id_for(factory, run_id)
    await seed_reading(
        factory,
        run_id=run_id,
        execution_id=execution_id,
        metric=metric,
        confidence=confidence,
        post=post,
    )
    async with factory() as session:
        await session.execute(
            update(ImpactReading).where(ImpactReading.run_id == run_id).values(pre=pre)
        )
        await session.commit()
    return card_id, run_id, execution_id
