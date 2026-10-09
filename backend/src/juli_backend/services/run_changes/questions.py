"""Read and answer the day-7 "Hoàn tác?" questions (fast track P8-C, ADR-109 d.11/13).

Answering "yes" is starting the revert (``revert.start_revert`` marks the
question ``reverted``); answering "no" is ``dismiss_question``. Both are the
seller's call -- nothing here reverts anything.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.run_changes import QUESTION_DISMISSED, QUESTION_OPEN, RunRevertQuestion


class QuestionNotFound(LookupError):
    """No such open question for this shop."""


async def list_open_questions(session: AsyncSession, shop_id: uuid.UUID) -> list[RunRevertQuestion]:
    result = await session.execute(
        select(RunRevertQuestion)
        .where(RunRevertQuestion.shop_id == shop_id, RunRevertQuestion.status == QUESTION_OPEN)
        .order_by(RunRevertQuestion.created_at.desc())
    )
    return list(result.scalars().all())


async def question_for_run(
    session: AsyncSession, shop_id: uuid.UUID, run_id: uuid.UUID
) -> RunRevertQuestion | None:
    result = await session.execute(
        select(RunRevertQuestion).where(
            RunRevertQuestion.shop_id == shop_id, RunRevertQuestion.workflow_run_id == run_id
        )
    )
    return result.scalar_one_or_none()


async def dismiss_question(
    session: AsyncSession,
    shop_id: uuid.UUID,
    question_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> RunRevertQuestion:
    """The seller keeps the change. Flush, no commit."""
    question = (
        await session.execute(
            select(RunRevertQuestion).where(
                RunRevertQuestion.id == question_id,
                RunRevertQuestion.shop_id == shop_id,
                RunRevertQuestion.status == QUESTION_OPEN,
            )
        )
    ).scalar_one_or_none()
    if question is None:
        raise QuestionNotFound(f"question {question_id} not open for shop {shop_id}")
    question.status = QUESTION_DISMISSED
    question.resolved_at = (now or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None)
    await session.flush()
    return question
