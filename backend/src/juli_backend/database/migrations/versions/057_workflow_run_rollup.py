"""Add rollup columns to workflow_runs (issue #1653, W8-A / P10-1).

Implements per-run cost and execution rollup: input_tokens, output_tokens, cost_usd,
duration_ms, tool_call_count, rows_affected. All six are populated during the run by
`WorkflowRunner` and persisted to `workflow_runs` on the same `ConversationStore.persist`
call that already stamps status/stop_reason/required_steps_completed.

**Nullable columns (no backfill).** Existing runs pre-date the rollup feature and stay
NULL. New runs (post-migration) populate all six on every terminal exit (or earlier,
depending on the stop_reason path). A run that legitimately does nothing records
tool_call_count=0 and rows_affected=0 while still recording a non-null duration.

**Cost provenance.** cost_usd is computed from the rate in force for that run
(`PRICE_TABLE_USD_PER_MILLION_TOKENS` in `services/agent/llm/config.py`), stamped
at the time of the run, never retroactively updated. A later rate change does not
rewrite history.

**Token accounting.** input_tokens and output_tokens are summed from every
`AssistantTurn.usage` returned by `LLMService.complete()` during the run. No
re-tokenising or estimating; every value comes from the provider's own Usage record.

**Tool call and row accounting.** tool_call_count is the count of tool calls
dispatched to `ToolExecutor.execute`. rows_affected is the count of rows actually
written by the run's writes (defined at the `ToolExecutor` seam, `ToolExecutionLedger`
dispatch boundary, never a vendor-reported count reinterpreted as a row count).

**Duration.** duration_ms is wall-clock time from `started_at` to the terminal (or
paused) event, in milliseconds. This includes any approval wait time (the running_seconds
clock pauses, but duration_ms does not). Across pause/resume, duration_ms accumulates
from the original start_at through the final event.

**Types.**
- input_tokens: Integer, nullable
- output_tokens: Integer, nullable
- cost_usd: Numeric (same scale as money_allocated/money_spent columns already in
  the table), nullable
- duration_ms: Integer, nullable
- tool_call_count: Integer, nullable
- rows_affected: Integer, nullable
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "057_workflow_run_rollup"
down_revision: str | None = "056_series_source_column"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add six nullable rollup columns to workflow_runs."""
    op.add_column(
        "workflow_runs",
        sa.Column("input_tokens", sa.Integer, nullable=True),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("output_tokens", sa.Integer, nullable=True),
    )
    # cost_usd uses Numeric(10, 6) for sub-cent precision on small LLM calls
    # (standard across the codebase for USD values; avoids false-zero rounding)
    op.add_column(
        "workflow_runs",
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=6), nullable=True),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("duration_ms", sa.Integer, nullable=True),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("tool_call_count", sa.Integer, nullable=True),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("rows_affected", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    """Remove the six rollup columns."""
    op.drop_column("workflow_runs", "rows_affected")
    op.drop_column("workflow_runs", "tool_call_count")
    op.drop_column("workflow_runs", "duration_ms")
    op.drop_column("workflow_runs", "cost_usd")
    op.drop_column("workflow_runs", "output_tokens")
    op.drop_column("workflow_runs", "input_tokens")
