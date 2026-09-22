"""What an Action Card is *about* — subject resolution at emission time.

ADR-087 decision 1 widens a card's identity from ``(shop, workflow_key)`` to
``(shop, workflow_key, subject_type, subject_id)``, and **amends ADR-082
decision 1** in the process: *"product binding moves from approval-time
revenue derivation to card-generation time... deriving a different product at
approval would contradict the card the seller was shown."* #1701 added the
columns and backfilled every existing row to ``subject_type='unscoped'``.
This module is the producer those columns were waiting for (#1703).

**The rule this module exists to enforce: a subject is resolved from the
producer's own evidence, or it is not resolved at all.** A card never gets a
subject invented for it to satisfy a consumer's guard. A fabricated
``subject_id`` pointing at an arbitrary row is strictly worse than no subject:
the refusal is visible, a run against the wrong product is not.

## Which workflows yield a per-subject card, and which do not

The scoring pipeline (``services/scoring``) computes shop-level KPI
aggregates. ``WorkflowRecommendation`` carries no entity reference at all --
it is a ranked ``workflow_key`` with a rationale. So "which subject?" has no
automatic answer, and the honest answer differs per key:

* ``optimize_product_2`` -- **per product**. Its subject is a ``products``
  row, which exists on every connected shop before it ever meets Juli, and
  the ordering that picks one (``revenue`` descending, ``tiktok_product_id``
  ascending) is the exact rule ADR-082 decision 2 already defined. ADR-087
  decision 1 does not delete that rule, it *relocates* it: choosing what to
  offer is a producer's job, substituting a different subject at approval
  time is not. This is the case #1701's re-keyed partial unique index was
  built for.

* **Every other key -- no resolvable subject, and it stays ``unscoped``.**
  Not because the design says they are shop-level (ADR-087 decision 5 assigns
  ``replenish_inventory_3``/``clear_excess_4`` to Product, ``process_order_5``
  to Order, the ``prevent_*`` family to After-sales), but because the rows
  those subjects would point at do not exist: ADR-087's Context records that
  ``inventory_items``, ``orders``, ``campaigns``, ``returns`` and
  ``livestreams`` are empty on **every** shop on the deployed database,
  production's 116-product merchant included, and its Consequences say so in
  as many words -- *"Only ``optimize_product_2`` is provable today."*
  ``create_*`` keys are excluded by ADR-087 decision 4 on a different and
  permanent ground: they act on something that does not exist yet.

``unscoped`` is therefore **not** a shop-level subject and **not**
approvable. It is the honest statement "this producer could not name what
this card is about", and it keeps ``_BINDABLE_SUBJECT_TYPES`` in
``services/agent/approval.py`` (issue #1702) exactly as that slice wrote it:
widening it is #1704's declared seam, and nothing here needs it widened.
An unscoped card is still emitted and still surfaced -- it is advisory copy
the seller can act on by hand, and every key that produces one also has no
registered playbook, so ``approve`` already refuses it one gate earlier with
``WorkflowNotExecutable``.

## Coordination note for issue #1702 (PR #2074)

``BINDABLE_SUBJECT_TYPES`` below and ``approval._BINDABLE_SUBJECT_TYPES``
are the same set and must never drift. #1702 branched before this module
existed, so the two are written twice today; the moment both are on ``main``,
``approval.py`` should import this one and delete its own copy. That is a
mechanical follow-up, not a widening -- #1704 owns any change to the *value*.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ActionCard, Product

#: ``action_cards.subject_type`` for a card whose subject is a ``products``
#: row; ``subject_id`` is that row's ``id`` as a string (the internal UUID,
#: not ``tiktok_product_id`` -- the approve path resolves it through
#: ``ProductsRepo.get(shop_id, uuid)``).
SUBJECT_TYPE_PRODUCT = "product"

#: ``action_cards.subject_type`` for a card whose subject could not be
#: resolved -- #1701's backfill value, and the value this module writes when
#: the producer has no evidence naming an entity. Both populations mean the
#: same thing and are treated the same way everywhere: not approvable.
SUBJECT_TYPE_UNSCOPED = "unscoped"

#: Subject kinds a run can be bound to today. Kept identical to
#: ``services/agent/approval.py::_BINDABLE_SUBJECT_TYPES`` (issue #1702) --
#: see the module docstring's coordination note. Widening this is #1704's
#: seam, never a caller's convenience.
BINDABLE_SUBJECT_TYPES: frozenset[str] = frozenset({SUBJECT_TYPE_PRODUCT})


@dataclass(frozen=True, slots=True)
class CardSubject:
    """What one emitted card is about.

    ``label`` is a human-readable name for the subject, carried in the card's
    payload for the audit snapshot and for W9-D's rendering. It is never part
    of the card's identity -- only ``subject_type``/``subject_id`` are.
    """

    subject_type: str
    subject_id: str
    label: str | None = None

    @property
    def is_resolved(self) -> bool:
        return self.subject_type != SUBJECT_TYPE_UNSCOPED and bool(self.subject_id)


#: The subject of a card whose producer could not name one. Matches #1701's
#: backfill exactly (``'unscoped'`` / ``''``), so a legacy row and a freshly
#: emitted unresolved row are the same tuple and collide on the same partial
#: unique index -- which is what keeps "one live card per workflow" true for
#: the keys that have no subject.
UNSCOPED_SUBJECT = CardSubject(subject_type=SUBJECT_TYPE_UNSCOPED, subject_id="")


async def _resolve_product_subject(session: AsyncSession, shop_id: uuid.UUID) -> CardSubject:
    """The shop's top-revenue product, or ``UNSCOPED_SUBJECT`` if it has none.

    ``revenue`` descending with ``tiktok_product_id`` ascending as tiebreak --
    the ordering ADR-082 decision 2 defined and justified: *"Without it two
    products with equal revenue resolve in whatever order Postgres returns
    them"*, and a card that names a different listing on each refresh is a
    card the seller cannot trust.

    Queried here rather than through ``ProductsRepo.get_highest_revenue_product``
    deliberately. Issue #1702 deletes that repo method outright so the approve
    path cannot reach for it again; the selection belongs to the producer
    now, and keeping the query on the producer's side is what makes that
    deletion permanent rather than a helper that moved house.

    A shop with zero products yields no subject. The card is still emitted,
    unscoped and unapprovable -- "you have nothing to optimize" is the truth,
    and an invented product id would not be.
    """
    stmt = (
        select(Product)
        .where(Product.shop_id == shop_id)
        .order_by(Product.revenue.desc(), Product.tiktok_product_id.asc())
        .limit(1)
    )
    product = (await session.execute(stmt)).scalars().first()
    if product is None:
        return UNSCOPED_SUBJECT
    return CardSubject(
        subject_type=SUBJECT_TYPE_PRODUCT,
        subject_id=str(product.id),
        label=product.title or product.name,
    )


#: Workflow keys whose subject this producer can resolve, and how. A key that
#: is absent yields ``UNSCOPED_SUBJECT`` -- see the module docstring for why
#: that is the whole rest of the catalog today, and what would have to change
#: (ingest populating ``orders``/``inventory_items``/``campaigns``) before a
#: key moves into this table.
_SUBJECT_RESOLVERS = {
    "optimize_product_2": _resolve_product_subject,
}


async def resolve_card_subject(
    session: AsyncSession,
    shop_id: uuid.UUID,
    workflow_key: str,
) -> CardSubject:
    """The subject for a card about to be emitted for *workflow_key*.

    Never raises and never invents: an unresolvable subject comes back as
    ``UNSCOPED_SUBJECT``, which is a value the whole pipeline already
    understands (#1701's backfill wrote it on every row).
    """
    resolver = _SUBJECT_RESOLVERS.get(workflow_key)
    if resolver is None:
        return UNSCOPED_SUBJECT
    return await resolver(session, shop_id)


def card_subject_is_bindable(card: ActionCard) -> bool:
    """Whether ``approve`` can bind a run to *card*'s subject.

    This is the *same* predicate ``services/agent/approval.py`` applies
    before creating a run (issue #1702): a subject type in
    ``BINDABLE_SUBJECT_TYPES`` and a non-empty ``subject_id``. It exists here
    so a read surface can agree with the write surface instead of guessing --
    ``demo_decisions/read.py``'s ``is_executable`` reported ``true`` for
    subject-less cards that approve refuses, and a listing that disagrees
    with its own approve endpoint is a lie the seller discovers by clicking.

    It does **not** verify the referenced row exists -- that needs a query and
    a shop scope, and approve does it for real at the moment it matters.
    """
    return card.subject_type in BINDABLE_SUBJECT_TYPES and bool(card.subject_id)


__all__ = [
    "BINDABLE_SUBJECT_TYPES",
    "SUBJECT_TYPE_PRODUCT",
    "SUBJECT_TYPE_UNSCOPED",
    "UNSCOPED_SUBJECT",
    "CardSubject",
    "card_subject_is_bindable",
    "resolve_card_subject",
]
