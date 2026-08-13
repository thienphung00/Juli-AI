"""Daily impact-reader beat task orchestration — ADR-077 decision 5 (#1044).

`services.impact` (#1041-#1043) is a pure library: it accepts already-built
`RawDailyRecord` series, `ControlCandidate`s, and a `confounded: bool`, and
never touches the database or the wall clock. This package is the I/O layer
that builds those inputs from `ToolExecution`/`AnalyticsPerformanceInterval`/
`Product` rows, calls `services.impact`, and persists `ImpactReading` rows —
the daily beat task itself lives in `workers/tasks/impact_reader.py`.
"""

from __future__ import annotations

from juli_backend.workers.impact_reader.pipeline import (
    ImpactReaderRunResult,
    run_daily_impact_reader,
)

__all__ = ["ImpactReaderRunResult", "run_daily_impact_reader"]
