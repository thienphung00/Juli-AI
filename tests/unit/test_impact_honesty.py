"""Impact read-side honesty rule — ADR-085 decision 8 (#1338).

#1226 forbids closing the gate by "producing a suppressed reading and calling
it a reading." Make that structural: no surface, report or query that answers
"what was the impact" may count a suppressed or confounded row as a reading.

With ONLY suppressed rows present, the gate-closing query returns ZERO rows.
Asserted directly, because this is the exact dishonesty #1226 names by name.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import (
    ImpactReading,
    Shop,
    ToolExecution,
    User,
)
from juli_backend.services.operations.impact_honesty import (
    list_impact_readings_honest,
)


@pytest_asyncio.fixture
async def shop(session: AsyncSession) -> Shop:
    """Create a test shop."""
    user = User(id=uuid.uuid4(), phone="+84909991144")
    shop_row = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Honesty Test Shop",
        tiktok_shop_id="tts_honesty_test",
    )
    session.add_all([user, shop_row])
    await session.flush()
    return shop_row


@pytest_asyncio.fixture
async def tool_execution(session: AsyncSession, shop: Shop) -> ToolExecution:
    """Create a tool execution."""
    stamp = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    execution = ToolExecution(
        id=uuid.uuid4(),
        shop_id=shop.id,
        approval_id="approval-test-1",
        tool_name="listing.optimize_product",
        payload_json=json.dumps({"workflow_id": "optimize_product_2"}),
        status="succeeded",
        updated_at=stamp,
    )
    session.add(execution)
    await session.flush()
    return execution


class TestHonestyRule:
    """Read-side honesty: suppressed/confounded rows are not counted as readings."""

    @pytest.mark.asyncio
    async def test_query_with_only_suppressed_returns_zero_rows(
        self, session: AsyncSession, shop: Shop, tool_execution: ToolExecution
    ) -> None:
        """Gate-closing query returns zero rows with only suppressed readings."""
        # Seed only suppressed readings
        for metric in ["gmv", "sku_orders", "impressions"]:
            row = ImpactReading(
                id=uuid.uuid4(),
                tool_execution_id=tool_execution.id,
                metric=metric,
                kind="preliminary",
                pre=None,
                post=None,
                expected=None,
                incremental=None,
                impact_pct=None,
                confidence="suppressed",
                control_set_json="{}",
                computed_at=datetime.now(UTC),
            )
            session.add(row)
        await session.flush()

        # The query should return zero rows for honest reading count
        result = await list_impact_readings_honest(session, tool_execution.id)
        assert len(result) == 0  # Zero rows counted as actual readings

    @pytest.mark.asyncio
    async def test_query_with_only_confounded_returns_zero_rows(
        self, session: AsyncSession, shop: Shop, tool_execution: ToolExecution
    ) -> None:
        """Gate-closing query returns zero rows with only confounded readings."""
        # Seed only confounded readings
        for metric in ["gmv", "sku_orders"]:
            row = ImpactReading(
                id=uuid.uuid4(),
                tool_execution_id=tool_execution.id,
                metric=metric,
                kind="preliminary",
                pre=Decimal("100.00"),
                post=Decimal("120.00"),
                expected=Decimal("105.00"),
                incremental=Decimal("15.00"),
                impact_pct=Decimal("0.142857"),
                confidence="confounded",
                control_set_json="{}",
                computed_at=datetime.now(UTC),
            )
            session.add(row)
        await session.flush()

        # The query should return zero rows (confounded is not a reading)
        result = await list_impact_readings_honest(session, tool_execution.id)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_query_excludes_suppressed_keeps_real_readings(
        self, session: AsyncSession, shop: Shop, tool_execution: ToolExecution
    ) -> None:
        """Query excludes suppressed rows but includes real readings."""
        # Seed a mix: one cao, one suppressed
        cao_row = ImpactReading(
            id=uuid.uuid4(),
            tool_execution_id=tool_execution.id,
            metric="gmv",
            kind="preliminary",
            pre=Decimal("100.00"),
            post=Decimal("200.00"),
            expected=Decimal("110.00"),
            incremental=Decimal("90.00"),
            impact_pct=Decimal("0.818182"),
            confidence="cao",
            control_set_json="{}",
            computed_at=datetime.now(UTC),
        )
        suppressed_row = ImpactReading(
            id=uuid.uuid4(),
            tool_execution_id=tool_execution.id,
            metric="sku_orders",
            kind="preliminary",
            pre=None,
            post=None,
            expected=None,
            incremental=None,
            impact_pct=None,
            confidence="suppressed",
            control_set_json="{}",
            computed_at=datetime.now(UTC),
        )
        session.add_all([cao_row, suppressed_row])
        await session.flush()

        # The query should return only the cao reading
        result = await list_impact_readings_honest(session, tool_execution.id)
        assert len(result) == 1
        assert result[0].metric == "gmv"
        assert result[0].confidence == "cao"

    @pytest.mark.asyncio
    async def test_confounded_distinguishable_from_suppressed(
        self, session: AsyncSession, shop: Shop, tool_execution: ToolExecution
    ) -> None:
        """confounded rows are distinguishable from suppressed at read surface."""
        # Seed one of each
        suppressed_row = ImpactReading(
            id=uuid.uuid4(),
            tool_execution_id=tool_execution.id,
            metric="gmv",
            kind="preliminary",
            pre=None,
            post=None,
            expected=None,
            incremental=None,
            impact_pct=None,
            confidence="suppressed",
            control_set_json="{}",
            computed_at=datetime.now(UTC),
        )
        confounded_row = ImpactReading(
            id=uuid.uuid4(),
            tool_execution_id=tool_execution.id,
            metric="sku_orders",
            kind="preliminary",
            pre=Decimal("10.00"),
            post=Decimal("15.00"),
            expected=Decimal("11.00"),
            incremental=Decimal("4.00"),
            impact_pct=Decimal("0.363636"),
            confidence="confounded",
            control_set_json="{}",
            computed_at=datetime.now(UTC),
        )
        session.add_all([suppressed_row, confounded_row])
        await session.flush()

        # Both should be filtered out of "readings"
        result = await list_impact_readings_honest(session, tool_execution.id)
        assert len(result) == 0  # Neither counted as readings

        # But they should be distinguishable elsewhere (e.g., in a detailed view)
        # This test just confirms they're not counted; another surface would show them labeled.

    @pytest.mark.asyncio
    async def test_all_tier_levels_included_except_suppressed_confounded(
        self, session: AsyncSession, shop: Shop, tool_execution: ToolExecution
    ) -> None:
        """All real confidence tiers (cao/trung_binh/thap) are included."""
        tiers = ["cao", "trung_binh", "thap"]
        for i, tier in enumerate(tiers):
            row = ImpactReading(
                id=uuid.uuid4(),
                tool_execution_id=tool_execution.id,
                metric=f"metric_{i}",
                kind="preliminary",
                pre=Decimal("100.00"),
                post=Decimal("120.00"),
                expected=Decimal("105.00"),
                incremental=Decimal("15.00"),
                impact_pct=Decimal("0.142857"),
                confidence=tier,
                control_set_json="{}",
                computed_at=datetime.now(UTC),
            )
            session.add(row)
        await session.flush()

        # All should be included
        result = await list_impact_readings_honest(session, tool_execution.id)
        assert len(result) == 3
        result_tiers = {r.confidence for r in result}
        assert result_tiers == {"cao", "trung_binh", "thap"}
