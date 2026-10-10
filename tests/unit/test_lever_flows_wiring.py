"""AC-10.2 (fast track P10-B): migration 080, the runner's resume seam, the reaper's
per-flow policy, and the Celery route for ``resume_lever_flow``.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from juli_backend.services import lever_flows
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.llm.fake import FakeLLMService
from juli_backend.services.agent.runner.conversation_store import JsonbConversationStore
from juli_backend.services.agent.runner.core import NoExternalWaitError, WorkflowRunner
from juli_backend.services.agent.tools import ToolRegistry
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from tests.support.lever_flows import seed_run, seed_shop

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = REPO_ROOT / "backend/src/juli_backend/database/migrations/versions/080_lever_flows.py"
TABLES = ("run_lever_flows", "run_lever_photos", "lever_calibrations", "run_measurement_finals")


def test_migration_080_is_short_chained_and_tenant_scoped():
    text = MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "080_lever_flows"' in text
    assert len("080_lever_flows") <= 32
    assert 'down_revision: str | None = "079_decision_reasons"' in text
    for table in TABLES:
        assert f'"{table}"' in text
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "app_current_shop_id()" in text
    downgrade = text.split("def downgrade()", 1)[1]
    for table in TABLES:
        assert f'op.drop_table("{table}")' in downgrade

    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP

    for table in TABLES:
        assert TABLE_CLASSIFICATION_MAP[("public", table)] == "tenant_direct"


def test_the_deferred_phone_cleanup_stays_the_tail():
    deferred = (
        REPO_ROOT
        / "backend/src/juli_backend/database/migrations/deferred"
        / "074_users_placeholder_phone_cleanup.py"
    )
    assert 'down_revision: str | None = "081_order_cost_data"' in deferred.read_text(
        encoding="utf-8"
    )


def test_the_reaper_judges_a_lever_flow_wait_by_its_own_policy():
    from juli_backend.workers.tasks import reaper

    photo = SimpleNamespace(id=uuid.uuid4(), workflow_key="optimize_product_2", status="x")
    photo.external_wait_reason = "photo"
    promotion = SimpleNamespace(**{**vars(photo), "external_wait_reason": "seller_action"})
    plain = SimpleNamespace(**{**vars(photo), "external_wait_reason": None})

    assert reaper._policy_for_run(photo).external_wait_timeout_h == 72
    assert reaper._policy_for_run(promotion).external_wait_timeout_h == 14 * 24
    assert reaper._policy_for_run(plain).external_wait_timeout_h is None, (
        "an ordinary Optimize Product run still may not wait externally"
    )


def test_resume_lever_flow_is_routed_to_the_agent_runs_queue():
    from juli_backend.workers.celery_app import celery_app
    from juli_backend.workers.tasks import agent_workflow

    assert celery_app.conf.task_routes["juli_backend.resume_lever_flow"] == {"queue": "agent_runs"}
    assert agent_workflow.resume_lever_flow.name == "juli_backend.resume_lever_flow"


@pytest.mark.asyncio
async def test_resume_after_external_wait_refuses_a_run_that_is_not_waiting(session):
    shop, product = await seed_shop(session)
    run = await seed_run(session, shop, product, status="running")
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    runner = WorkflowRunner(
        llm_service=FakeLLMService(script=[]),
        tool_executor=SimpleNamespace(execute=None),
        event_sink=InMemoryEventSink(),
        conversation_store=JsonbConversationStore(session),
        registry=registry,
        playbook=lever_flows.PHOTO_PLAYBOOK,
    )
    with pytest.raises(NoExternalWaitError):
        await runner.resume_after_external_wait(run.id)
