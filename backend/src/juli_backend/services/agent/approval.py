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
3. **read the subject off the card** (issue #1702, ADR-087 d.1): the run is
   bound to whatever the card was about -- `card.subject_type` /
   `card.subject_id`. A card that carries no subject, or a subject kind this
   runtime cannot bind a run to yet, raises `CardSubjectNotApprovable`.
4. INSERT the `workflow_run`, stamping the card's own `workflow_key` and
   subject (`product_id` where the subject is a product, **and**
   `action_card_id`)
5. INSERT the approval audit row (`action_card_approvals`): who, when, a
   VERBATIM snapshot of the card as it read *before* the flip above (the
   state the seller actually saw -- `status` in the snapshot is always
   `"active"`)
6. a `session.flush()` (never `commit()`) surfaces a raced concurrent
   second active run for the same `(shop, workflow_key, subject)` as
   `IntegrityError`
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

**The card decides, not the shop (issue #1702, W9-A/P-SHARED-2).** This
module used to resolve two things from somewhere other than the approved
card: the playbook (there was one registered, so every run executed it) and
the bound product (`ProductsRepo.get_highest_revenue_product`, ADR-082
decision 2). Both are gone. The run now carries `card.workflow_key`,
resolved through `playbooks.get_playbook` -- the same registry the worker
and the reaper read -- and its subject is `card.subject_type` /
`card.subject_id` verbatim. `get_highest_revenue_product` is deleted from
`repositories/commerce.py` outright rather than left unreferenced, so a
future caller cannot reintroduce the substitution by reaching for a helper
that is still lying around; `NoProductsForShop` is deleted with it.

**Coexistence note, and it is the whole risk of this slice.** No card
producer writes a subject yet -- #1701 backfilled every existing
`action_cards` row to `subject_type='unscoped'`/`subject_id=''` precisely
because none existed, and `services/action_cards/persist.py` (the scoring
persist path) and `services/seeds/demo_tenant.py` still name neither column.
Subject-scoped emission is #1703. Until #1703 lands, EVERY card refuses
approval with `CardSubjectNotApprovable` (409). That refusal is the point --
it is the honest replacement for silently binding the seller's best-selling
product to a card that never mentioned it -- but it means #1702 and #1703
must reach a seller together.

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
`ActionCardNotActive`/`WorkflowNotExecutable`/`CardSubjectNotApprovable`
before the flush, `IntegrityError` at or after it). This is what makes the
whole thing one transaction:
nothing durable exists until that one commit succeeds, so a crash or a
raised exception anywhere in this function -- so long as the caller then
rolls back -- leaves the card, the run, and the audit row all unwritten
together. Note that SQLAlchemy's default autoflush means the `card.status`
UPDATE is typically sent to Postgres (though still not committed) even
earlier than that, by the time the subject-verification SELECT below runs.
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
from juli_backend.services.agent import playbooks as playbooks_module

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


class WorkflowNotExecutable(Exception):
    """The card's `workflow_key` has no registered playbook -- ADR-084 decision 3.
    The card is refused for approval before any run is created; the card
    remains `active` and unchanged.

    Issue #1702 kept this exception and its position (first, before any
    write) and only changed what raises it: `playbooks.get_playbook`'s
    `UnregisteredWorkflowError` is translated here rather than a separate
    `is_workflow_executable` predicate being consulted and the playbook
    looked up again afterwards. Refusing an unrecognised key is #1350
    (#1309)'s named 409 and is NOT reimplemented here."""


class CardSubjectNotApprovable(Exception):
    """The approved card carries no subject a run can be bound to
    (issue #1702, ADR-087 d.1).

    Two causes are reachable today, and they are deliberately ONE exception
    because both are the same fail-closed refusal at the same point in the
    transaction -- the message names which:

    * the card predates subject scoping (`subject_type == "unscoped"`, or an
      empty `subject_id`). #1701 backfilled every existing row that way
      because no real value existed to write, and no producer writes one yet
      (#1703). See the module docstring's coexistence note.
    * the card names a subject kind this runtime cannot bind a run to yet.
      `_BINDABLE_SUBJECT_TYPES` below is the whole list, and widening it is
      #1704's job, not a caller's.

    This replaces `NoProductsForShop` (ADR-082 decision 4), which is deleted:
    the approve path no longer asks the shop for a product at all, so "this
    shop has no products" stopped being a reason approval can fail."""


#: Subject kinds `approve_action_card` can bind a run to. ONE entry today.
#: A card naming anything else is refused by name rather than coerced --
#: `workflow_runs` carries `subject_type`/`subject_ref` for any string, but
#: the run created here still needs a `product_id` for the worker's
#: `_load_context`, and inventing one is the substitution #1702 deleted.
#:
#: **Still one entry after #1704 (W9-A/P-SHARED-4), deliberately.** That
#: slice made tool dispatch domain-based, and a `ToolDomain` declares the
#: subject kinds it acts on
#: (`tools/domain_registry.py::bindable_subject_types`), so the runtime can
#: now *express* a non-product subject. It cannot yet *run* one: only the
#: product domain is registered, and
#: `workers/tasks/agent_workflow.py::_load_context` still loads a `Product`
#: for every run unconditionally, so a run bound to a SKU set would be
#: created and then fail in the worker. Widening this set therefore has
#: four halves that move together, and
#: `tests/unit/test_tool_dispatcher_domains.py
#: ::test_bindable_subject_types_and_the_approval_wire_widen_together` is the
#: tripwire that fails the day one of them moves alone:
#:
#: 1. this set, and `bindable_subject_types()` growing a second kind;
#: 2. `services/action_cards/subjects.py::BINDABLE_SUBJECT_TYPES` -- the set
#:    the card PRODUCER may emit, added by #1703 after this note was first
#:    written, and kept identical to this one by its own comment rather than
#:    by anything mechanical. Emitting a subject kind approve cannot bind
#:    would refuse every such card at approval;
#: 3. `ApprovalResult.product_id` -> `uuid.UUID | None`, and
#:    `DemoDecisionApproveData.product_id` with it (see that field's note);
#: 4. `_load_context`'s unconditional `Product` load.
_BINDABLE_SUBJECT_TYPES: frozenset[str] = frozenset({"product"})

#: `action_cards.subject_type`'s #1701 backfill value: "this card predates
#: subject scoping". Named rather than spelled inline so the coexistence
#: window with #1703 is greppable from both ends.
_UNSCOPED_SUBJECT_TYPE = "unscoped"


@dataclass(frozen=True)
class ApprovalResult:
    run_id: uuid.UUID
    action_card_id: uuid.UUID
    approval_id: uuid.UUID
    #: The run's subject, verbatim from the card (#1702). `product_id` stays
    #: a non-optional `uuid.UUID` rather than widening because only a product
    #: subject is bindable today (`_BINDABLE_SUBJECT_TYPES`) and
    #: `DemoDecisionApproveData.product_id` is a non-optional `uuid.UUID` on
    #: the wire. #1704 did NOT widen the pair: it made the *precondition* for
    #: widening explicit and executable instead -- see
    #: `_BINDABLE_SUBJECT_TYPES`' own note for the four halves that must move
    #: together, and the tripwire test that fails if one moves alone.
    product_id: uuid.UUID
    workflow_key: str
    subject_type: str
    subject_ref: str
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


@dataclass(frozen=True)
class _CardSubject:
    """The run's subject, read off the card (issue #1702, ADR-087 d.1).

    `subject_type`/`subject_ref` are what `workflow_runs` stores; `product_id`
    is the same value re-typed for the `products` foreign key, and is
    non-None for exactly the `"product"` subject kind.
    """

    subject_type: str
    subject_ref: str
    product_id: uuid.UUID


async def _resolve_card_subject(session: AsyncSession, card: ActionCard) -> _CardSubject:
    """The card's own subject, verified to exist under the card's shop.

    Fail-closed at every step, and never by substitution:

    * an unscoped card (or an empty `subject_id`) is refused -- there is no
      subject to bind, and the shop's best-selling product is NOT it;
    * a subject kind outside `_BINDABLE_SUBJECT_TYPES` is refused by name;
    * a `"product"` subject whose `subject_id` is not a UUID is refused
      rather than reaching the foreign key as a `DataError`;
    * a product that does not exist under this card's shop is refused with
      the same named error rather than surfacing as the `IntegrityError` the
      route translates to "an active run already exists" -- a wrong message
      for a wrong subject. `ProductsRepo.get` reports a row under a different
      shop as missing, so this cannot become a cross-tenant existence oracle.

    This SELECT is where SQLAlchemy's autoflush sends the pending
    `card.status` UPDATE to Postgres (still inside the open transaction,
    never committed) -- the same position the deleted highest-revenue SELECT
    held, so the transaction's flush ordering is unchanged.
    """
    subject_type = card.subject_type
    subject_ref = card.subject_id

    if subject_type == _UNSCOPED_SUBJECT_TYPE or not subject_ref:
        raise CardSubjectNotApprovable(
            f"ActionCard {card.id} carries no subject "
            f"(subject_type={subject_type!r}, subject_id={subject_ref!r}) "
            "and cannot be approved; a card's subject is what the run acts on"
        )

    if subject_type not in _BINDABLE_SUBJECT_TYPES:
        raise CardSubjectNotApprovable(
            f"ActionCard {card.id} has subject_type {subject_type!r}, which "
            f"approve cannot bind a run to; bindable kinds are "
            f"{sorted(_BINDABLE_SUBJECT_TYPES)}"
        )

    try:
        product_id = uuid.UUID(subject_ref)
    except ValueError as exc:
        raise CardSubjectNotApprovable(
            f"ActionCard {card.id} has subject_type 'product' but its "
            f"subject_id {subject_ref!r} is not a product id"
        ) from exc

    try:
        await ProductsRepo(session).get(card.shop_id, product_id)
    except NotFound as exc:
        raise CardSubjectNotApprovable(
            f"ActionCard {card.id} names product {product_id} as its subject, "
            "which does not exist for this shop"
        ) from exc

    return _CardSubject(
        subject_type=subject_type,
        subject_ref=subject_ref,
        product_id=product_id,
    )


def _resolve_prompt_pin(workflow_key: str) -> tuple[str, str]:
    """The production-pinned `(prompt_version, prompt_sha256)` for the given
    workflow_key (ADR-084 decision 3).

    This function looks up the playbook from the registry to determine the
    correct prompt version and sha256, based on the card's own
    `workflow_key`. Non-executable workflow_keys should be rejected before
    calling this function (see `approve_action_card`).
    """
    from juli_backend.services.agent import prompts as prompts_module

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
    `ActionCardNotActive`, `WorkflowNotExecutable`, or
    `CardSubjectNotApprovable` for the four fail-closed conditions; the caller
    is responsible for translating those (and any `IntegrityError` its own
    `session.commit()` raises) to HTTP responses and for calling
    `session.rollback()` in every failure branch.

    The run this creates executes the approved card's OWN workflow on the
    approved card's OWN subject (issue #1702). Nothing here consults the
    shop's products, the most recent card, or any other card.
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

    # ADR-084 decision 3 / issue #1702: resolve the card's OWN workflow
    # through the registry the worker and the reaper also read. This happens
    # BEFORE any database changes, so a card whose key is not registered is
    # refused without creating or modifying any rows -- and, crucially,
    # without substituting the one registered playbook for it.
    try:
        playbook = playbooks_module.get_playbook(card.workflow_key)
    except playbooks_module.UnregisteredWorkflowError as exc:
        raise WorkflowNotExecutable(
            f"ActionCard {action_card_id} has workflow_key {card.workflow_key!r} "
            f"which has no registered playbook and cannot be executed"
        ) from exc

    # Captured BEFORE the flip below -- the audit is what was shown.
    snapshot = _card_snapshot(card)

    approved_at = clock()
    card.status = "approved"
    card.approved_at = approved_at

    subject = await _resolve_card_subject(session, card)

    prompt_version_value, prompt_sha256_value = _resolve_prompt_pin(playbook.workflow_key)
    initial_state = _initial_run_state_for(card)

    run = WorkflowRunRow(
        shop_id=shop_id,
        product_id=subject.product_id,
        action_card_id=card.id,
        workflow_key=playbook.workflow_key,
        subject_type=subject.subject_type,
        subject_ref=subject.subject_ref,
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
    # a raced concurrent second active run for this `(shop, workflow_key,
    # subject)` surfaces as IntegrityError, in-transaction -- the caller
    # translates it to 409.
    await session.flush()

    return ApprovalResult(
        run_id=run.id,
        action_card_id=card.id,
        approval_id=approval.id,
        product_id=subject.product_id,
        workflow_key=run.workflow_key,
        subject_type=run.subject_type,
        subject_ref=run.subject_ref,
        status=run.status,
    )
