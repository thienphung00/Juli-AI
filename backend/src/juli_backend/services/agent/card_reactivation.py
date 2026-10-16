"""Put an ended run's approved action card back on the seller's desk.

Issue #1305 / AGT-W5A first did this for a run that ends ``failed`` (the clean
runner path and the worker crash handler): the card the seller approved goes
from ``approved`` back to ``active`` with ``approved_at`` cleared, so they can
approve it again. Fast track D47.5 (owner, 2026-10-16) widens it to the two
other unsuccessful terminal statuses, ``cancelled`` and ``timed_out``: a card
must never stay on "Đang thực hiện" behind a run that is over.

:func:`reactivate_card_for_ended_run` is the ONE place that transition is
written. Its callers are every terminal writer of a run row:

- ``runner.conversation_store.JsonbConversationStore.persist`` -- the runner's
  own exits (LLM / tool errors, the seller's or Ops' ``cancel_requested``
  checkpoint, the wall clock, the iteration cap);
- ``workers.tasks.agent_workflow``'s crash handler (``failed``);
- ``workers.tasks.reaper``'s sink -- ``worker_lost`` (``failed``), an expired
  consent (``confirmation_expired`` -> ``cancelled``) and an expired external
  wait (``external_wait_expired`` -> ``timed_out``).

A seller DECLINE is not this path: "Từ chối", "Không thực hiện" (at the
consent step or while a lever flow waits for the seller) and "Hoàn tác" go
through ``decision_reasons.close_card`` -> ``dismissed`` with the 7-day
cooldown, in the same transaction as the decline. A dismissed card is not
``approved``, so nothing here can bring it back.

Guarantees:

- **Idempotent.** Only an ``approved`` card moves; a second call, or a card a
  decline already dismissed, is a no-op returning ``False``.
- **Tenant-scoped.** The card is read through the caller's (RLS-scoped)
  session and must belong to the run's own shop; a mismatch is logged and
  left alone.
- **Expiry untouched.** ``surfaced_at`` is kept, so a card first surfaced more
  than 7 days ago is ``expired`` on the next read (``card_view._status``) and
  the next emission-budget pass (``emission_budget.apply_emission_budget``),
  exactly like any other active card -- it does not linger. A reactivated card
  counts as open again; it did not while ``approved``.

Flush / commit belong to the caller.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from juli_backend.services.agent.status import WorkflowRunStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from juli_backend.models.models import WorkflowRun

logger = logging.getLogger(__name__)

#: Terminal statuses that hand the card back (D47.5). ``completed`` never does:
#: the change was applied, or the seller declined it (``confirmation_declined``).
REACTIVATING_RUN_STATUSES: frozenset[WorkflowRunStatus] = frozenset(
    {WorkflowRunStatus.FAILED, WorkflowRunStatus.CANCELLED, WorkflowRunStatus.TIMED_OUT}
)

_APPROVED = "approved"
_ACTIVE = "active"


async def reactivate_card_for_ended_run(
    session: AsyncSession,
    run: WorkflowRun,
    status: WorkflowRunStatus | str,
) -> bool:
    """``approved`` -> ``active`` (``approved_at`` cleared) for *run*'s card.

    *status* is the terminal status the run is being moved to. Returns whether
    the card was changed.
    """
    try:
        status = WorkflowRunStatus(status)
    except ValueError:
        return False
    if status not in REACTIVATING_RUN_STATUSES or not run.action_card_id:
        return False

    from juli_backend.models.models import ActionCard

    card = await session.get(ActionCard, run.action_card_id)
    if card is None or card.status != _APPROVED:
        return False
    if card.shop_id != run.shop_id:
        logger.warning(
            "action_card_reactivation_shop_mismatch",
            extra={
                "run_id": str(run.id),
                "run_shop_id": str(run.shop_id),
                "action_card_id": str(card.id),
            },
        )
        return False
    card.status = _ACTIVE
    card.approved_at = None
    logger.info(
        "action_card_reactivated_after_run",
        extra={
            "shop_id": str(run.shop_id),
            "run_id": str(run.id),
            "action_card_id": str(card.id),
            "run_status": status.value,
            "stop_reason": run.stop_reason,
        },
    )
    return True


__all__ = ["REACTIVATING_RUN_STATUSES", "reactivate_card_for_ended_run"]
