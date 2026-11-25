"""Two indexes for the hot read paths that no existing index orders (batch-1125-idx, owner #68)

Revision ID: 139_hot_path_indexes
Revises: 138_juli_agent_spend
Create Date: 2026-11-25

Prod ``pg_stat_user_tables`` (2026-11-25) showed full scans on ``stock_history``,
``platform_item_snapshots`` and ``platform_promotions``. Every reader filters ``shop_id`` and
every table already has an index leading with it; two read shapes still had no index in their
sort order:

- ``ix_platform_item_snapshots_capture`` ``(shop_id, platform, captured_at)``: the screens'
  freshness read ``max(captured_at)`` for the shop's platform (``PlatformItemSnapshotsRepo.
  latest_capture``, every screen load) and the shop-inputs catalogue's newest-first read. The
  unique ``ix_platform_item_snapshots_item_time`` puts ``item_id`` / ``variation_id`` before
  ``captured_at``, so neither could stop early; with this index the max is one index entry.
- ``ix_platform_promotions_type_capture`` ``(shop_id, promo_type, captured_at)``: the Connector
  fill poll's voucher capture (``fill_queue.resolve_voucher_captures``: ``promo_type`` voucher,
  newest ``captured_at`` first, limit 400), the voucher read-back and revert, and the voucher
  verification (``captured_at > since``). They do not all filter ``platform``, so the unique key
  ``(shop_id, platform, promo_type, ...)`` served only its ``shop_id`` column.

``stock_history`` gets no index: ``ix_stock_history_read`` ``(shop_id, read_at)`` (134) already
serves its reads once they bound ``read_at`` (the code half of this batch).

Plain ``CREATE INDEX`` (no migration here uses CONCURRENTLY): the tables hold a few thousand rows,
so the SHARE lock lasts milliseconds. ``IF NOT EXISTS`` makes a re-run safe.

ADDITIVE AND REVERSIBLE: two new indexes; ``downgrade`` drops exactly these two.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "139_hot_path_indexes"
down_revision: str | None = "138_juli_agent_spend"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (index, table, columns) -- the models' ``__table_args__`` carry the same two
INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "ix_platform_item_snapshots_capture",
        "platform_item_snapshots",
        ("shop_id", "platform", "captured_at"),
    ),
    (
        "ix_platform_promotions_type_capture",
        "platform_promotions",
        ("shop_id", "promo_type", "captured_at"),
    ),
)


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_platform_item_snapshots_capture "
        "ON public.platform_item_snapshots (shop_id, platform, captured_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_platform_promotions_type_capture "
        "ON public.platform_promotions (shop_id, promo_type, captured_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.ix_platform_promotions_type_capture")
    op.execute("DROP INDEX IF EXISTS public.ix_platform_item_snapshots_capture")
