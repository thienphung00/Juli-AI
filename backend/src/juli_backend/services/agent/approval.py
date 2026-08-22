"""Approve-is-run-creation transaction (ADR-075 decision 1, ADR-082, #1222).

`POST /v1/demo/decisions/{action_card_id}/approve` (`api/routes/
demo_execution.py`) is the ONLY way an agent `workflow_runs` row ever comes
into existence. This module owns the single atomic transaction ADR-075
decision 1 specifies:

1. verify the `ActionCard` belongs to the caller's shop **and** is `active`
   (`ActionCardNotFound` for both a cross-tenant card and a nonexistent one
   -- deliberately the SAME exception, so the route cannot turn this into an
   existence oracle; ADR-075: 404, never 403, for both)
2. flip it to `approved`
3. **derive the bound product** (ADR-082 decision 2): among the caller's
   shop's `products`, highest `revenue` first, `tiktok_product_id` ascending
   tiebreak. A shop with zero products raises `NoProductsForShop` --
   ADR-082 decision 4's honest 409, never a run with a NULL `product_id`.
4. INSERT the `workflow_run` (`product_id` **and** `action_card_id`)
5. INSERT the approval audit row (`action_card_approvals`): who, when, a
   VERBATIM snapshot of the card as it read *before* the flip above (the
   state the seller actually saw -- `status` in the snapshot is always
   `"active"`)
6. a `session.flush()` (never `commit()`) surfaces a raced concurrent
   second active run for the derived product as `IntegrityError`
   (`uq_workflow_runs_active_shop_product`, `models.py`), in-transaction --
   this module does not catch that; `api/routes/demo_execution.py` catches
   it (around this call and its own subsequent `commit()` alike) and
   translates it to `409`, reusing the exact shape
   `api/routes/agent_runs.py::create_run` already established (now removed
   from that module -- see its own docstring)
7. enqueueing `run_agent_workflow` happens OUTSIDE this module, in the
   route, strictly AFTER the commit succeeds -- publishing a run id a
   worker could read before the row exists would be worse than a duplicate
   enqueue

**Deliberately not `services/demo_execution/`.** That package is quarantined
by a static AST import-boundary test (`tests/unit/
test_demo_execution_import_boundary.py`) that walks its transitive import
graph and fails if it ever reaches `repositories`, `api`,
`services.execution`, or `integrations.tiktok`. This transaction genuinely
needs the ORM models plus `ActionCardsRepo`/`ProductsRepo`
(`repositories/repos.py`) -- structurally incompatible with that boundary.

**Reached via the existing depth-2 facade idiom.** `api/routes/
demo_execution.py` imports this module as `from juli_backend.services.agent
import approval as approval_module` -- `juli_backend.services.agent` is
exactly `<top>.<direct_child>`, the ceiling `.importlinter.toml`'s
`max_cross_package_depth = 2` allows for a cross-package (`api` -> `services`)
import; `api/routes/agent_runs.py::_resolve_optimize_product_prompt_pin`
(now removed, see that module's docstring) used the identical idiom for
`services.agent.playbooks`/`services.agent.prompts`.

**No commit here.** Every write this module makes -- the `card.status`
flip, the `WorkflowRun` insert, the `ActionCardApproval` insert -- is added
to the caller's own `AsyncSession` without this module ever calling
`session.commit()`. A `session.flush()` at the very end sends all three
writes to Postgres (assigning the client-side `uuid.uuid4()` primary keys
this function returns) and is also where the partial unique index
(`uq_workflow_runs_active_shop_product`) can raise `IntegrityError` for a
raced concurrent second active run -- but nothing is committed yet either
way. The caller commits exactly once, after this function returns, and
rolls back on any exception this module raises (`ActionCardNotFound`/
`ActionCardNotActive`/`NoProductsForShop` before the flush, `IntegrityError`
at or after it). This is what makes the whole thing one transaction:
nothing durable exists until that one commit succeeds, so a crash or a
raised exception anywhere in this function -- so long as the caller then
rolls back -- leaves the card, the run, and the audit row all unwritten
together. Note that SQLAlchemy's default autoflush means the `card.status`
UPDATE is typically sent to Postgres (though still not committed) even
earlier than that, by the time the product-selection SELECT below runs.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.exceptions import NotFound
from juli_backend.models.models import ActionCard, ActionCardApproval
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.repositories.repos import ActionCardsRepo, ProductsRepo

Clock = Callable[[], datetime]


def _default_clock() -> datetime:
    # Naive UTC: ActionCard.approved_at / ActionCardApproval.approved_at
    # are plain DateTime columns (no timezone=True), the same convention
    # every other naive-DateTime column in this codebase follows (e.g.
    # Product.update_time). asyncpg rejects a tz-aware value against a
    # naive column outright (DataError, Postgres-only -- SQLite silently
    # tolerates the mismatch, which is exactly why this needs a comment).
    return datetime.now(UTC).replace(tzinfo=None)


class ActionCardNotFound(Exception):
    """The target `ActionCard` does not exist for the caller's shop --
    covers both "no such id at all" and "belongs to a different shop"
    identically, on purpose (ADR-075: 404 both, never 403 -- no existence
    oracle)."""


class ActionCardNotActive(Exception):
    """The card's `status` is not `"active"`. Covers a sequential
    double-approve (the first call already flipped it) and the concurrent
    loser once the winner's write is visible, plus any other terminal/
    in-flight state (`dismissed`, `executing`)."""


class NoProductsForShop(Exception):
    """The caller's shop has zero `products` rows -- ADR-082 decision 4: an
    honest 409, never a run created with a NULL `product_id`, never a bare
    500 from the column's NOT NULL constraint."""


