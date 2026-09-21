"""Subject-scoped card emission, chained revisions, named suppression — #1703.

ADR-087 decisions 1, 3 and 6, moved to Accepted by this slice.

AC1 → an active card for a subject + an unchanged basis writes no row and the
      suppression reason is ``basis_unchanged``.
AC2 → an executed card for a subject + a changed basis writes a new row at
      ``revision + 1`` with ``supersedes_card_id`` set, and the predecessor's
      payload is not copied forward.
AC3 → a second emission for a subject whose card is still standing is
      suppressed with ``active_card_exists`` — never a second active row.
AC4 → the emission budget's reasons are unchanged and stay distinguishable
      from the revision reasons.

Plus the two things this slice exists to unblock, which the acceptance list
does not name:

* the emitted card carries a subject the **approve** path will accept —
  without it #1702 refuses every card with ``CardSubjectNotApprovable`` and
  no seller can approve anything;
* ``basis_unchanged`` and ``active_card_exists`` are distinguishable *in the
  same GIVEN*, not merely different strings.

Every test here drives the real ``persist_scoring_result`` /
``emit_scoring_cards`` producer over real ``Shop``/``Product`` rows. None
constructs an ``ActionCard`` to stand in for what emission would have
written: the recurring defect in this repository is a consumer that ships
without its producer while every test supplies the value itself, and a card
subject is exactly that shape of value.

**Postgres-only, therefore not proven here:** the ``session`` fixture is
SQLite. The partial unique index ``uq_action_cards_active_shop_workflow_subject``
now builds partially on SQLite too (``sqlite_where``, ``models.py``), so
"never two active rows for one subject" is exercised against a real index of
the right shape — but RLS, and the Postgres-side behaviour of the index under
concurrent writers, are not. Those need the integration lane.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from juli_backend.models.models import ActionCard, Product, Shop, User
from juli_backend.repositories.repos import ProductsRepo
from juli_backend.services.action_cards.basis import BASIS_METADATA_KEY, stored_basis
from juli_backend.services.action_cards.emission_budget import SUPPRESSED_REASONS
from juli_backend.services.action_cards.persist import (
    REVISION_SUPPRESSED_REASONS,
    SUPPRESSED_REASON_ACTIVE_CARD_EXISTS,
    SUPPRESSED_REASON_BASIS_UNCHANGED,
    emit_scoring_cards,
    persist_scoring_result,
)
from juli_backend.services.action_cards.subjects import (
    BINDABLE_SUBJECT_TYPES,
    SUBJECT_TYPE_PRODUCT,
    SUBJECT_TYPE_UNSCOPED,
    card_subject_is_bindable,
)
from juli_backend.services.aggregates.types import (
    FeatureAggregateSnapshot,
    HealthDataSource,
    ShopProfile,
)
from juli_backend.services.scoring.types import (
    AdvisorySignal,
    DailyScoringResult,
    KpiId,
    ScoringSignals,
    Severity,
    VisualLayerDomain,
    WorkflowExpectedImpact,
    WorkflowRecommendation,
    WorkflowRecommendations,
)

OPTIMIZE = "optimize_product_2"
RUN_AT = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
async def shop(session, user_id):
    user = User(id=user_id, phone="+849170001703")
    row = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="W9-A Revisions Shop",
        tiktok_shop_id="tiktok_shop_1703",
    )
    session.add_all([user, row])
    await session.flush()
    return row


@pytest.fixture
async def products(session, shop):
    """Two products, so "which one?" is a real choice rather than the only row."""
    top = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id="ttp-top",
        name="Top seller",
        title="Top seller",
        status="ACTIVE",
        price=Decimal("199000"),
        inventory=12,
        revenue=Decimal("5000000"),
        units_sold=40,
        update_time=RUN_AT,
    )
    tail = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id="ttp-tail",
        name="Long tail",
        title="Long tail",
        status="ACTIVE",
        price=Decimal("49000"),
        inventory=3,
        revenue=Decimal("120000"),
        units_sold=2,
        update_time=RUN_AT,
    )
    session.add_all([top, tail])
    await session.flush()
    return top, tail


def _signal(kpi_id: KpiId, severity: Severity) -> AdvisorySignal:
    return AdvisorySignal(
        kpi_id=kpi_id,
        domain=VisualLayerDomain.REVENUE,
        technique="rules_proxy",
        change_text="test",
        signal_type="risk",
        action_hint="test",
        one_line="test",
        workflow_keys=(OPTIMIZE,),
        severity=severity,
    )


def _result(
    shop_id: uuid.UUID,
    *,
    computed_at: datetime = RUN_AT,
    workflow_key: str = OPTIMIZE,
    workflow_name: str = "Tối ưu sản phẩm",
    priority: int = 1,
    severity: Severity = "warning",
    rationale: str = "Conversion is slipping on your best listing",
) -> DailyScoringResult:
    """A real ``DailyScoringResult``, the shape ``run_daily_scoring_for_shop``
    returns — the producer's own input type, not a stand-in."""
    return DailyScoringResult(
        aggregates=FeatureAggregateSnapshot(
            shop_id=shop_id,
            shop_profile=ShopProfile.MID_LARGE_SHOP,
            health_data_source=HealthDataSource.PROXY,
            sps_score=None,
            vp_score=None,
            ahr_score=None,
            order_count=20,
            product_count=2,
            return_count=0,
            total_order_value=Decimal("5120000"),
            total_product_revenue=Decimal("5120000"),
            total_units_sold=42,
            return_rate_proxy=0.0,
            data_sources=["products", "orders"],
        ),
        signals=ScoringSignals(
            shop_id=shop_id,
            computed_at=computed_at,
            health_data_source=HealthDataSource.PROXY,
            kpis={"conversion_rate_by_category": _signal("conversion_rate_by_category", severity)},
        ),
        recommendations=WorkflowRecommendations(
            shop_profile=ShopProfile.MID_LARGE_SHOP,
            recommended_workflows=[
                WorkflowRecommendation(
                    workflow_key=workflow_key,
                    workflow_name=workflow_name,
                    priority=priority,
                    rationale=rationale,
                    expected_impact=WorkflowExpectedImpact(
                        metric="conversion_rate_by_category",
                        value=50.0,
                        confidence="medium",
                    ),
                    preconditions_met=True,
                    user_action_required=True,
                    source_kpi_ids=("conversion_rate_by_category",),
                )
            ],
        ),
        reasoning_summaries=(),
    )


