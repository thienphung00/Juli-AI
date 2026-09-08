"""Model-level tests for series_source column (#1766, ADR-099).

These tests verify the model definition enforces the series_source contract
at the ORM level.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from juli_backend.models.models import ImpactReading


class TestSeriesSourceModel:
    """Test the series_source field in the ImpactReading model."""

    def test_model_has_series_source_field(self) -> None:
        """ImpactReading model must have a series_source field."""
        assert hasattr(ImpactReading, "series_source")

    def test_create_reading_with_measured_source(self) -> None:
        """Can create a reading with series_source='measured'."""
        reading = ImpactReading(
            id=uuid.uuid4(),
            tool_execution_id=uuid.uuid4(),
            metric="gmv",
            kind="preliminary",
            confidence="cao",
            control_set_json="{}",
            computed_at=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
            series_source="measured",
        )
        assert reading.series_source == "measured"

    def test_create_reading_with_synthetic_source(self) -> None:
        """Can create a reading with series_source='synthetic'."""
        reading = ImpactReading(
            id=uuid.uuid4(),
            tool_execution_id=uuid.uuid4(),
            metric="gmv",
            kind="preliminary",
            confidence="cao",
            control_set_json="{}",
            computed_at=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
            series_source="synthetic",
        )
        assert reading.series_source == "synthetic"

    def test_check_constraint_is_defined(self) -> None:
        """The series_source check constraint must be in __table_args__."""
        from sqlalchemy import CheckConstraint

        # Find the check constraint in table args
        check_constraints = [
            arg for arg in ImpactReading.__table_args__ if isinstance(arg, CheckConstraint)
        ]
        # Should have at least 3: kind, confidence, and series_source
        assert len(check_constraints) >= 3

        # Find series_source constraint
        series_source_constraint = None
        for constraint in check_constraints:
            if constraint.name == "ck_impact_readings_series_source":
                series_source_constraint = constraint
                break

        assert series_source_constraint is not None, "series_source check constraint not found"
