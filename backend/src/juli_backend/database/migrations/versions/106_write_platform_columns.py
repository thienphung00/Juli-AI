"""``platform`` + ``platform_product_id`` on the two production-write tables (NDA work, PR 5).

Revision ID: 106_write_platform_columns
Revises: 105_llm_call_log
Create Date: 2026-10-26

DECISIONS D76; ADR-116 §6 (grill log D7.2).

WHAT IT ADDS. ``production_write_authorizations`` and ``production_write_audit`` were keyed by
``tiktok_product_id``; phase 2 (Shopee) needs the same gate and the same trail per platform.
On both tables:

- ``platform`` varchar(32) NOT NULL DEFAULT ``'tiktok'`` -- every existing row is a TikTok row,
  and code that does not name a platform yet keeps writing TikTok rows;
- ``platform_product_id`` varchar(100), nullable -- written by the code beside
  ``tiktok_product_id`` from this release on; read with a fallback to ``tiktok_product_id``
  (``COALESCE``) so a row written before it still matches;
- on the authorizations table, an index (``shop_id``, ``platform``, ``platform_product_id``,
  ``mutation_kind``) for the per-platform lookup.

EXPAND-ONLY AND REVERSIBLE (ADR-027). Two columns per table and one index; the old column, its
index, the RLS policies and the grants are untouched (``juli_app`` keeps SELECT / INSERT on the
audit -- still append-only -- and SELECT / UPDATE on the authorizations). Column-level grants
are not used anywhere, so the table grants cover the new columns. ``downgrade`` drops them.

NO DATA IS MOVED HERE. Copying the stored ``tiktok_product_id`` into ``platform_product_id`` is a
data change, which ``infra/scripts/migration_additive_gate.py`` refuses from a release. It is
the operator command ``python -m juli_backend.services.operations.write_platform_backfill``
(dry run by default, ``--apply`` to write), run once this release is serving. Until it runs the
reads' fallback keeps every old row matching, so running it late is harmless.

The deferred write-mode backfill (and the phone cleanup under it) is re-parented onto this
revision so it stays the tail.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "106_write_platform_columns"
down_revision: str | None = "105_llm_call_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUTHORIZATIONS = "production_write_authorizations"
AUDIT = "production_write_audit"
TABLES = (AUTHORIZATIONS, AUDIT)
PLATFORM = "platform"
PLATFORM_PRODUCT_ID = "platform_product_id"
#: Written out rather than imported from the model: a migration must not change when the
#: model does. ``tests/unit/test_write_approval.py`` pins the two equal.
DEFAULT_PLATFORM = "tiktok"
LOOKUP_INDEX = "ix_production_write_authorizations_platform_lookup"


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                PLATFORM,
                sa.String(length=32),
                server_default=sa.text(f"'{DEFAULT_PLATFORM}'"),
                nullable=False,
            ),
        )
        op.add_column(table, sa.Column(PLATFORM_PRODUCT_ID, sa.String(length=100), nullable=True))
    op.create_index(
        LOOKUP_INDEX,
        AUTHORIZATIONS,
        ["shop_id", PLATFORM, PLATFORM_PRODUCT_ID, "mutation_kind"],
    )


def downgrade() -> None:
    op.drop_index(LOOKUP_INDEX, table_name=AUTHORIZATIONS)
    for table in TABLES:
        op.drop_column(table, PLATFORM_PRODUCT_ID)
        op.drop_column(table, PLATFORM)
