"""OpenAI call log ``llm_call_log`` (NDA work, PR 4).

Revision ID: 105_llm_call_log
Revises: 104_shop_pseudonym_keys
Create Date: 2026-10-26

DECISIONS D76; ADR-116 §5 (grill log D6 revised).

WHAT IT ADDS. One tenant table, append-only like 095's ``card_events``: one row per
OpenAI call attempt the gate (``services/llm_gate``) sees -- ``sent``, ``refused``
before any HTTP, or ``error`` on the wire:

- ``shop_id``, ``purpose``, ``model``, ``endpoint``, ``project``, ``input_tokens``,
  ``output_tokens``, ``request_id`` (OpenAI's ``x-request-id``), ``status``,
  ``refusal_reason`` (set exactly when ``status = 'refused'``), ``created_at``.
  Metadata only: no prompt, no output.
- index (``shop_id``, ``created_at``) for the per-shop monthly usage read;
- RLS through ``app_current_shop_id()``, a SELECT and an INSERT policy, and
  ``juli_app`` granted SELECT, INSERT only -- no UPDATE / DELETE grant and no policy
  for them. Rows go with the shop (the privacy purge deletes as the owner).

EXPAND-ONLY AND REVERSIBLE. A new table, its policies and its grant; no data change.
``downgrade`` drops it. The deferred write-mode backfill (and the phone cleanup under
it) is re-parented onto this revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "105_llm_call_log"
down_revision: str | None = "104_shop_pseudonym_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
TABLE = "llm_call_log"

#: Written out rather than imported from the model: a migration must not change
#: when the model does. ``tests/unit/test_llm_gate.py`` pins the two equal.
STATUSES = ("sent", "refused", "error")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("endpoint", sa.String(length=64), nullable=False),
        sa.Column("project", sa.String(length=64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("refusal_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_llm_call_log"),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], name="fk_llm_call_log_shop"),
        sa.CheckConstraint(f"status IN ({_in(STATUSES)})", name="ck_llm_call_log_status"),
        sa.CheckConstraint(
            "(status = 'refused') = (refusal_reason IS NOT NULL)",
            name="ck_llm_call_log_refusal_reason",
        ),
    )
    op.create_index("ix_llm_call_log_shop_created", TABLE, ["shop_id", "created_at"])

    op.execute(f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {TABLE}_select_public ON public.{TABLE} "
        "FOR SELECT USING (shop_id = app_current_shop_id())"
    )
    op.execute(
        f"CREATE POLICY {TABLE}_insert_public ON public.{TABLE} "
        "FOR INSERT WITH CHECK (shop_id = app_current_shop_id())"
    )
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT ON public.{TABLE} TO {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - table and role are fixed module constants


def downgrade() -> None:
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'REVOKE ALL ON public.{TABLE} FROM {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - table and role are fixed module constants
    op.drop_index("ix_llm_call_log_shop_created", table_name=TABLE)
    op.drop_table(TABLE)