async def _rows(session, shop_id: uuid.UUID, workflow_key: str = OPTIMIZE):
    stmt = (
        select(ActionCard)
        .where(ActionCard.shop_id == shop_id, ActionCard.workflow_key == workflow_key)
        .order_by(ActionCard.revision.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# The producer writes a subject the approve path accepts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emitted_optimize_card_carries_an_approvable_product_subject(session, shop, products):
    """The whole point of the slice: a card a seller can actually approve.

    #1702 reads the run's subject off the card and refuses anything that
    carries none (``CardSubjectNotApprovable``); #1701 backfilled every
    existing row to ``unscoped``. With no producer writing a subject, every
    active card 409s on approve. This asserts the producer closes that.

    The three checks are exactly the three ``approval._resolve_card_subject``
    performs, in its order: a subject kind in ``_BINDABLE_SUBJECT_TYPES``
    with a non-empty ``subject_id``; a ``subject_id`` that parses as a UUID;
    and a ``products`` row under *this card's shop* for it
    (``ProductsRepo.get``, which reports another shop's row as missing).
    """
    top, _tail = products

    cards = await persist_scoring_result(session, shop.id, _result(shop.id))
    await session.flush()

    assert len(cards) == 1
    card = cards[0]

    assert card.subject_type == SUBJECT_TYPE_PRODUCT
    assert card.subject_type in BINDABLE_SUBJECT_TYPES
    assert card_subject_is_bindable(card) is True

    product_id = uuid.UUID(card.subject_id)
    bound = await ProductsRepo(session).get(shop.id, product_id)
    assert bound.id == top.id, "the subject is a real row of this shop, not an invention"

    # And the subject is on the card's payload too, so the verbatim approval
    # snapshot records what the seller was offered.
    payload = json.loads(card.recommendation_payload)
    assert payload["subject"] == {
        "type": SUBJECT_TYPE_PRODUCT,
        "id": str(top.id),
        "label": top.title,
    }


@pytest.mark.asyncio
async def test_a_shop_with_no_products_gets_no_invented_subject(session, shop):
    """Fail closed, never by substitution.

    A shop with zero products cannot be offered a listing to optimize. The
    card is still emitted — it is honest advisory copy — but it carries no
    subject, and approve refuses it. An invented ``subject_id`` would be
    worse than the refusal: it would run a real workflow against the wrong
    thing.
    """
    cards = await persist_scoring_result(session, shop.id, _result(shop.id))
    await session.flush()

    assert len(cards) == 1
    assert cards[0].subject_type == SUBJECT_TYPE_UNSCOPED
    assert cards[0].subject_id == ""
    assert card_subject_is_bindable(cards[0]) is False


@pytest.mark.asyncio
async def test_first_emission_starts_the_chain_at_revision_one(session, shop, products):
    report = await emit_scoring_cards(session, shop.id, _result(shop.id))
    await session.flush()

    (decision,) = report.decisions
    assert decision.suppressed_reason is None
    assert decision.revision == 1
    assert decision.card is not None
    assert decision.card.revision == 1
    assert decision.card.supersedes_card_id is None
    assert stored_basis(decision.card) is not None


# ---------------------------------------------------------------------------
# AC1 — unchanged basis suppresses with a named reason
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unchanged_basis_suppresses_with_named_reason(session, shop, products):
    """AC1: an active card for a subject, nothing material moved, no row written."""
    first = await emit_scoring_cards(session, shop.id, _result(shop.id))
    await session.flush()
    original = first.decisions[0].card
    assert original is not None
    original_id = original.id
    original_title = original.title

    # A later scoring run: a new computed_at, new copy, new priority — and the
    # same underlying evidence. computed_at and copy are deliberately outside
    # the basis, so none of that is a reason to offer the seller a second pass.
    second = await emit_scoring_cards(
        session,
        shop.id,
        _result(
            shop.id,
            computed_at=datetime(2026, 9, 8, 9, 0, tzinfo=UTC),
            workflow_name="Tối ưu sản phẩm (rescored)",
            priority=4,
            rationale="Reworded rationale",
        ),
    )
    await session.flush()

    (decision,) = second.decisions
    assert decision.suppressed_reason == SUPPRESSED_REASON_BASIS_UNCHANGED
    assert second.emitted == []

    rows = await _rows(session, shop.id)
    assert len(rows) == 1
    assert rows[0].id == original_id
    assert rows[0].title == original_title


# ---------------------------------------------------------------------------
# AC2 — a changed basis emits a chained successor, nothing copied
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_changed_basis_emits_chained_successor_without_copying(session, shop, products):
    """AC2: revision + 1, ``supersedes_card_id`` set, payload built fresh.

    The predecessor is *executed* — ADR-087 decision 6 defines a successor as
    following the last executed revision — and carries a marker in its
    payload that only a copy-forward could reproduce. The second emission is
    dated past the 7-day churn floor; the floor itself is pinned by
    ``test_a_changed_basis_inside_the_churn_floor_still_waits`` below.
    """
    top, _tail = products

    first = await emit_scoring_cards(session, shop.id, _result(shop.id))
    await session.flush()
    predecessor = first.decisions[0].card
    assert predecessor is not None

    # Mark it executed, and plant a marker a copy-forward would carry over.
    predecessor_payload = json.loads(predecessor.recommendation_payload)
    predecessor_payload["predecessor_only_marker"] = "must not be copied"
    predecessor.recommendation_payload = json.dumps(predecessor_payload)
    predecessor.status = "approved"
    predecessor.approved_at = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    predecessor.executed_at = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
    predecessor.surfaced_at = RUN_AT
    await session.flush()
    predecessor_id = predecessor.id
    predecessor_basis = stored_basis(predecessor)

    # The basis moves: the subject's own price changed.
    top.price = Decimal("149000")
    await session.flush()

    second = await emit_scoring_cards(
        session,
        shop.id,
        _result(shop.id, computed_at=datetime(2026, 9, 12, 9, 0, tzinfo=UTC)),
    )
    await session.flush()

    (decision,) = second.decisions
    assert decision.suppressed_reason is None
    successor = decision.card
    assert successor is not None

    assert successor.id != predecessor_id
    assert successor.revision == predecessor.revision + 1 == 2
    assert successor.supersedes_card_id == predecessor_id
    assert successor.status == "active"
    assert successor.subject_type == SUBJECT_TYPE_PRODUCT
    assert successor.subject_id == str(top.id)

    # Reached by reference, never copied (ADR-087 decision 3).
    successor_payload = json.loads(successor.recommendation_payload)
    assert "predecessor_only_marker" not in successor_payload

    # The predecessor is intact — a chain, not an in-place edit.
    rows = await _rows(session, shop.id)
    assert [row.revision for row in rows] == [1, 2]
    kept = next(row for row in rows if row.id == predecessor_id)
    assert kept.status == "approved"
    assert kept.executed_at is not None
    assert json.loads(kept.recommendation_payload)["predecessor_only_marker"] == (
        "must not be copied"
    )

    # And the successor recorded its own, different basis.
    assert stored_basis(successor) != predecessor_basis
    assert BASIS_METADATA_KEY in json.loads(successor.metadata_json)


@pytest.mark.asyncio
async def test_a_changed_basis_inside_the_churn_floor_still_waits(session, shop, products):
    """ADR-087 decision 9's sentence, made true rather than merely written.

    That decision left the emission budget's cooldown gate alone on the
    reasoning that *"per-card becomes per-subject for free -- and it doubles as
    the secondary time-based floor decision 6 wants, so a basis change inside 7
    days still waits."* Under chained revisions it does not come for free:
    ``emission_budget._terminal_marker`` reads a card's OWN terminal
    timestamps, and a successor is a new row carrying none of its
    predecessor's, so the budget would surface it the day after the
    predecessor executed. The floor lives in emission, where the chain is
    visible.
    """
    top, _tail = products

    first = await emit_scoring_cards(session, shop.id, _result(shop.id))
    await session.flush()
    predecessor = first.decisions[0].card
    assert predecessor is not None
    predecessor.status = "approved"
    predecessor.approved_at = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)
    predecessor.executed_at = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
    predecessor.surfaced_at = RUN_AT
    await session.flush()

    top.price = Decimal("129000")
    await session.flush()

    # Day 6 after execution: the basis moved, and the successor still waits.
    inside = await emit_scoring_cards(
        session,
        shop.id,
        _result(shop.id, computed_at=datetime(2026, 9, 8, 9, 0, tzinfo=UTC)),
    )
    await session.flush()
    assert inside.decisions[0].suppressed_reason == SUPPRESSED_REASON_ACTIVE_CARD_EXISTS
    assert len(await _rows(session, shop.id)) == 1

    # Day 11: the floor has elapsed and the successor lands.
    outside = await emit_scoring_cards(
        session,
        shop.id,
        _result(shop.id, computed_at=datetime(2026, 9, 13, 9, 0, tzinfo=UTC)),
    )
    await session.flush()
    assert outside.decisions[0].suppressed_reason is None
    assert outside.decisions[0].revision == 2
    assert len(await _rows(session, shop.id)) == 2


# ---------------------------------------------------------------------------
# AC3 — a standing card withholds the successor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_active_card_for_subject_is_suppressed(session, shop, products):
    """AC3: the basis moved, but the seller's card is still standing.

    This is the case that would otherwise write a second active row for one
    subject and collide with ``uq_action_cards_active_shop_workflow_subject``.
    The pipeline refuses before the index has to.
    """
    top, _tail = products

    first = await emit_scoring_cards(session, shop.id, _result(shop.id))
    await session.flush()
    standing = first.decisions[0].card
    assert standing is not None
    standing.surfaced_at = RUN_AT  # the budget put it in front of the seller
    await session.flush()
    standing_id = standing.id

    top.price = Decimal("99000")  # the basis genuinely moved
    await session.flush()

    second = await emit_scoring_cards(
        session,
        shop.id,
        _result(shop.id, computed_at=datetime(2026, 9, 10, 9, 0, tzinfo=UTC)),
    )
    await session.flush()

    (decision,) = second.decisions
    assert decision.suppressed_reason == SUPPRESSED_REASON_ACTIVE_CARD_EXISTS
    assert second.emitted == []

    rows = await _rows(session, shop.id)
    assert len(rows) == 1
    assert rows[0].id == standing_id
    active = [row for row in rows if row.status == "active"]
    assert len(active) == 1


@pytest.mark.asyncio
async def test_the_two_revision_reasons_are_distinguishable_in_the_same_given(
    session, shop, products
):
    """Same GIVEN — an active, surfaced card for a subject — two outcomes.

    The only difference between the two runs below is whether the subject's
    basis moved. If either reason were a synonym for "there is already a
    card", these two would be identical; they are not. This is what makes
    each reason *provable for that reason*, rather than merely present in the
    vocabulary.
    """
    top, _tail = products

    first = await emit_scoring_cards(session, shop.id, _result(shop.id))
    await session.flush()
    standing = first.decisions[0].card
    assert standing is not None
    standing.surfaced_at = RUN_AT
    await session.flush()

    unchanged = await emit_scoring_cards(
        session,
        shop.id,
        _result(shop.id, computed_at=datetime(2026, 9, 11, 9, 0, tzinfo=UTC)),
    )
    await session.flush()
    assert unchanged.decisions[0].suppressed_reason == SUPPRESSED_REASON_BASIS_UNCHANGED

    top.price = Decimal("77000")
    await session.flush()

    changed = await emit_scoring_cards(
        session,
        shop.id,
        _result(shop.id, computed_at=datetime(2026, 9, 12, 9, 0, tzinfo=UTC)),
    )
    await session.flush()
    assert changed.decisions[0].suppressed_reason == SUPPRESSED_REASON_ACTIVE_CARD_EXISTS

    assert len(await _rows(session, shop.id)) == 1


@pytest.mark.asyncio
async def test_a_price_move_the_seller_cannot_see_is_not_a_basis_change(session, shop, products):
    """Materiality is per workflow key, and it lives in the projection.

    ADR-087 decision 6: *"a 2% price move and a stock level crossing zero are
    not the same event."* For ``optimize_product_2`` the stock projection is
    the zero crossing, so selling units off the same listing is not a reason
    to re-offer it — while running out is.
    """
    top, _tail = products

    first = await emit_scoring_cards(session, shop.id, _result(shop.id))
    await session.flush()
    standing = first.decisions[0].card
    assert standing is not None
    standing.status = "approved"
    standing.executed_at = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
    await session.flush()

    top.inventory = 4  # 12 -> 4: sold units, still in stock
    await session.flush()
    quiet = await emit_scoring_cards(
        session,
        shop.id,
        _result(shop.id, computed_at=datetime(2026, 9, 13, 9, 0, tzinfo=UTC)),
    )
    await session.flush()
    assert quiet.decisions[0].suppressed_reason == SUPPRESSED_REASON_BASIS_UNCHANGED

    top.inventory = 0  # the crossing
    await session.flush()
    crossed = await emit_scoring_cards(
        session,
        shop.id,
        _result(shop.id, computed_at=datetime(2026, 9, 14, 9, 0, tzinfo=UTC)),
    )
    await session.flush()
    assert crossed.decisions[0].suppressed_reason is None
    assert crossed.decisions[0].revision == 2


# ---------------------------------------------------------------------------
# AC4 — the two vocabularies stay apart
# ---------------------------------------------------------------------------


def test_budget_reasons_and_revision_reasons_are_disjoint():
    """AC4: the emission budget's reasons are unchanged and distinguishable.

    Disjointness is checked on the real frozensets both modules export, and
    the budget's own set is pinned verbatim so widening the revision
    vocabulary can never quietly annex one of its values.
    """
    assert SUPPRESSED_REASONS == frozenset({"active_cap", "cooldown", "weekly_novelty_cap"})
    assert REVISION_SUPPRESSED_REASONS == frozenset({"basis_unchanged", "active_card_exists"})
    assert SUPPRESSED_REASONS.isdisjoint(REVISION_SUPPRESSED_REASONS)


@pytest.mark.asyncio
async def test_revision_reasons_never_reach_the_budget_owned_column(session, shop, products):
    """The structural half of AC4, which a set comparison cannot show.

    ``ActionCard.suppressed_reason`` belongs to the emission budget. If a
    revision reason were written there, the two vocabularies would share one
    carrier and "distinguishable" would be a naming convention rather than a
    fact. The budget's own value on the row survives an emission that
    suppresses for a revision reason.
    """
    first = await emit_scoring_cards(session, shop.id, _result(shop.id))
    await session.flush()
    card = first.decisions[0].card
    assert card is not None
    card.surfaced_at = None
    card.suppressed_reason = "active_cap"  # the budget's verdict, on the row
    card.status = "approved"
    card.approved_at = RUN_AT
    await session.flush()

    report = await emit_scoring_cards(
        session,
        shop.id,
        _result(shop.id, computed_at=datetime(2026, 9, 15, 9, 0, tzinfo=UTC)),
    )
    await session.flush()

    assert report.decisions[0].suppressed_reason in REVISION_SUPPRESSED_REASONS
    rows = await _rows(session, shop.id)
    assert len(rows) == 1
    assert rows[0].suppressed_reason == "active_cap"


@pytest.mark.asyncio
async def test_suppression_is_logged_with_its_reason_and_subject(session, shop, products, caplog):
    """On-call diagnosability, and the only production-visible record of a
    suppression — the reasons are deliberately not on a column."""
    first = await emit_scoring_cards(session, shop.id, _result(shop.id))
    await session.flush()
    card = first.decisions[0].card
    assert card is not None
    card.surfaced_at = RUN_AT
    await session.flush()

    with caplog.at_level("INFO"):
        await emit_scoring_cards(
            session,
            shop.id,
            _result(shop.id, computed_at=datetime(2026, 9, 16, 9, 0, tzinfo=UTC)),
        )

    records = [r for r in caplog.records if r.message == "action_card_emission_suppressed"]
    assert len(records) == 1
    assert records[0].suppressed_reason == SUPPRESSED_REASON_BASIS_UNCHANGED
    assert records[0].subject_type == SUBJECT_TYPE_PRODUCT
    assert records[0].workflow_key == OPTIMIZE
    # No card copy in the log line (PRD security stories 22/23).
    assert not hasattr(records[0], "title")


# ---------------------------------------------------------------------------
# The #1701 coexistence bridge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_pre_1703_unscoped_card_gains_its_subject_instead_of_a_twin(
    session, shop, products
):
    """The 9 active production rows #1701 backfilled must become approvable.

    They carry ``subject_type='unscoped'``. A naive subject-scoped emission
    would insert a *second* live card beside each one — the partial unique
    index keys on the subject, and those two subjects differ — leaving the
    seller with two cards for one workflow and the old one still refusing
    approval. The standing subject-less candidate is completed instead.
    """
    top, _tail = products

    legacy = ActionCard(
        id=uuid.uuid4(),
        shop_id=shop.id,
        workflow_key=OPTIMIZE,
        subject_type=SUBJECT_TYPE_UNSCOPED,
        subject_id="",
        revision=1,
        priority=1,
        severity="warning",
        title="Tối ưu sản phẩm",
        description="Pre-#1703 row",
        recommendation_payload="{}",
        status="active",
        surfaced_at=RUN_AT,
        computed_at=RUN_AT,
    )
    session.add(legacy)
    await session.flush()
    legacy_id = legacy.id

    cards = await persist_scoring_result(
        session,
        shop.id,
        _result(shop.id, computed_at=datetime(2026, 9, 17, 9, 0, tzinfo=UTC)),
    )
    await session.flush()

    rows = await _rows(session, shop.id)
    assert len(rows) == 1, "no twin card beside the legacy row"
    assert rows[0].id == legacy_id
    assert rows[0].subject_type == SUBJECT_TYPE_PRODUCT
    assert rows[0].subject_id == str(top.id)
    assert card_subject_is_bindable(rows[0]) is True
    assert cards == [rows[0]]


