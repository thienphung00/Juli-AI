"""Content hashes on Juli's writes, per-field attribution of product changes (fast track P60-1b).

Revision ID: 096_change_attribution
Revises: 095_card_events
Create Date: 2026-10-20

DECISIONS D70.11 (1)(3); ADR-107 "Amendment 2026-10-20" §6 and §8.

WHAT IT ADDS.

- ``run_write_values``: ``before_hash``, ``after_hash`` (sha256 of the value in
  the form ``product_snapshots`` hashes it, ``normalize.field_value_hash``),
  ``before_read_at``, ``production_write_audit_id`` (-> ``production_write_audit``,
  nullable).
- ``external_changes``: ``attribution`` (CHECK ``juli`` / ``seller_revert`` /
  ``seller_change`` / ``mixed``, NULL only on a row written by pre-096 code) and
  ``field_attribution`` (jsonb ``{field: label}``).
- ``enumerate_history_shops()``: a ``SECURITY DEFINER`` function returning the
  ids of every shop with cards, Juli writes or observed changes (identifiers
  only, EXECUTE for ``juli_app`` only, the migration 051 pattern), so the
  ``card_events_backfill_fanout`` reaches a disconnected shop with history too.

GRANTS UNCHANGED. Both tables stay append-only for ``juli_app`` (SELECT, INSERT;
078 / 087): new columns inherit the table grants and no UPDATE is granted.

DATA STEP (runs as the migration owner, so it may UPDATE). Existing rows are
filled here, because the runtime role cannot:

1. hashes of every ``run_write_values`` row: a pure function of its stored values;
2. the audit link, by (``run_id``, ``tiktok_product_id``, ``mutation_kind`` =
   ``tool_name``) only when exactly one audit row matches, else NULL;
3. the attribution of every ``external_changes`` row: ``juli_write`` rows are
   all ``juli`` (the stored verdict stands); content / price rows are labelled
   against the snapshot they recorded (``details.snapshot_id``) and the Juli
   writes known when they were detected; every other row is all
   ``seller_change``.

The hash and the labelling rules are written out here (``database`` may not
import ``services``, and a migration must not change when the code does);
``tests/unit/test_change_attribution.py`` pins them equal to
``normalize.field_value_hash`` and ``attribution.label_fields`` over the
attribution matrix. On a fresh database there are no rows and the step does nothing. ``seller_change`` ``card_events`` rows for past changes
are written by the ``card_events_backfill`` task, not here.

REVERSIBLE. ``downgrade`` drops the function, the CHECK, the FK and the columns.
The deferred phone-cleanup step is re-parented onto this revision so it stays the tail.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "096_change_attribution"
down_revision: str | None = "095_card_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "juli_app"
WRITES = "run_write_values"
CHANGES = "external_changes"
#: Written out rather than imported from the model (a migration must not change
#: when the model does). ``tests/unit/test_change_attribution.py`` pins them equal.
ATTRIBUTIONS = ("juli", "seller_revert", "seller_change", "mixed")
FUNCTION_SIGNATURE = "enumerate_history_shops()"


# -- frozen copies of the pure helpers (pinned equal by tests/unit/test_change_attribution.py)

#: ``attribution.JULI_WRITE_LOOKBACK`` / ``JULI_WRITE_LOOKAHEAD`` / ``JULI_FIELDS``.
LOOKBACK = timedelta(hours=72)
LOOKAHEAD = timedelta(hours=1)
JULI_FIELDS = frozenset({"title", "description", "main_images", "price"})


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _plain(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _amount(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        return _plain(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return f"invalid:{value}"


def _uris(value: Any) -> list[str]:
    out: list[str] = []
    for image in value if isinstance(value, list | tuple) else []:
        uri = image.get("uri") if isinstance(image, dict) else image
        if uri:
            out.append(str(uri))
    return out


def field_hash(field: str, value: Any) -> str | None:
    """``normalize.field_value_hash``."""
    if value is None:
        return None
    if field in ("title", "description"):
        return _sha(str(value).strip())
    if field == "main_images":
        return _sha(_canonical(_uris(value)))
    if field == "price":
        items = value if isinstance(value, list | tuple) else []
        pairs = [
            [str(i.get("sku_id")), _amount(i.get("amount"))] for i in items if isinstance(i, dict)
        ]
        return _sha(_canonical(sorted(pairs, key=lambda pair: pair[0])))
    return _sha(_canonical(value))


def state_hash(state: dict[str, Any], field: str, like: Any) -> str | None:
    """``normalize.ProductFields.field_hash`` over a snapshot's columns."""
    if field == "title":
        return field_hash("title", state["title"])
    if field == "description":
        return state["description_hash"]
    if field == "main_images":
        return field_hash("main_images", list(state["image_uris"]))
    if field == "price":
        prices = state["list_prices"]
        if isinstance(like, list | tuple):
            wanted = sorted(str(i.get("sku_id")) for i in like if isinstance(i, dict))
        else:
            wanted = sorted(prices)
        return _sha(_canonical([[sku, prices.get(sku)] for sku in wanted]))
    return None


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def label_field(
    field: str,
    state: dict[str, Any] | None,
    writes: list[dict[str, Any]],
    occurred_at: datetime,
    known_at: datetime | None,
) -> str:
    """``attribution.label_field``; a write is ``{field, recorded_at, before_value,
    after_value, before_hash, after_hash}``."""
    if field not in JULI_FIELDS or state is None:
        return "seller_change"
    occurred = _naive(occurred_at)
    latest = occurred + LOOKAHEAD
    if known_at is not None:
        latest = min(latest, _naive(known_at))
    mine = sorted(
        (w for w in writes if w["field"] == field and _naive(w["recorded_at"]) <= latest),
        key=lambda w: _naive(w["recorded_at"]),
    )
    for w in mine:
        if _naive(w["recorded_at"]) < occurred - LOOKBACK:
            continue
        if w["after_value"] is None and w["after_hash"] is None:
            return "juli"
        after = w["after_hash"] or field_hash(field, w["after_value"])
        if after == state_hash(state, field, w["after_value"]):
            return "juli"
    if mine:
        last = mine[-1]
        before = last["before_hash"] or field_hash(field, last["before_value"])
        if before is not None and before == state_hash(state, field, last["before_value"]):
            return "seller_revert"
    return "seller_change"


