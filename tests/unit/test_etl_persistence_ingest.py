"""MMU-9a — ETL ingest persistence public surface (#558)."""
# ruff: noqa: E402

from __future__ import annotations

import inspect
import json
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import get_type_hints

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
SCRIPTS_DIR = REPO_ROOT / "agent-runtime" / "scripts"
sys.path.insert(0, str(CI_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

from build_runtime import load_simple_yaml  # noqa: E402
from check_ownership_registry import discover_orm_table_names  # noqa: E402

import juli_backend.database as database_pkg
from juli_backend.database import Base as DatabaseBase
from juli_backend.database import get_session, init_session_factory
from juli_backend.models.models import ProcessedEvent as LegacyProcessedEvent
from juli_backend.models.models import Shop, User
from juli_backend.orm_base import Base as SharedBase
from juli_backend.repositories.repos import ProcessedEventsRepo as LegacyProcessedEventsRepo
from juli_backend.services.etl import consumer as etl_consumer
from juli_backend.services.etl.persistence.ingest import (
    ProcessedEvent,
    ProcessedEventsRepo,
)
from juli_backend.services.etl.persistence.ingest import model as ingest_model
from juli_backend.services.etl.persistence.ingest import repo as ingest_repo

SCOPE_ALIGNMENT_PATH = REPO_ROOT / "tests" / "fixtures" / "mmu9" / "scope-alignment-issue-558.md"
IMPLEMENTATION_ARTIFACT_PATH = (
    REPO_ROOT / "agent-runtime" / "artifacts" / "implementations" / "implementation-issue-558.json"
)
SLICE_ROUTING_PATH = REPO_ROOT / "agent-runtime" / "config" / "slice-routing.yml"
AGENT_RUNTIME_CONFIG_PATH = REPO_ROOT / "agent-runtime" / "config" / "agent-runtime.config.yml"

APPROVAL_COMMENT_ID = "5099566733"
KICKOFF_COMMENT_ID = "5099545543"
APPROVAL_MARKER = "MMU-9 APPROVED"


def _parse_utc_timestamp(raw: str) -> datetime:
    normalized = raw.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(UTC)


def test_written_split_plan_approved_before_code_move_issue_558() -> None:
    """AC1 — factual HITL approval precedes implementation start (scope-alignment source)."""
    scope_text = SCOPE_ALIGNMENT_PATH.read_text(encoding="utf-8")
    implementation = json.loads(IMPLEMENTATION_ARTIFACT_PATH.read_text(encoding="utf-8"))

    assert APPROVAL_MARKER in scope_text
    assert APPROVAL_COMMENT_ID in scope_text
    assert KICKOFF_COMMENT_ID in scope_text
    assert "Written split plan" in scope_text or "written split plan" in scope_text.lower()

    approval_match = re.search(
        rf"{APPROVAL_COMMENT_ID}\).*?posted (\d{{4}}-\d{{2}}-\d{{2}}T\d{{2}}:\d{{2}}:\d{{2}}Z)",
        scope_text,
        flags=re.DOTALL,
    )
    assert approval_match is not None, "approval timestamp missing from scope-alignment AC1 record"

    approval_at = _parse_utc_timestamp(approval_match.group(1))
    implementation_started_at = _parse_utc_timestamp(implementation["startedAt"])
    assert approval_at < implementation_started_at


def test_at_least_one_domain_moved_end_to_end_imports_updated() -> None:
    """AC2 — ETL ingest domain owns ProcessedEvent/Repo with updated import paths."""
    assert ProcessedEvent.__tablename__ == "processed_events"
    assert ProcessedEvent is LegacyProcessedEvent
    assert ProcessedEventsRepo is LegacyProcessedEventsRepo
    assert ProcessedEvent.__module__ == "juli_backend.services.etl.persistence.ingest.model"
    assert ProcessedEventsRepo.__module__ == "juli_backend.services.etl.persistence.ingest.repo"

    consumer_source = inspect.getsource(etl_consumer)
    assert (
        "from juli_backend.services.etl.persistence.ingest import ProcessedEventsRepo"
        in consumer_source
    )

    assert (
        database_pkg._LAZY_EXPORTS["ProcessedEvent"]
        == "juli_backend.services.etl.persistence.ingest"
    )
    assert (
        database_pkg._LAZY_EXPORTS["ProcessedEventsRepo"]
        == "juli_backend.services.etl.persistence.ingest"
    )


def test_ownership_registry_discovers_moved_processed_events_table() -> None:
    tables = discover_orm_table_names()
    assert "processed_events" in tables


def test_shared_session_base_remain_in_database_shared_infra() -> None:
    """AC3 — moved ingest persistence still uses Database shared Base/session primitives."""
    assert DatabaseBase is SharedBase
    assert issubclass(ProcessedEvent, SharedBase)
    assert ProcessedEvent.__table__.metadata is SharedBase.metadata

    session_hint = get_type_hints(ProcessedEventsRepo.__init__)["session"]
    assert session_hint is AsyncSession

    assert callable(get_session)
    assert callable(init_session_factory)


@pytest.mark.asyncio
async def test_processed_events_repo_claim_idempotency_contract(session, user_id) -> None:
    user = User(id=user_id, phone="+84901111111")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="Ingest Shop",
        tiktok_shop_id="7000000000999",
    )
    session.add_all([user, shop])
    await session.flush()

    repo = ProcessedEventsRepo(session)
    event_id = "evt-mmu9a-1"

    assert await repo.claim(event_id=event_id, shop_id=shop.id) is True
    assert await repo.claim(event_id=event_id, shop_id=shop.id) is False


def test_no_polyglot_db_single_deployable_shared_postgres() -> None:
    """AC4 — moved ingest persistence stays on shared Base + AsyncSession only."""
    assert issubclass(ProcessedEvent, SharedBase)
    assert ProcessedEvent.__table__.metadata is SharedBase.metadata

    session_hint = get_type_hints(ProcessedEventsRepo.__init__)["session"]
    assert session_hint is AsyncSession

    combined_source = inspect.getsource(ingest_model) + inspect.getsource(ingest_repo)
    forbidden_wiring = (
        "create_engine",
        "create_async_engine",
        "redis",
        "MongoClient",
        "boto3",
        "DATABASE_URL",
    )
    for token in forbidden_wiring:
        assert token not in combined_source, f"unexpected alternate datastore wiring: {token}"


def test_remaining_god_file_shrinkage_tracked_in_follow_up_slices() -> None:
    """AC5 — remaining models/repos god-file shrinkage tracked under parent #550 slices."""
    scope_text = SCOPE_ALIGNMENT_PATH.read_text(encoding="utf-8")
    implementation = json.loads(IMPLEMENTATION_ARTIFACT_PATH.read_text(encoding="utf-8"))

    slice_routing = load_simple_yaml(SLICE_ROUTING_PATH)
    mmu9 = slice_routing["MMU-9"]
    required_modules = mmu9["requiredModules"]
    assert "backend/src/juli_backend/models/models.py" in required_modules
    assert "backend/src/juli_backend/repositories/repos.py" in required_modules

    runtime_config = load_simple_yaml(AGENT_RUNTIME_CONFIG_PATH)
    child_slices_raw = runtime_config["workflow_prompt_cache"]["epicRegistry"]["550"]["childSlices"]
    child_slices = {str(key).strip('"'): value for key, value in child_slices_raw.items()}
    follow_up_slice_ids = {"MMU-10", "MMU-11", "MMU-12", "MMU-13", "MMU-14", "MMU-15"}
    assert follow_up_slice_ids.issubset(set(child_slices.values()))
    assert child_slices["558"] == "MMU-9"

    assumptions_blob = " ".join(implementation["assumptions"]).lower()
    assert "follow-up" in assumptions_blob or "god" in assumptions_blob
    assert "follow-up" in scope_text.lower() or "Follow-up" in scope_text