@dataclass(frozen=True)
class ApprovalResult:
    run_id: uuid.UUID
    action_card_id: uuid.UUID
    approval_id: uuid.UUID
    product_id: uuid.UUID
    status: str


def _card_snapshot(card: ActionCard) -> dict[str, Any]:
    """VERBATIM snapshot of the card as shown at approval time -- captured
    by the caller BEFORE `card.status` is flipped below, so `status` here
    always reads `"active"`, matching what the seller actually saw. Written
    once to `action_card_approvals.card_snapshot` and never re-derived; the
    audit must survive the card row itself later changing (#1214's
    `ActionCardApproval` docstring)."""
    return {
        "id": str(card.id),
        "shop_id": str(card.shop_id),
        "workflow_key": card.workflow_key,
        "priority": card.priority,
        "severity": card.severity,
        "title": card.title,
        "description": card.description,
        "recommendation_payload": card.recommendation_payload,
        "status": card.status,
        "computed_at": card.computed_at.isoformat() if card.computed_at else None,
    }


def _initial_run_state_for(card: ActionCard) -> dict[str, Any]:
    """The complete `workflow_runs.state` blob (issue #1188) plus the
    opening `source: "juli"` context message
    (`prompts/optimize_product/v1.md` Sec.3-4) for the run this approval
    creates.

    Unlike the now-removed `agent_runs.py::_build_initial_run_state` (which
    had no card in hand and had to re-query "the most recent card for this
    workflow" as a heuristic rationale source), this always has the EXACT
    card the seller approved -- its own `description` is the rationale
    directly, no lookup needed.
    """
    from juli_backend.services.agent import run_context as run_context_module

    rationale = card.description or run_context_module.DIRECT_RUN_RATIONALE
    opening = run_context_module.build_opening_context_message(
        workflow_key=card.workflow_key, rationale=rationale
    )
    return run_context_module.initial_run_state(opening)


def _resolve_optimize_product_prompt_pin() -> tuple[str, str]:
    """The production-pinned `(prompt_version, prompt_sha256)` for the
    Optimize Product workflow -- the only `Playbook` this wave implements.
    Every run this transaction creates runs that one playbook, regardless
    of the approved card's own `workflow_key`, mirroring exactly what the
    now-removed `agent_runs.py::create_run` did before this slice (single-
    workflow scope is a pre-existing, unchanged constraint, not a new
    decision made here).
    """
    from juli_backend.services.agent import playbooks as playbooks_module
    from juli_backend.services.agent import prompts as prompts_module

    workflow_key = playbooks_module.OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key
    version = prompts_module.production_version(workflow_key)
    return (
        prompts_module.prompt_version(workflow_key, version),
        prompts_module.prompt_sha256(workflow_key, version),
    )


async def approve_action_card(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    action_card_id: uuid.UUID,
    approved_by_user_id: uuid.UUID,
    now: Clock | None = None,
) -> ApprovalResult:
    """Approve `action_card_id` under `shop_id` and create the agent run it
    authorizes, all on `session` -- see module docstring for the exact step
    order and the "no commit here" contract. Raises `ActionCardNotFound`,
    `ActionCardNotActive`, or `NoProductsForShop` for the three fail-closed
    conditions; the caller is responsible for translating those (and any
    `IntegrityError` its own `session.commit()` raises) to HTTP responses
    and for calling `session.rollback()` in every failure branch.
    """
    clock = now or _default_clock

    try:
        card = await ActionCardsRepo(session).get(shop_id, action_card_id)
    except NotFound as exc:
        raise ActionCardNotFound(str(exc)) from exc

    if card.status != "active":
        raise ActionCardNotActive(
            f"ActionCard {action_card_id} is not active (status={card.status!r})"
        )

    # Captured BEFORE the flip below -- the audit is what was shown.
    snapshot = _card_snapshot(card)

    approved_at = clock()
    card.status = "approved"
    card.approved_at = approved_at

    # ADR-082 decision 2: highest revenue first, tiktok_product_id ascending
    # tiebreak. This SELECT autoflushes the pending card.status UPDATE above
    # to the database (still inside the open transaction, not committed).
    product = await ProductsRepo(session).get_highest_revenue_product(shop_id)
    if product is None:
        raise NoProductsForShop(f"Shop {shop_id} has no products to bind this run to")

    prompt_version_value, prompt_sha256_value = _resolve_optimize_product_prompt_pin()
    initial_state = _initial_run_state_for(card)

    run = WorkflowRunRow(
        shop_id=shop_id,
        product_id=product.id,
        action_card_id=card.id,
        state=initial_state,
        status="queued",
        prompt_version=prompt_version_value,
        prompt_sha256=prompt_sha256_value,
    )
    session.add(run)

    approval = ActionCardApproval(
        action_card_id=card.id,
        approved_by_user_id=approved_by_user_id,
        approved_at=approved_at,
        card_snapshot=snapshot,
    )
    session.add(approval)

    # Sends all three writes to Postgres (still uncommitted) and assigns the
    # client-side uuid.uuid4() primary keys read below. This is also where
    # a raced concurrent second active run for `product.id` surfaces as
    # IntegrityError, in-transaction -- the caller translates it to 409.
    await session.flush()

    return ApprovalResult(
        run_id=run.id,
        action_card_id=card.id,
        approval_id=approval.id,
        product_id=product.id,
        status=run.status,
    )
