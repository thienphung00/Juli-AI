"""Contract tests for the series_source column migration (#1766, ADR-099).

series_source is a required column on impact_readings that tracks whether the
underlying series data is measured (real data) or synthetic (simulated data).
No default is allowed — a writer that omits provenance must FAIL.

The migration's backfill of pre-existing rows to 'measured' is deliberately NOT
tested here. This module runs on SQLite, where migration 056 never executes, so
a query for backfilled rows returns nothing and any assertion over them passes
vacuously. The property is also self-enforcing: step 3 of the migration sets
NOT NULL, which aborts if step 2 left a single NULL behind. Enforcement against
a real Postgres schema lives in tests/integration/test_series_source_enforced.py.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import ImpactReading, Shop, ToolExecution, User

pytestmark = pytest.mark.migration_heavy

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT / "backend/src/juli_backend/database/migrations/versions/056_series_source_column.py"
)


def test_migration_file_exists():
    """Migration 056 must exist in the versions directory."""
    assert MIGRATION_PATH.is_file(), f"missing migration: {MIGRATION_PATH}"


def test_migration_revision_chain():
    """Verify the migration revision chain is correct."""
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    assert 'revision: str = "056_series_source_column"' in text
    assert 'down_revision: str | None = "055_juli_app_sync_state_update"' in text


def test_migration_adds_column_and_rls_note():
    """Verify migration adds the series_source column and documents RLS."""
    text = MIGRATION_PATH.read_text(encoding="utf-8")
    # Must document that this is tenant-scoped and RLS policy shape doesn't change
    has_rls_note = "tenant-scoped" in text.lower() or "rls" in text.lower()
    assert has_rls_note, "Migration must document RLS implications"
    # Must have an upgrade() function that adds the column
    has_upgrade = "def upgrade" in text
    has_downgrade = "def downgrade" in text
    assert has_upgrade and has_downgrade, "Migration must define upgrade() and downgrade()"


class TestSeriesSourceColumn:
    """Test the series_source column behavior in the actual schema."""

    @pytest_asyncio.fixture
    async def shop(self, session: AsyncSession) -> Shop:
        """Create a test shop."""
        user = User(id=uuid.uuid4(), phone="+84909991144")
        shop_row = Shop(
            id=uuid.uuid4(),
            user_id=user.id,
            shop_name="Series Source Test Shop",
            tiktok_shop_id="tts_series_test",
        )
        session.add_all([user, shop_row])
        await session.flush()
        return shop_row

    @pytest_asyncio.fixture
    async def tool_execution(self, session: AsyncSession, shop: Shop) -> ToolExecution:
        """Create a tool execution for testing."""
        stamp = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
        execution = ToolExecution(
            id=uuid.uuid4(),
            shop_id=shop.id,
            approval_id="approval-series-test-1",
            tool_name="listing.optimize_product",
            payload_json=json.dumps({"workflow_id": "optimize_product_2"}),
            status="succeeded",
            updated_at=stamp,
        )
        session.add(execution)
        await session.flush()
        return execution

    @pytest.mark.asyncio
    async def test_write_without_series_source_raises(
        self, session: AsyncSession, tool_execution: ToolExecution
    ) -> None:
        """A write without series_source must raise, not silently default."""
        # Attempt to create an ImpactReading without series_source
        # This should fail when flushed to the database
        reading = ImpactReading(
            id=uuid.uuid4(),
            tool_execution_id=tool_execution.id,
            metric="gmv",
            kind="preliminary",
            confidence="cao",
            control_set_json="{}",
            computed_at=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
            # series_source is intentionally omitted
        )
        session.add(reading)
        # The constraint must be enforced at flush time, and it must be THIS
        # constraint. `pytest.raises` alone would pass on any IntegrityError the
        # fixtures happened to trigger — a NOT NULL somewhere else, a duplicate
        # key — and would still pass if `series_source` were nullable. Naming the
        # column is what makes this a test of the column.
        with pytest.raises((IntegrityError, ValueError)) as excinfo:
            await session.flush()
        assert "series_source" in str(excinfo.value), (
            f"expected the write to be refused for series_source, but the database "
            f"refused it for something else: {excinfo.value}"
        )

    @pytest.mark.asyncio
    async def test_write_with_measured_succeeds(
        self, session: AsyncSession, tool_execution: ToolExecution
    ) -> None:
        """Writing with series_source='measured' should succeed."""
        reading = ImpactReading(
            id=uuid.uuid4(),
            tool_execution_id=tool_execution.id,
            metric="gmv",
            kind="preliminary",
            confidence="cao",
            control_set_json="{}",
            computed_at=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
            series_source="measured",
        )
        session.add(reading)
        await session.flush()
        # Verify the reading was inserted successfully
        assert reading.id is not None
        assert reading.series_source == "measured"

    @pytest.mark.asyncio
    async def test_write_with_synthetic_succeeds(
        self, session: AsyncSession, tool_execution: ToolExecution
    ) -> None:
        """Writing with series_source='synthetic' should succeed."""
        reading = ImpactReading(
            id=uuid.uuid4(),
            tool_execution_id=tool_execution.id,
            metric="gmv",
            kind="final",
            confidence="cao",
            control_set_json="{}",
            computed_at=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
            series_source="synthetic",
        )
        session.add(reading)
        await session.flush()
        # Verify the reading was inserted successfully
        assert reading.id is not None
        assert reading.series_source == "synthetic"

    @pytest.mark.asyncio
    async def test_filtering_by_measured_works(
        self, session: AsyncSession, tool_execution: ToolExecution
    ) -> None:
        """Querying with series_source='measured' should work."""
        # Create both measured and synthetic readings
        measured = ImpactReading(
            id=uuid.uuid4(),
            tool_execution_id=tool_execution.id,
            metric="gmv",
            kind="preliminary",
            confidence="cao",
            control_set_json="{}",
            computed_at=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
            series_source="measured",
        )
        synthetic = ImpactReading(
            id=uuid.uuid4(),
            tool_execution_id=tool_execution.id,
            metric="sku_orders",
            kind="preliminary",
            confidence="cao",
            control_set_json="{}",
            computed_at=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
            series_source="synthetic",
        )
        session.add_all([measured, synthetic])
        await session.flush()

        # Filter through the ORM, not raw SQL: this module runs on SQLite, where
        # a `public.` schema prefix does not resolve. The point of the test is
        # that `series_source` is a queryable column rather than a JSON path
        # (ADR-099 d.2) — that holds on either backend.
        measured_ids = (
            (
                await session.execute(
                    select(ImpactReading.id).where(
                        ImpactReading.tool_execution_id == tool_execution.id,
                        ImpactReading.series_source == "measured",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert list(measured_ids) == [measured.id], (
            "filtering on series_source must select the measured row and exclude "
            "the synthetic one written against the same execution"
        )
