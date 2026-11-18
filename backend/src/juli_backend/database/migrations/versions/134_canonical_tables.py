"""Canonical fact tables: the seven Shopee tables get platform-neutral names (T5)

Revision ID: 134_canonical_tables
Revises: 135_connector_multi_computer
Create Date: 2026-11-18

Spec: the T5 canonical map (owner Q-T5-1..4 = a, D1-D4, 2026-11-18). The
TikTok mapper writes to the same tables Shopee does.

Chain (2026-11-18): 134 follows ``135_connector_multi_computer`` (batch 1118e, deployed first; it
revises 133). 135 touches none of the seven tables (``shopee_fill_jobs``, ``ingest_tokens`` and its
own ``shopee_connector_token_state``), so the downgrade 134 -> 135 restores the 135 schema as is.

- Tables: ``shopee_order_lines`` -> ``order_lines``, ``shopee_order_income`` ->
  ``order_settlements``, ``shopee_affiliate_lines`` -> ``affiliate_lines``,
  ``shopee_shop_metrics_daily`` / ``shopee_product_metrics_daily`` / ``shopee_source_metrics_daily``
  -> ``shop_metrics_daily`` / ``product_metrics_daily`` / ``source_metrics_daily``,
  ``shopee_stock_history`` -> ``stock_history``. Every constraint, index and policy name that
  carried the old table name carries the new one. RLS, the policies' clauses and the ``juli_app``
  verbs move with the table unchanged (stock_history: SELECT, INSERT; the others SELECT, INSERT,
  UPDATE).
- Columns: ``order_lines.shopee_subsidy`` -> ``platform_subsidy``,
  ``order_settlements.ship_shopee_subsidy`` -> ``ship_platform_subsidy``,
  ``affiliate_lines.order_status`` -> ``status``, ``affiliate_lines.model_id`` and
  ``stock_history.model_id`` -> ``variation_id`` (D3; the unique keys follow). Added:
  ``source_rank`` on ``order_lines`` and ``affiliate_lines`` (filled from ``source`` with
  ``models.ingest.SOURCE_RANK``), ``order_settlements.fee_other``, and the stored GMT+7 ``day`` of
  ``ordered_at`` on ``order_lines`` and ``affiliate_lines``. PiShip / NTTD / Voucher Xtra keep
  their names (Q-T5-2).
- Times are ``timestamptz`` (Q-T5-4). The stored naive values are converted by their known
  meaning: the order times (``ordered_at``, ``paid_at``, ``completed_at``, ``conversion_at``) are
  Vietnam local -- every sender posts a naive GMT+7 wall clock (the Connector's ``wallClock``, the
  file parsers, the sample generator). ``ordered_at`` verified on prod 2026-11-17 (grouping by
  ``ordered_at::date`` matched the shop totals); ``paid_at`` verified 2026-11-18 (paid within
  minutes of ``ordered_at`` on the same wall clock, no 7 h offset); ``completed_at`` /
  ``conversion_at`` assumed from the same source (their gap to ``ordered_at`` is days, so a 7 h
  shift cannot be ruled out by reading). ``read_at`` (the post's ``captured_at`` made naive UTC by the gateway)
  and the audit times (``created_at``, ``updated_at``, ``built_at``: ``now()`` / the gateway's
  naive-UTC clock) are UTC. The stock-alert tables (``shopee_sku_tracking``,
  ``shopee_stock_alert_unsubscribes``, ``shopee_stock_alert_sends``) are not T5 tables: their
  times stay naive UTC.
- Order statuses (Q-T5-3, D2): ``order_lines.status`` is one of ``pending``, ``confirmed``,
  ``in_transit``, ``delivered``, ``cancelled``, ``refunded_accepted``, ``refunded_not_received``,
  ``returned``, ``on_hold`` (CHECK). A stored value outside the set becomes ``in_transit`` when the
  line has a payment time, else ``pending``.
- Index ``(shop_id, read_at)`` on ``stock_history`` (map §5), ``(shop_id, day)`` on the line
  tables.
- Compat views (D4), for one release: a ``security_invoker = true`` view under each old name
  (``SELECT *`` of the new table, so it shows the NEW column names), with the table's verbs to
  ``juli_app``. A simple view is auto-updatable and the invoker's RLS applies through it.

REVERSIBLE: downgrade drops the views, the added columns, indexes and the CHECK, converts the
times back to naive values of the same meaning, and restores the names. The status merge is not
1:1, so a normalised status stays as it is (the 135 schema has no CHECK on it).

NOT ADDITIVE: renames, type changes and the fill UPDATEs are refused by
``infra/scripts/migration_additive_gate.py``. Owner decision 2026-11-18: 134 ships in a
maintenance window. The owner runs ``alembic upgrade 134_canonical_tables`` on the VPS as a
separate step (workers and Connector sync paused), then the deploy tag runs with nothing pending,
so the gate passes. Runbook: ``docs/runbooks/t5-maintenance-window.md``. Forward fix only: after
the window the downgrade is for tests and emergencies, never part of a rollback.

``lock_timeout`` (``LOCK_TIMEOUT``, transaction-local): every rename / type change takes an
ACCESS EXCLUSIVE lock on a fact table; if a straggling worker or Connector post still holds
one, the migration fails fast and can be re-run instead of queueing every later query behind it.

``source_rank`` is filled with the ranks of the owner's 2026-11-18 order (API > Connector > file
> vendor: api 4, extension 3, file 2, vendor 1), as ``models.ingest.SOURCE_RANK`` now holds them.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "134_canonical_tables"
down_revision: str | None = "135_connector_multi_computer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
VN = "Asia/Ho_Chi_Minh"
UTC = "UTC"
#: fail fast on a held lock (see the module doc)
LOCK_TIMEOUT = "10s"
UPSERT_VERBS = "SELECT, INSERT, UPDATE"
APPEND_ONLY_VERBS = "SELECT, INSERT"

LINES = "order_lines"
SETTLEMENTS = "order_settlements"
AFFILIATE = "affiliate_lines"
SHOP_DAILY = "shop_metrics_daily"
PRODUCT_DAILY = "product_metrics_daily"
SOURCE_DAILY = "source_metrics_daily"
STOCK = "stock_history"

#: (old name, new name, the juli_app verbs of the table and of its compat view)
TABLES: tuple[tuple[str, str, str], ...] = (
    ("shopee_order_lines", LINES, UPSERT_VERBS),
    ("shopee_order_income", SETTLEMENTS, UPSERT_VERBS),
    ("shopee_affiliate_lines", AFFILIATE, UPSERT_VERBS),
    ("shopee_shop_metrics_daily", SHOP_DAILY, UPSERT_VERBS),
    ("shopee_product_metrics_daily", PRODUCT_DAILY, UPSERT_VERBS),
    ("shopee_source_metrics_daily", SOURCE_DAILY, UPSERT_VERBS),
    ("shopee_stock_history", STOCK, APPEND_ONLY_VERBS),
)
#: (table, old column, new column)
COLUMNS: tuple[tuple[str, str, str], ...] = (
    (LINES, "shopee_subsidy", "platform_subsidy"),
    (SETTLEMENTS, "ship_shopee_subsidy", "ship_platform_subsidy"),
    (AFFILIATE, "order_status", "status"),
    (AFFILIATE, "model_id", "variation_id"),
    (STOCK, "model_id", "variation_id"),
)
#: (table, column, the zone its naive values are in)
TIMES: tuple[tuple[str, str, str], ...] = (
    (LINES, "ordered_at", VN),
    (LINES, "paid_at", VN),
    (LINES, "completed_at", VN),
    (LINES, "created_at", UTC),
    (LINES, "updated_at", UTC),
    (AFFILIATE, "ordered_at", VN),
    (AFFILIATE, "completed_at", VN),
    (AFFILIATE, "conversion_at", VN),
    (AFFILIATE, "created_at", UTC),
    (AFFILIATE, "updated_at", UTC),
    (SETTLEMENTS, "created_at", UTC),
    (SETTLEMENTS, "updated_at", UTC),
    (SHOP_DAILY, "built_at", UTC),
    (PRODUCT_DAILY, "built_at", UTC),
    (SOURCE_DAILY, "built_at", UTC),
    (STOCK, "read_at", UTC),
    (STOCK, "created_at", UTC),
)
DAY_TABLES = (LINES, AFFILIATE)
RANK_TABLES = (LINES, AFFILIATE)
#: (index, table, columns) added here
INDEXES: tuple[tuple[str, str, str], ...] = (
    ("ix_order_lines_day", LINES, "shop_id, day"),
    ("ix_affiliate_lines_day", AFFILIATE, "shop_id, platform, day"),
    ("ix_stock_history_read", STOCK, "shop_id, read_at"),
)
STATUSES = (
    "'pending', 'confirmed', 'in_transit', 'delivered', 'cancelled', 'refunded_accepted', "
    "'refunded_not_received', 'returned', 'on_hold'"
)
#: ``models.ingest.SOURCE_RANK`` at this revision (api 4, extension 3, file 2, vendor 1)
RANK_CASE = (
    "CASE source WHEN 'api' THEN 4 WHEN 'extension' THEN 3 WHEN 'file' THEN 2 "
    "WHEN 'vendor' THEN 1 ELSE 0 END"
)


def _rename_objects(table: str, old: str, new: str) -> None:
    """Every constraint, index and policy of ``table`` whose name holds ``old`` gets ``new``.
    Constraints first: renaming a primary / unique key renames its index too."""
    op.execute(f"""
    DO $$
    DECLARE
        r record;
    BEGIN
        FOR r IN
            SELECT conname AS name FROM pg_constraint
            WHERE conrelid = 'public.{table}'::regclass AND position('{old}' IN conname) > 0
        LOOP
            EXECUTE format(
                'ALTER TABLE public.%I RENAME CONSTRAINT %I TO %I',
                '{table}', r.name, replace(r.name, '{old}', '{new}')
            );
        END LOOP;
        FOR r IN
            SELECT indexname AS name FROM pg_indexes
            WHERE schemaname = 'public' AND tablename = '{table}'
              AND position('{old}' IN indexname) > 0
        LOOP
            EXECUTE format(
                'ALTER INDEX public.%I RENAME TO %I', r.name, replace(r.name, '{old}', '{new}')
            );
        END LOOP;
        FOR r IN
            SELECT polname AS name FROM pg_policy
            WHERE polrelid = 'public.{table}'::regclass AND position('{old}' IN polname) > 0
        LOOP
            EXECUTE format(
                'ALTER POLICY %I ON public.%I RENAME TO %I',
                r.name, '{table}', replace(r.name, '{old}', '{new}')
            );
        END LOOP;
    END
    $$;
    """)  # nosec B608 - fixed module constants


def _grant(relation: str, verbs: str) -> None:
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT {verbs} ON public.{relation} TO {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608 - fixed module constants


def _fail_fast() -> None:
    op.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")  # nosec B608 - module constant


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    _fail_fast()
    for old, new, _verbs in TABLES:
        op.execute(f"ALTER TABLE public.{old} RENAME TO {new}")  # nosec B608
        _rename_objects(new, old, new)
        # RLS moves with the table; stated again under the new name (a no-op if already on)
        op.execute(f"ALTER TABLE public.{new} ENABLE ROW LEVEL SECURITY")  # nosec B608
    for table, old_column, new_column in COLUMNS:
        op.execute(  # nosec B608 - fixed module constants
            f"ALTER TABLE public.{table} RENAME COLUMN {old_column} TO {new_column}"
        )
    for table, column, zone in TIMES:
        op.execute(  # nosec B608 - fixed module constants
            f"ALTER TABLE public.{table} ALTER COLUMN {column} TYPE timestamptz "
            f"USING {column} AT TIME ZONE '{zone}'"
        )
    for table in RANK_TABLES:
        op.execute(  # nosec B608 - fixed module constants
            f"ALTER TABLE public.{table} ADD COLUMN source_rank smallint NOT NULL DEFAULT 0"
        )
        op.execute(f"UPDATE public.{table} SET source_rank = {RANK_CASE}")  # nosec B608
    for table in DAY_TABLES:
        op.execute(f"ALTER TABLE public.{table} ADD COLUMN day date")  # nosec B608
        op.execute(
            f"UPDATE public.{table} SET day = (ordered_at AT TIME ZONE '{VN}')::date"  # nosec B608
        )
        op.execute(f"ALTER TABLE public.{table} ALTER COLUMN day SET NOT NULL")  # nosec B608
    op.execute(f"ALTER TABLE public.{SETTLEMENTS} ADD COLUMN fee_other numeric(18, 2)")  # nosec B608
    op.execute(f"""
    UPDATE public.{LINES}
    SET status = CASE WHEN paid_at IS NOT NULL THEN 'in_transit' ELSE 'pending' END
    WHERE status NOT IN ({STATUSES})
    """)  # nosec B608 - fixed module constants
    op.execute(  # nosec B608 - fixed module constants
        f"ALTER TABLE public.{LINES} ADD CONSTRAINT ck_order_lines_status "
        f"CHECK (status IN ({STATUSES}))"
    )
    for index, table, columns in INDEXES:
        op.execute(f"CREATE INDEX {index} ON public.{table} ({columns})")  # nosec B608
    for old, new, verbs in TABLES:
        op.execute(
            f"CREATE VIEW public.{old} WITH (security_invoker = true) "  # nosec B608
            f"AS SELECT * FROM public.{new}"
        )
        _grant(old, verbs)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    _fail_fast()
    for old, _new, _verbs in TABLES:
        op.execute(f"DROP VIEW IF EXISTS public.{old}")  # nosec B608
    for index, _table, _columns in INDEXES:
        op.execute(f"DROP INDEX IF EXISTS public.{index}")  # nosec B608
    op.execute(  # nosec B608 - fixed module constants
        f"ALTER TABLE public.{LINES} DROP CONSTRAINT IF EXISTS ck_order_lines_status"
    )
    op.execute(f"ALTER TABLE public.{SETTLEMENTS} DROP COLUMN fee_other")  # nosec B608
    for table in DAY_TABLES:
        op.execute(f"ALTER TABLE public.{table} DROP COLUMN day")  # nosec B608
    for table in RANK_TABLES:
        op.execute(f"ALTER TABLE public.{table} DROP COLUMN source_rank")  # nosec B608
    for table, column, zone in TIMES:
        op.execute(  # nosec B608 - fixed module constants
            f"ALTER TABLE public.{table} ALTER COLUMN {column} TYPE timestamp "
            f"USING {column} AT TIME ZONE '{zone}'"
        )
    for table, old_column, new_column in COLUMNS:
        op.execute(  # nosec B608 - fixed module constants
            f"ALTER TABLE public.{table} RENAME COLUMN {new_column} TO {old_column}"
        )
    for old, new, _verbs in TABLES:
        _rename_objects(new, new, old)
        op.execute(f"ALTER TABLE public.{new} RENAME TO {old}")  # nosec B608
