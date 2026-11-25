"""Two indexes for the hot read paths no index orders, one duplicate dropped (batch-1125-idx)

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
serves its reads once they bound ``read_at`` (the code half of this batch). It loses one:
``ix_stock_history_sku`` ``(shop_id, item_id, variation_id, read_at)`` (129, renamed in 134) has
the same columns in the same order as the unique ``uq_stock_history_read``, so every read it could
serve the unique index serves, and every stock read row (one per variation per Connector read)
paid one more index write for nothing (owner approval 2026-11-25).

Plain ``CREATE INDEX`` (no migration here uses CONCURRENTLY): the tables hold a few thousand rows,
so the SHARE lock lasts milliseconds. ``IF NOT EXISTS`` makes a re-run safe.

REVERSIBLE: two new indexes and one dropped duplicate; ``downgrade`` drops exactly the two and
recreates ``ix_stock_history_sku`` as 129 / 134 left it. Dropping an index relaxes nothing the
previous code relies on (the additive gate tolerates it): the unique twin keeps serving its reads.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "139_hot_path_indexes"
down_revision: str | None = "138_juli_agent_spend"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (index, table, columns) added here -- the models' ``__table_args__`` carry the same two
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
#: the duplicate of ``uq_stock_history_read`` dropped here (and recreated by ``downgrade``)
DROPPED: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ix_stock_history_sku", "stock_history", ("shop_id", "item_id", "variation_id", "read_at")),
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
    op.execute("DROP INDEX IF EXISTS public.ix_stock_history_sku")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX ix_stock_history_sku ON public.stock_history "
        "USING btree (shop_id, item_id, variation_id, read_at)"
    )
    op.execute("DROP INDEX IF EXISTS public.ix_platform_promotions_type_capture")
    op.execute("DROP INDEX IF EXISTS public.ix_platform_item_snapshots_capture")
