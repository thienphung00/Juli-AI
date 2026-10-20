"""``card_events`` writer, outcome mapping and backfill on the SQLite schema (P60-1a).

ADR-107 "Amendment 2026-10-20" §1-§3, §5. The Postgres-only claims (RLS,
append-only grants, the migration round trip) are in
``tests/integration/test_card_events_db.py``; this module proves the mapping
and the idempotency of the code paths, and that a failing log write never
breaks the path it rides on.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from juli_backend.models.card_events import (
    ACTORS,
    CARDLESS_EVENT_TYPES,
    DISMISS_REASON_CODES,
    EVENT_TYPES,
    SINGLE_PER_CARD_EVENT_TYPES,
    SOURCES,
    CardEvent,
)
from juli_backend.models.decision_reasons import DecisionReason
from juli_backend.models.lever_flows import RunLeverFlow, RunMeasurementFinal
from juli_backend.models.models import (
    ActionCard,
    ActionCardApproval,
    ImpactReading,
    ToolExecution,
)
from juli_backend.services import card_events
from juli_backend.services.card_events import keys, outcomes, writer
from juli_backend.services.card_events.backfill import (
    backfill_shop,
    collect_specs,
    match_run,
)
from tests.support.builders import make_product, make_run_event, make_tenant
from tests.support.builders import make_workflow_run as _make_workflow_run

REPO = Path(__file__).resolve().parents[2]
MIGRATION = REPO / "backend/src/juli_backend/database/migrations/versions/095_card_events.py"
DEFERRED = (
    REPO
    / "backend/src/juli_backend/database/migrations/deferred/074_users_placeholder_phone_cleanup.py"
)

NOW = datetime(2026, 10, 20, 3, 0, tzinfo=UTC)


# -- migration <-> model vocabulary (no database) ---------------------------------------


def _migration_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("mig095", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_vocabulary_matches_the_model():
    mig = _migration_module()
    assert mig.EVENT_TYPES == EVENT_TYPES
    assert mig.SINGLE_PER_CARD == SINGLE_PER_CARD_EVENT_TYPES
    assert mig.CARDLESS == CARDLESS_EVENT_TYPES == ("seller_change", "shadow")
    assert mig.ACTORS == ACTORS == ("seller", "juli", "tiktok", "system")
    assert mig.SOURCES == SOURCES == ("live", "backfill")
    assert mig.DISMISS_REASONS == DISMISS_REASON_CODES
    # The five reasons of ADR-107 decision 5, in order, then "no choice".
    assert DISMISS_REASON_CODES == (
        "not_needed",
        "wrong_analysis",
        "not_understood",
        "already_done",
        "later",
        "unspecified",
    )


def test_revision_fits_alembic_and_keeps_the_phone_cleanup_the_tail():
    mig = _migration_module()
    assert mig.revision == "095_card_events" and len(mig.revision) <= 32
    assert mig.down_revision == "094_user_privacy_and_consent"
    body = DEFERRED.read_text("utf-8")
    assert 'down_revision: str | None = "095_card_events"' in body


def test_migration_is_append_only_for_the_app_role():
    text = MIGRATION.read_text("utf-8")
    assert "GRANT SELECT, INSERT ON public.{TABLE} TO {APP_ROLE}" in text
    assert "FOR UPDATE" not in text and "FOR DELETE" not in text
    assert "UPDATE ON" not in text and "DELETE ON" not in text


def test_card_events_is_classified_tenant_direct():
    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP

    assert TABLE_CLASSIFICATION_MAP[("public", "card_events")] == "tenant_direct"


# -- pure mappings ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "stop_reason", "executed"),
    [
        ("completed", "final_response", True),
        ("completed", "confirmation_declined", False),
        ("completed", "concluded_without_changes", False),
        ("failed", "tool_error_unrecoverable", False),
        ("cancelled", "cancelled_by_seller", False),
        ("timed_out", "external_wait_expired", False),
    ],
)
def test_executed_only_for_a_completed_final_response(status, stop_reason, executed):
    assert outcomes.is_executed(status, stop_reason) is executed


@pytest.mark.parametrize(
    ("code", "group"),
    [
        ("confirmation_declined", "seller_declined_confirmation"),
        ("cancelled_by_seller", "seller_declined_confirmation"),
        ("confirmation_expired", "confirmation_expired"),
        ("external_wait_expired", "confirmation_expired"),
        ("audit_rejected", "tiktok_rejected"),
        ("discount_cap_unset", "shop_precondition_missing"),
        ("concluded_without_changes", "nothing_to_change"),
        ("llm_error", "system_error"),
        ("worker_lost", "system_error"),
        (None, "system_error"),
    ],
)
def test_not_executed_groups_follow_decision_6(code, group):
    assert outcomes.not_executed_group(code) == group


def test_keys_name_the_fact_not_the_writer():
    card, run, approval = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert keys.proposed(card) == f"proposed:{card}"
    assert keys.accepted(approval) != keys.accepted(uuid.uuid4())
    # executed and not_executed of one run share one key: a run has one outcome.
    assert keys.run_outcome(run) == f"run_outcome:{run}"
    assert keys.impact("impact_final", run) != keys.impact("impact_preliminary", run)


def test_rules_model_version_is_stable_and_config_sensitive():
    from juli_backend.core.config.decision_emission import DecisionEmissionConfig

    a = writer.rules_model_version(DecisionEmissionConfig())
    assert a == writer.rules_model_version(DecisionEmissionConfig())
    assert a.startswith("rules:ADR-107am2026-10-20:") and len(a.rsplit(":", 1)[1]) == 12
    assert a != writer.rules_model_version(DecisionEmissionConfig(daily_new_cap=99))


def test_match_run_picks_the_run_created_with_the_approval():
    class R:
        def __init__(self, created):
            self.id, self.created_at = uuid.uuid4(), created

    approved = datetime(2026, 10, 1, 8, 0, 0)
    near, far = R(approved + timedelta(seconds=1)), R(approved + timedelta(hours=3))
    assert match_run(approved, [far, near]) == near.id
    assert match_run(approved, [far]) is None


# -- writer on SQLite ---------------------------------------------------------------------


async def make_workflow_run(session, shop, **kw):
    """A run with its own subject ref (SQLite enforces the Postgres-partial active-run unique)."""
    kw.setdefault("subject_ref", uuid.uuid4().hex)
    return await _make_workflow_run(session, shop, **kw)


async def _card(session, shop, product, **kw) -> ActionCard:
    # A workflow key per card: SQLite enforces action_cards' Postgres-partial
    # one-live-card-per-subject unique on every row.
    values = {
        "id": uuid.uuid4(),
        "shop_id": shop.id,
        "workflow_key": f"wk_{uuid.uuid4().hex[:8]}",
        "subject_type": "product",
        "subject_id": str(product.id),
        "revision": 1,
        "priority": 1,
        "severity": "high",
        "title": "Tối ưu mô tả",
        "description": "Mô tả quá ngắn",
        "recommendation_payload": json.dumps({"lever": "description"}),
        "status": "active",
        "metadata_json": json.dumps({"computed_at": NOW.isoformat()}),
        "computed_at": NOW,
    }
    values.update(kw)
    card = ActionCard(**values)
    session.add(card)
    await session.flush()
    return card


async def _events(session, **where) -> list[CardEvent]:
    stmt = select(CardEvent).order_by(CardEvent.occurred_at, CardEvent.event_type)
    for name, value in where.items():
        stmt = stmt.where(getattr(CardEvent, name) == value)
    return list((await session.execute(stmt)).scalars())


class _Emission:
    def __init__(self, card, supersedes=None, suppressed=None):
        self.card, self.supersedes_card_id, self.suppressed_reason = card, supersedes, suppressed


@pytest.mark.asyncio
async def test_emission_writes_proposed_and_superseded_once(session):
    from juli_backend.core.config.decision_emission import DecisionEmissionConfig

    _user, shop = await make_tenant(session)
    product = await make_product(session, shop)
    first = await _card(session, shop, product)
    second = await _card(session, shop, product, revision=2, supersedes_card_id=first.id)
    standing = await _card(session, shop, product, workflow_key="other")
    decisions = [
        _Emission(first),
        _Emission(second, supersedes=first.id),
        _Emission(standing, suppressed="basis_unchanged"),
    ]

    for _ in range(2):  # a retried emission writes nothing twice
        await card_events.record_emissions(
            session, decisions, occurred_at=NOW, config=DecisionEmissionConfig()
        )

    rows = await _events(session)
    assert [(r.card_id, r.event_type) for r in rows] == [
        (first.id, "proposed"),
        (second.id, "proposed"),
        (first.id, "superseded"),
    ]
    proposed = rows[0]
    assert proposed.actor == "juli" and proposed.source == "live"
    assert proposed.subject_id == product.tiktok_product_id  # the TikTok id, not products.id
    assert proposed.payload["card_subject_id"] == str(product.id)
    assert proposed.payload["recommendation_payload"] == {"lever": "description"}
    assert proposed.model_version.startswith("rules:ADR-107am2026-10-20:")
    assert proposed.readiness_level is None and proposed.feature_snapshot_id is None
    assert rows[2].payload["successor_card_id"] == str(second.id)


@pytest.mark.asyncio
async def test_metadata_model_version_wins(session):
    _user, shop = await make_tenant(session)
    product = await make_product(session, shop)
    card = await _card(session, shop, product, metadata_json=json.dumps({"model_version": "m-7"}))
    await card_events.record_proposed(session, card, occurred_at=NOW, model_version="rules:x")
    (row,) = await _events(session)
    assert row.model_version == "m-7"


@pytest.mark.asyncio
async def test_budget_outcome_writes_shown_and_expired(session):
    _user, shop = await make_tenant(session)
    product = await make_product(session, shop)
    shown = await _card(session, shop, product, surfaced_at=NOW)
    gone = await _card(
        session, shop, product, workflow_key="k2", surfaced_at=NOW - timedelta(days=8)
    )
    for _ in range(2):
        await card_events.record_budget_outcome(
            session, newly_surfaced=[shown], expired=[gone], now=NOW
        )
    rows = await _events(session)
    assert sorted((r.card_id, r.event_type, r.actor) for r in rows) == sorted(
        [(shown.id, "shown", "system"), (gone.id, "expired", "system")]
    )


@pytest.mark.asyncio
async def test_accepted_is_once_per_approval_and_dismissed_is_unspecified(session):
    user, shop = await make_tenant(session)
    product = await make_product(session, shop)
    card = await _card(session, shop, product)
    run = await make_workflow_run(session, shop, product=product, action_card_id=card.id)
    approvals = [uuid.uuid4(), uuid.uuid4()]  # approved, run failed (D47.5), approved again
    for approval_id in approvals + approvals[:1]:
        await card_events.record_accepted(
            session,
            card,
            approval_id=approval_id,
            run_id=run.id,
            approved_by_user_id=user.id,
            occurred_at=NOW,
        )
    reason_id = uuid.uuid4()
    for _ in range(2):
        await card_events.record_dismissed(
            session,
            card,
            occurred_at=NOW,
            decision_reason_code="not_convincing",
            decision_reason_id=reason_id,
        )
    accepted = await _events(session, event_type="accepted")
    assert len(accepted) == 2 and {a.workflow_run_id for a in accepted} == {run.id}
    (dismissed,) = await _events(session, event_type="dismissed")
    assert dismissed.reason_code == "unspecified" and dismissed.actor == "seller"
    assert dismissed.payload == {
        "decision_reason_code": "not_convincing",
        "decision_reason_id": str(reason_id),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "stop_reason", "event_type", "group"),
    [
        ("completed", "final_response", "executed", None),
        ("completed", "confirmation_declined", "not_executed", "seller_declined_confirmation"),
        ("failed", "llm_error", "not_executed", "system_error"),
    ],
)
async def test_run_outcome(session, status, stop_reason, event_type, group):
    _user, shop = await make_tenant(session)
    product = await make_product(session, shop)
    card = await _card(session, shop, product)
    run = await make_workflow_run(
        session, shop, product=product, action_card_id=card.id, status=status
    )
    for _ in range(2):
        await card_events.record_run_outcome(
            session, run, status=status, stop_reason=stop_reason, occurred_at=NOW
        )
    (row,) = await _events(session)
    assert row.event_type == event_type and row.workflow_run_id == run.id
    assert row.payload["stop_reason"] == stop_reason
    assert row.payload.get("group") == group


@pytest.mark.asyncio
async def test_run_outcome_skips_non_terminal_cardless_and_failed_reverts(session):
    _user, shop = await make_tenant(session)
    product = await make_product(session, shop)
    card = await _card(session, shop, product)
    original = await make_workflow_run(
        session, shop, product=product, action_card_id=card.id, status="completed"
    )
    cardless = await make_workflow_run(session, shop, product=product, status="completed")
    revert = await make_workflow_run(
        session,
        shop,
        product=product,
        action_card_id=card.id,
        reverts_run_id=original.id,
        status="failed",
    )
    await card_events.record_run_outcome(
        session, original, status="waiting_approval", stop_reason=None
    )
    await card_events.record_run_outcome(
        session, cardless, status="completed", stop_reason="final_response"
    )
    await card_events.record_run_outcome(session, revert, status="failed", stop_reason="llm_error")
    assert await _events(session) == []

    await card_events.record_run_outcome(
        session, revert, status="completed", stop_reason="final_response", occurred_at=NOW
    )
    (row,) = await _events(session)
    assert row.event_type == "reverted" and row.card_id == card.id
    assert row.payload["reverts_run_id"] == str(original.id)


async def _execution(session, shop, run) -> ToolExecution:
    execution = ToolExecution(
        id=uuid.uuid4(),
        shop_id=shop.id,
        workflow_run_id=run.id,
        approval_id=f"approval-{run.id}",
        tool_name="update_product_listing",
        status="succeeded",
        payload_json="{}",
    )
    session.add(execution)
    await session.flush()
    return execution


def _reading(execution, run, kind, metric, computed_at=NOW) -> ImpactReading:
    return ImpactReading(
        id=uuid.uuid4(),
        run_id=run.id,
        tool_execution_id=execution.id,
        metric=metric,
        kind=kind,
        pre=Decimal("10"),
        post=Decimal("12"),
        expected=Decimal("10"),
        incremental=Decimal("2"),
        impact_pct=Decimal("0.2"),
        confidence="trung_binh",
        control_set_json="{}",
        computed_at=computed_at,
        series_source="measured",
    )


@pytest.mark.asyncio
async def test_impact_readings_then_final_from_measurement_keeps_the_first(session):
    _user, shop = await make_tenant(session)
    product = await make_product(session, shop)
    card = await _card(session, shop, product)
    run = await make_workflow_run(
        session, shop, product=product, action_card_id=card.id, status="completed"
    )
    execution = await _execution(session, shop, run)
    session.add_all(
        [_reading(execution, run, "preliminary", "gmv"), _reading(execution, run, "final", "gmv")]
    )
    await session.flush()
    for kind in ("preliminary", "final", "final"):
        await card_events.record_impact_readings(session, run_id=run.id, kind=kind, occurred_at=NOW)
    final = RunMeasurementFinal(
        id=uuid.uuid4(), shop_id=shop.id, workflow_run_id=run.id, lever="description", label="dat"
    )
    session.add(final)
    await session.flush()
    await card_events.record_measurement_final(session, final)

    rows = await _events(session)
    assert [r.event_type for r in rows] == ["impact_final", "impact_preliminary"]
    final_row = next(r for r in rows if r.event_type == "impact_final")
    assert final_row.payload["source_table"] == "impact_readings"
    assert final_row.payload["readings"][0]["metric"] == "gmv"


@pytest.mark.asyncio
async def test_a_failing_log_write_never_raises(session, monkeypatch, caplog):
    _user, shop = await make_tenant(session)
    product = await make_product(session, shop)
    card = await _card(session, shop, product)

    async def boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(writer, "insert_event", boom)
    await card_events.record_proposed(session, card, occurred_at=NOW, model_version="rules:x")
    await card_events.record_dismissed(session, card, occurred_at=NOW)
    assert "card_event_write_failed" in caplog.text
    assert await session.get(ActionCard, card.id) is not None


@pytest.mark.asyncio
async def test_insert_event_enforces_the_check_on_card_id(session):
    from sqlalchemy.exc import IntegrityError

    _user, shop = await make_tenant(session)
    spec = writer.EventSpec(
        shop_id=shop.id,
        card_id=None,
        event_type="accepted",
        actor="seller",
        occurred_at=NOW,
        workflow_key="optimize_product_2",
        subject_type="product",
        subject_id="tt-1",
        dedup_key="x",
    )
    with pytest.raises(IntegrityError):
        await writer.insert_event(session, spec)
    await session.rollback()


# -- backfill on SQLite -------------------------------------------------------------------


async def _seed_history(session):
    """One shop's past: a superseded card, an approved + executed + measured one,
    a rejected one, a declined one, a reverted run."""
    user, shop = await make_tenant(session)
    product = await make_product(session, shop)
    old = await _card(session, shop, product, status="superseded")
    live = await _card(
        session,
        shop,
        product,
        revision=2,
        supersedes_card_id=old.id,
        status="approved",
        surfaced_at=NOW,
        approved_at=NOW + timedelta(hours=1),
    )
    rejected = await _card(
        session,
        shop,
        product,
        workflow_key="content_video",
        status="dismissed",
        dismissed_at=NOW + timedelta(hours=2),
    )
    declined = await _card(
        session,
        shop,
        product,
        workflow_key="price",
        status="dismissed",
        dismissed_at=NOW + timedelta(hours=3),
    )
    approved_at = (NOW + timedelta(hours=1)).replace(tzinfo=None)
    session.add(
        ActionCardApproval(
            id=uuid.uuid4(),
            action_card_id=live.id,
            approved_by_user_id=user.id,
            approved_at=approved_at,
            card_snapshot={},
        )
    )
    run = await make_workflow_run(
        session,
        shop,
        product=product,
        action_card_id=live.id,
        status="completed",
        stop_reason="final_response",
        created_at=approved_at,
        completed_at=NOW + timedelta(hours=2),
    )
    await make_run_event(session, run.id, 0, event_type="workflow.status")
    await make_run_event(
        session,
        run.id,
        1,
        event_type="workflow.completed",
        payload={"status": "completed", "stop_reason": "final_response"},
    )
    session.add(
        RunLeverFlow(
            id=uuid.uuid4(),
            shop_id=shop.id,
            workflow_run_id=run.id,
            kind="photo",
            lever="cover_image",
            applied_at=(NOW + timedelta(hours=5)).replace(tzinfo=None),
        )
    )
    execution = await _execution(session, shop, run)
    session.add(_reading(execution, run, "preliminary", "ctr", NOW + timedelta(days=7)))
    session.add(
        RunMeasurementFinal(
            id=uuid.uuid4(),
            shop_id=shop.id,
            workflow_run_id=run.id,
            lever="cover_image",
            label="gan_dat",
            computed_at=(NOW + timedelta(days=14)).replace(tzinfo=None),
        )
    )
    revert = await make_workflow_run(
        session,
        shop,
        product=product,
        action_card_id=live.id,
        reverts_run_id=run.id,
        status="completed",
        stop_reason="final_response",
        completed_at=NOW + timedelta(days=8),
    )
    declined_run = await make_workflow_run(
        session,
        shop,
        product=product,
        action_card_id=declined.id,
        status="completed",
        stop_reason="confirmation_declined",
        completed_at=NOW + timedelta(hours=3),
    )
    for action, card, reason in (
        ("reject", rejected, "not_convincing"),
        ("decline", declined, "tone"),
    ):
        session.add(
            DecisionReason(
                id=uuid.uuid4(),
                shop_id=shop.id,
                action=action,
                reason_code=reason,
                action_card_id=card.id,
                cooldown_until=(NOW + timedelta(days=7)).replace(tzinfo=None),
            )
        )
    await session.flush()
    return (
        shop,
        product,
        {"old": old, "live": live, "rejected": rejected, "declined": declined},
        {
            "run": run,
            "revert": revert,
            "declined": declined_run,
        },
    )


@pytest.mark.asyncio
async def test_backfill_reconstructs_the_marked_events(session):
    shop, product, cards, runs = await _seed_history(session)
    report = await backfill_shop(session, shop.id)

    got = {(r.card_id, r.event_type) for r in await _events(session)}
    live, old = cards["live"].id, cards["old"].id
    assert got == {
        (old, "proposed"),
        (cards["live"].id, "proposed"),
        (cards["rejected"].id, "proposed"),
        (cards["declined"].id, "proposed"),
        (old, "superseded"),
        (live, "shown"),
        (live, "accepted"),
        (
            cards["rejected"].id,
            "dismissed",
        ),  # not the declined card: a run decline is not a dismissal
        (live, "executed"),
        (live, "reverted"),
        (cards["declined"].id, "not_executed"),
        (live, "impact_preliminary"),
        (live, "impact_final"),
    }
    rows = await _events(session)
    assert {r.source for r in rows} == {"backfill"}
    proposed = next(r for r in rows if r.event_type == "proposed" and r.card_id == live)
    assert proposed.model_version == "unknown" and proposed.readiness_level is None
    assert proposed.subject_id == product.tiktok_product_id
    accepted = next(r for r in rows if r.event_type == "accepted")
    assert accepted.workflow_run_id == runs["run"].id
    executed = next(r for r in rows if r.event_type == "executed")
    assert executed.payload["applied_at"].startswith("2026-10-20T08:00")  # the lever flow's
    dismissed = next(r for r in rows if r.event_type == "dismissed")
    assert dismissed.reason_code == "unspecified"
    assert dismissed.payload["decision_reason_code"] == "not_convincing"
    final = next(r for r in rows if r.event_type == "impact_final")
    assert final.payload["source_table"] == "run_measurement_finals"
    assert final.payload["label"] == "gan_dat"
    assert report.inserted == report.considered
    assert sum(report.inserted.values()) == len(rows) == 13


@pytest.mark.asyncio
async def test_backfill_twice_inserts_nothing_new(session):
    shop, _product, _cards, _runs = await _seed_history(session)
    first = await backfill_shop(session, shop.id)
    count = (await session.execute(select(func.count()).select_from(CardEvent))).scalar_one()
    second = await backfill_shop(session, shop.id)
    assert (
        await session.execute(select(func.count()).select_from(CardEvent))
    ).scalar_one() == count
    assert sum(first.inserted.values()) == count and second.inserted == {}
    assert second.considered == first.considered


@pytest.mark.asyncio
async def test_backfill_after_live_writes_keeps_the_live_rows(session):
    shop, _product, cards, _runs = await _seed_history(session)
    await card_events.record_proposed(
        session, cards["live"], occurred_at=NOW, model_version="rules:live"
    )
    await backfill_shop(session, shop.id)
    (row,) = await _events(session, event_type="proposed", card_id=cards["live"].id)
    assert row.source == "live" and row.model_version == "rules:live"


@pytest.mark.asyncio
async def test_backfill_reads_only_its_own_shop(session):
    shop, _product, _cards, _runs = await _seed_history(session)
    _user, other = await make_tenant(session)
    assert await collect_specs(session, other.id) == []
    await backfill_shop(session, other.id)
    assert await _events(session) == []
    await backfill_shop(session, shop.id)
    assert {r.shop_id for r in await _events(session)} == {shop.id}