def label_fields(
    kind: str,
    fields: list[str],
    state: dict[str, Any] | None,
    writes: list[dict[str, Any]],
    occurred_at: datetime,
    known_at: datetime | None,
    juli_write: bool = False,
) -> dict[str, str]:
    """``attribution.label_fields`` / ``uniform_labels`` for one row."""
    names = ["price"] if kind == "price" else ([str(f) for f in fields] or ["product"])
    if juli_write:
        return {name: "juli" for name in names}
    if kind not in ("content", "price"):
        return {name: "seller_change" for name in names}
    return {name: label_field(name, state, writes, occurred_at, known_at) for name in names}


def summarize(labels: dict[str, str]) -> str:
    distinct = set(labels.values())
    if not distinct:
        return "seller_change"
    return distinct.pop() if len(distinct) == 1 else "mixed"


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _schema() -> None:
    op.add_column(WRITES, sa.Column("before_hash", sa.String(length=64), nullable=True))
    op.add_column(WRITES, sa.Column("after_hash", sa.String(length=64), nullable=True))
    op.add_column(WRITES, sa.Column("before_read_at", sa.DateTime(), nullable=True))
    op.add_column(WRITES, sa.Column("production_write_audit_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_run_write_values_audit",
        WRITES,
        "production_write_audit",
        ["production_write_audit_id"],
        ["id"],
    )
    op.add_column(CHANGES, sa.Column("attribution", sa.String(length=16), nullable=True))
    op.add_column(CHANGES, sa.Column("field_attribution", postgresql.JSONB(), nullable=True))
    op.create_check_constraint(
        "ck_external_changes_attribution",
        CHANGES,
        f"attribution IS NULL OR attribution IN ({_in(ATTRIBUTIONS)})",
    )


def _function() -> None:
    op.execute(f"""
    CREATE OR REPLACE FUNCTION public.{FUNCTION_SIGNATURE}
    RETURNS TABLE (out_shop_id uuid)
      LANGUAGE sql
      STABLE
      SECURITY DEFINER
      SET search_path = pg_catalog, public
      AS $fn$
        SELECT shop_id FROM public.action_cards
        UNION SELECT shop_id FROM public.external_changes
        UNION SELECT shop_id FROM public.run_write_values
      $fn$;
    """)  # nosec B608 - fixed module constant
    op.execute(f"REVOKE ALL ON FUNCTION public.{FUNCTION_SIGNATURE} FROM PUBLIC;")  # nosec B608
    op.execute(f"""
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT EXECUTE ON FUNCTION public.{FUNCTION_SIGNATURE} TO {APP_ROLE}';
        END IF;
    END
    $$;
    """)  # nosec B608


def _fill_hashes(conn: Any) -> None:
    rows = conn.execute(
        sa.text(
            f"SELECT id, field, before_value, after_value FROM public.{WRITES} "  # nosec B608
            "WHERE before_hash IS NULL AND after_hash IS NULL"
        )
    ).all()
    for row_id, field, before, after in rows:
        conn.execute(
            sa.text(
                f"UPDATE public.{WRITES} SET before_hash = :b, after_hash = :a "  # nosec B608
                "WHERE id = :id"
            ),
            {
                "id": row_id,
                "b": field_hash(field, before),
                "a": field_hash(field, after),
            },
        )


def _fill_audit_links(conn: Any) -> None:
    conn.execute(
        sa.text(f"""
        UPDATE public.{WRITES} AS w
           SET production_write_audit_id = a.audit_id
          FROM (
                SELECT run_id, tiktok_product_id, mutation_kind,
                       (array_agg(id))[1] AS audit_id
                  FROM public.production_write_audit
                 GROUP BY run_id, tiktok_product_id, mutation_kind
                HAVING count(*) = 1
               ) AS a
         WHERE w.production_write_audit_id IS NULL
           AND a.run_id = w.workflow_run_id
           AND a.tiktok_product_id = w.tiktok_product_id
           AND a.mutation_kind = w.tool_name
        """)  # nosec B608 - fixed module constant
    )


def _fill_attribution(conn: Any) -> None:
    changes = conn.execute(
        sa.text(
            "SELECT id, shop_id, tiktok_product_id, kind, fields, occurred_at, "  # nosec B608
            f" detected_at, juli_write, details FROM public.{CHANGES} WHERE attribution IS NULL"
        )
    ).all()
    if not changes:
        return
    writes: dict[tuple[Any, str], list[dict[str, Any]]] = defaultdict(list)
    for row in conn.execute(
        sa.text(
            "SELECT shop_id, tiktok_product_id, field, recorded_at, before_value, "
            f" after_value, before_hash, after_hash FROM public.{WRITES} "  # nosec B608
            "ORDER BY recorded_at, id"
        )
    ).all():
        writes[(row[0], row[1])].append(
            {
                "field": row[2],
                "recorded_at": row[3],
                "before_value": row[4],
                "after_value": row[5],
                "before_hash": row[6],
                "after_hash": row[7],
            }
        )
    for change_id, shop_id, pid, kind, fields, occurred, detected, juli, details in changes:
        state = None
        if not juli and kind in ("content", "price"):
            raw = details.get("snapshot_id") if isinstance(details, dict) else None
            try:
                snapshot_id = uuid.UUID(str(raw)) if raw else None
            except ValueError:
                snapshot_id = None
            if snapshot_id is not None:
                snap = conn.execute(
                    sa.text(
                        "SELECT title, description_hash, main_images, skus "
                        "FROM public.product_snapshots WHERE id = :id AND shop_id = :shop"
                    ),
                    {"id": snapshot_id, "shop": shop_id},
                ).first()
                if snap is not None:
                    state = {
                        "title": snap[0],
                        "description_hash": snap[1],
                        "image_uris": _uris(snap[2] or []),
                        "list_prices": {
                            str(s.get("sku_id")): s.get("list_price")
                            for s in snap[3] or []
                            if isinstance(s, dict)
                        },
                    }
        labels = label_fields(
            kind,
            list(fields or []),
            state,
            writes.get((shop_id, pid), []) if pid else [],
            occurred,
            detected,
            juli_write=bool(juli),
        )
        conn.execute(
            sa.text(
                f"UPDATE public.{CHANGES} SET attribution = :a, "  # nosec B608
                "field_attribution = CAST(:f AS jsonb) WHERE id = :id"
            ),
            {"id": change_id, "a": summarize(labels), "f": json.dumps(labels)},
        )


def upgrade() -> None:
    _schema()
    _function()
    conn = op.get_bind()
    _fill_hashes(conn)
    _fill_audit_links(conn)
    _fill_attribution(conn)


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS public.{FUNCTION_SIGNATURE};")  # nosec B608
    op.drop_constraint("ck_external_changes_attribution", CHANGES, type_="check")
    op.drop_column(CHANGES, "field_attribution")
    op.drop_column(CHANGES, "attribution")
    op.drop_constraint("fk_run_write_values_audit", WRITES, type_="foreignkey")
    op.drop_column(WRITES, "production_write_audit_id")
    op.drop_column(WRITES, "before_read_at")
    op.drop_column(WRITES, "after_hash")
    op.drop_column(WRITES, "before_hash")
