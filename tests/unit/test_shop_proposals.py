"""ADR-118, migration 109: the manual cycle -- proposals, approvals, executions, results.

On the unit substrate (source text + SQLite):

- the chain: revision id fits ``alembic_version`` (32), sits on 108, the deferred tail
  moved onto it, the additive gate accepts it and its upgrade only adds;
- every model column is created by the migration, the vocabularies match the models and
  the four tables are tenant-direct;
- the state machine: draft → sent → approved → executed → verified, every wrong-state
  step refused, a sent proposal revised (never edited), a recorded approval needs its
  evidence, an item proposal names an item the shop's exports listed;
- the Ops routes: an operator runs one cycle end to end, each step audited; a viewer
  cannot write; another shop's proposal is not found.

The Postgres proof (RLS, grants) is ``tests/integration/test_shop_proposals_db.py``.
Synthetic fixtures only.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP
from juli_backend.models import shop_proposals as models
from juli_backend.models.ops import OpsAuditLog
from juli_backend.models.platform_data import PlatformItem
from juli_backend.services import shop_proposals as cycle
from tests.support.builders import make_shop, make_tenant

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
MIGRATION = MIGRATIONS / "versions/109_shop_proposals.py"
BACKFILL = MIGRATIONS / "deferred/101_write_mode_backfill.py"
MODELS = (
    models.ShopProposal,
    models.ShopProposalApproval,
    models.ShopProposalExecution,
    models.ShopProposalResult,
)
NOW = datetime(2026, 11, 3, 3, 0)


def _module():
    spec = importlib.util.spec_from_file_location("mig109", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# =========================================================================== migration 109


def test_migration_109_fits_alembic_and_the_deferred_tail_moved_onto_it():
    mig = _module()
    assert mig.revision == "109_shop_proposals" and len(mig.revision) <= 32
    assert mig.down_revision == "108_shopee_ops_data"
    # Migration 110 (Ops shop platform) went on 109 and took the deferred tail.
    later = (MIGRATIONS / "versions/110_ops_shop_platform.py").read_text("utf-8")
    assert f'down_revision: str | None = "{mig.revision}"' in later
    assert 'down_revision: str | None = "126_shopee_source_funnel"' in BACKFILL.read_text("utf-8")


def test_the_additive_gate_accepts_migration_109_and_its_upgrade_only_adds():
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION])
    assert [finding.render() for finding in result.findings] == []
    assert result.accepted is True
    body = MIGRATION.read_text("utf-8").split("def upgrade")[1].split("def downgrade")[0]
    for verb in ("op.drop_", "op.alter_column", "UPDATE public", "DELETE FROM", "DROP "):
        assert verb not in body, verb


def test_migration_vocabularies_match_the_models():
    mig = _module()
    for name in (
        "PLATFORMS",
        "KINDS",
        "SUBJECT_TYPES",
        "STATUSES",
        "DECISIONS",
        "APPROVAL_CHANNELS",
        "EXECUTOR_ROLES",
        "EXECUTION_CHANNELS",
        "VERIFIED_HOW",
        "VERDICTS",
    ):
        if name == "STATUSES":  # 117 widened the status CHECK with `planned` (P91 D-6)
            assert (*mig.STATUSES, "planned") == models.STATUSES
            continue
        assert getattr(mig, name) == getattr(models, name), name
    # 111 widened the method CHECK (D81.1): 109's values plus ``self_baseline``.
    spec = importlib.util.spec_from_file_location(
        "mig111", MIGRATION.with_name("111_shopee_keywords.py")
    )
    assert spec is not None and spec.loader is not None
    widened = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(widened)
    assert widened.METHODS_109 == mig.METHODS
    assert widened.METHODS == models.METHODS


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__tablename__)
def test_every_model_column_is_created_by_the_migration(model):
    source = MIGRATION.read_text("utf-8")
    # P91 migration 116 added these two to shop_proposals (tested in test_shopee_reco_p91.py)
    later = {"code", "product_queue"} if model.__tablename__ == "shop_proposals" else set()
    for column in model.__table__.columns.keys():
        if column in later:
            continue
        assert f'sa.Column("{column}"' in source, f"{model.__tablename__}.{column}"


def test_the_four_tables_are_tenant_direct_and_granted_to_the_app():
    mig = _module()
    assert set(mig.TENANT_GRANTS) == {m.__tablename__ for m in MODELS}
    for model in MODELS:
        assert TABLE_CLASSIFICATION_MAP[("public", model.__tablename__)] == "tenant_direct"
    # Append-only tables get no UPDATE; executions only on the verified_* columns.
    assert mig.TENANT_GRANTS["shop_proposal_approvals"][1] == "SELECT, INSERT"
    assert mig.TENANT_GRANTS["shop_proposal_results"][1] == "SELECT, INSERT"
    assert (
        "UPDATE (verified_at, verified_how, verified_state)"
        in (mig.TENANT_GRANTS["shop_proposal_executions"][1])
    )


# =========================================================================== state machine


async def _shopee_shop(session):
    user, shop = await make_tenant(session)
    shop.platform = "shopee"
    session.add(
        PlatformItem(
            id=uuid.uuid4(),
            shop_id=shop.id,
            platform="shopee",
            item_id="1001",
            name="Synthetic item",
            source="file",
            source_rank=2,
            source_version="test",
            captured_at=NOW,
            updated_at=NOW,
        )
    )
    await session.flush()
    return user, shop


def _draft(**overrides):
    values = {
        "cycle": "2026-11 Đợt 1",
        "kind": "title",
        "subject_type": "item",
        "item_id": "1001",
        "subject_label": "Synthetic item",
        "change_before": {"title": "Old title"},
        "change_after": {"title": "New title"},
        "reason": "Adds a niche phrase buyers search.",
    }
    values.update(overrides)
    return cycle.ProposalDraft(**values)


async def test_one_cycle_moves_forward_and_records_who_did_what(session):
    user, shop = await _shopee_shop(session)
    staff = uuid.uuid4()
    proposal = await cycle.create(session, shop.id, "shopee", _draft(), staff_id=staff, now=NOW)
    assert proposal.status == "draft" and proposal.revision == 1

    await cycle.send(session, proposal, now=NOW)
    approval = await cycle.record_approval(
        session,
        proposal,
        decision="approved",
        channel="email",
        decided_at=NOW,
        now=NOW + timedelta(hours=1),
        recorded_by_staff_id=staff,
        evidence_ref="mail:2026-11-03/approval-1",
    )
    assert proposal.status == "approved"
    assert approval.proposal_snapshot["change_after"] == {"title": "New title"}

    execution = await cycle.record_execution(
        session,
        proposal,
        executed_at=NOW + timedelta(hours=2),
        executor_role="client_representative",
        channel="ops",
        now=NOW + timedelta(hours=3),
        recorded_by_staff_id=staff,
    )
    assert proposal.status == "executed" and execution.executed_by_user_id is None

    await cycle.verify_execution(
        session,
        shop.id,
        execution.id,
        verified_how="export_readback",
        verified_state={"title": "New title"},
        verified_at=NOW + timedelta(days=7),
    )
    with pytest.raises(cycle.ProposalError) as again:
        await cycle.verify_execution(
            session,
            shop.id,
            execution.id,
            verified_how="export_readback",
            verified_state={},
            verified_at=NOW + timedelta(days=8),
        )
    assert again.value.status == 409

    [row] = await cycle.list_cycle(session, shop.id, "2026-11 Đợt 1")
    assert row["status"] == "executed"
    assert [a["channel"] for a in row["approvals"]] == ["email"]
    assert row["executions"][0]["verified_how"] == "export_readback"


async def test_wrong_state_steps_are_refused(session):
    _, shop = await _shopee_shop(session)
    proposal = await cycle.create(session, shop.id, "shopee", _draft(), staff_id=None, now=NOW)
    staff = uuid.uuid4()
    with pytest.raises(cycle.ProposalError) as unsent:
        await cycle.record_approval(
            session,
            proposal,
            decision="approved",
            channel="document",
            decided_at=NOW,
            now=NOW,
            recorded_by_staff_id=staff,
            evidence_ref="doc:signed",
        )
    assert unsent.value.status == 409
    with pytest.raises(cycle.ProposalError) as unapproved:
        await cycle.record_execution(
            session,
            proposal,
            executed_at=NOW,
            executor_role="client_representative",
            channel="ops",
            now=NOW,
            recorded_by_staff_id=staff,
        )
    assert unapproved.value.status == 409
    assert proposal.status == "draft"


async def test_a_recorded_approval_needs_evidence_and_an_in_app_one_needs_the_user(session):
    _, shop = await _shopee_shop(session)
    proposal = await cycle.create(session, shop.id, "shopee", _draft(), staff_id=None, now=NOW)
    await cycle.send(session, proposal, now=NOW)
    for kwargs in (
        {"channel": "email", "recorded_by_staff_id": uuid.uuid4(), "evidence_ref": " "},
        {"channel": "in_app"},
    ):
        with pytest.raises(cycle.ProposalError) as refused:
            await cycle.record_approval(
                session, proposal, decision="approved", decided_at=NOW, now=NOW, **kwargs
            )
        assert refused.value.code == cycle.ERROR_INVALID
    assert proposal.status == "sent"


async def test_a_sent_proposal_is_revised_never_edited(session):
    _, shop = await _shopee_shop(session)
    proposal = await cycle.create(session, shop.id, "shopee", _draft(), staff_id=None, now=NOW)
    await cycle.send(session, proposal, now=NOW)
    successor = await cycle.revise(
        session,
        proposal,
        _draft(change_after={"title": "Newer title"}),
        staff_id=None,
        now=NOW,
    )
    assert proposal.status == "superseded"
    assert proposal.change_after == {"title": "New title"}
    assert (successor.status, successor.revision, successor.supersedes_id) == (
        "draft",
        2,
        proposal.id,
    )


async def test_an_item_proposal_must_name_a_listed_item(session):
    _, shop = await _shopee_shop(session)
    with pytest.raises(cycle.ProposalError) as unknown:
        await cycle.create(
            session, shop.id, "shopee", _draft(item_id="9999"), staff_id=None, now=NOW
        )
    assert unknown.value.code == cycle.ERROR_UNKNOWN_ITEM
    shop_wide = await cycle.create(
        session,
        shop.id,
        "shopee",
        _draft(subject_type="shop", item_id=None, kind="voucher", subject_label="Shop"),
        staff_id=None,
        now=NOW,
    )
    assert shop_wide.item_id is None


# =========================================================================== Ops routes


async def _ops_client(session, monkeypatch, role):
    from juli_backend.api.routes.ops import get_ops_user
    from juli_backend.core.security import get_current_user
    from juli_backend.models.ops import OpsStaff
    from tests.support.api import build_app
    from tests.support.builders import make_user

    monkeypatch.setenv("OPS_CF_ACCESS_BYPASS", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    email = f"{role}-{uuid.uuid4().hex[:6]}@app-juli.com"
    user = await make_user(session, email=email)
    session.add(OpsStaff(id=uuid.uuid4(), email=email, role=role, active=True))
    await session.flush()
    app = build_app(session)

    async def current():
        await session.refresh(user)
        return user

    app.dependency_overrides[get_current_user] = current
    app.dependency_overrides[get_ops_user] = current
    return app


async def test_an_operator_runs_one_cycle_through_ops_and_every_step_is_audited(
    session, monkeypatch
):
    from tests.support.api import client_for

    _, shop = await _shopee_shop(session)
    app = await _ops_client(session, monkeypatch, "operator")
    base = f"/v1/ops/shops/{shop.id}/proposals"
    body = {
        "cycle": "2026-11 Đợt 1",
        "kind": "title",
        "subject_type": "item",
        "item_id": "1001",
        "subject_label": "Synthetic item",
        "change_after": {"title": "New title"},
        "reason": "Adds a niche phrase buyers search.",
    }
    async with client_for(app) as client:
        made = await client.post(base, json=body)
        assert made.status_code == 201, made.text
        pid = made.json()["proposal"]["id"]
        assert (await client.post(f"{base}/{pid}/send")).status_code == 200
        approved = await client.post(
            f"{base}/{pid}/approvals",
            json={
                "decision": "approved",
                "channel": "email",
                "evidence_ref": "mail:2026-11-01/approval-1",
                "decided_at": "2026-11-01T09:00:00+07:00",
            },
        )
        assert approved.status_code == 201, approved.text
        executed = await client.post(
            f"{base}/{pid}/executions",
            json={
                "executed_at": "2026-11-01T10:00:00+07:00",
                "executor_role": "client_representative",
            },
        )
        assert executed.status_code == 201, executed.text
        eid = executed.json()["execution_id"]
        verified = await client.post(
            f"{base}/{pid}/executions/{eid}/verify",
            json={
                "verified_how": "export_readback",
                "verified_state": {"title": "New title"},
                "verified_at": "2026-11-02T09:00:00+07:00",
            },
        )
        assert verified.status_code == 200, verified.text
        listed = await client.get(base, params={"cycle": "2026-11 Đợt 1"})
    app.dependency_overrides.clear()

    [row] = listed.json()["proposals"]
    assert row["status"] == "executed"
    # Times arrive with +07:00 and are stored as naive UTC.
    assert row["approvals"][0]["decided_at"] == "2026-11-01T02:00:00Z"
    actions = set(
        (
            await session.scalars(select(OpsAuditLog.action).where(OpsAuditLog.shop_id == shop.id))
        ).all()
    )
    assert {
        "proposal_create",
        "proposal_send",
        "proposal_approval_record",
        "proposal_execution_record",
        "proposal_execution_verify",
    } <= actions


async def test_a_viewer_cannot_write_and_another_shop_sees_nothing(session, monkeypatch):
    from tests.support.api import client_for

    user, shop = await _shopee_shop(session)
    other = await make_shop(session, user)
    proposal = await cycle.create(session, shop.id, "shopee", _draft(), staff_id=None, now=NOW)
    await session.commit()
    app = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(app) as client:
        refused = await client.post(f"/v1/ops/shops/{shop.id}/proposals/{proposal.id}/send")
        listed = await client.get(f"/v1/ops/shops/{other.id}/proposals")
    app.dependency_overrides.clear()
    assert refused.status_code == 403
    assert listed.json()["proposals"] == []