@pytest.mark.asyncio
async def test_an_already_actioned_unscoped_card_is_left_alone(session, shop, products):
    """History is not rewritten: only a *standing* candidate is completed.

    A seller who approved a card that named nothing approved exactly that.
    Back-filling a subject onto it afterwards would falsify the record, so the
    scoped card starts its own chain instead.
    """
    top, _tail = products

    actioned = ActionCard(
        id=uuid.uuid4(),
        shop_id=shop.id,
        workflow_key=OPTIMIZE,
        subject_type=SUBJECT_TYPE_UNSCOPED,
        subject_id="",
        revision=1,
        priority=1,
        severity="warning",
        title="Tối ưu sản phẩm",
        description="Pre-#1703 row, already dismissed",
        recommendation_payload="{}",
        status="dismissed",
        dismissed_at=RUN_AT,
        surfaced_at=RUN_AT,
        computed_at=RUN_AT,
    )
    session.add(actioned)
    await session.flush()
    actioned_id = actioned.id

    await persist_scoring_result(
        session,
        shop.id,
        _result(shop.id, computed_at=datetime(2026, 9, 18, 9, 0, tzinfo=UTC)),
    )
    await session.flush()

    rows = await _rows(session, shop.id)
    assert len(rows) == 2
    kept = next(row for row in rows if row.id == actioned_id)
    assert kept.subject_type == SUBJECT_TYPE_UNSCOPED
    assert kept.status == "dismissed"

    scoped = next(row for row in rows if row.id != actioned_id)
    assert scoped.subject_type == SUBJECT_TYPE_PRODUCT
    assert scoped.subject_id == str(top.id)
    assert scoped.revision == 1
    assert scoped.supersedes_card_id is None


@pytest.mark.asyncio
async def test_a_workflow_with_no_resolvable_subject_stays_unscoped(session, shop, products):
    """Every other key in the catalog, and why it is not a bug.

    ``clear_excess_4`` is a Product-subject workflow in ADR-087 decision 5,
    but the producer has no per-product evidence for it and
    ``inventory_items`` is empty on every deployed shop. It emits unscoped
    rather than borrowing the Optimize subject — the top-revenue listing is
    not what "clear your excess stock" is about — and approve refuses it one
    gate earlier anyway, on ``WorkflowNotExecutable``.
    """
    cards = await persist_scoring_result(
        session, shop.id, _result(shop.id, workflow_key="clear_excess_4")
    )
    await session.flush()

    assert len(cards) == 1
    assert cards[0].subject_type == SUBJECT_TYPE_UNSCOPED
    assert cards[0].subject_id == ""
    assert card_subject_is_bindable(cards[0]) is False
