"""Reset the sample shop: delete every row the shop accumulated, then the loader re-seeds it.

    python -m scripts.sample_shop --reset --database-url "$DATABASE_DIRECT_URL" \
        --allow-remote-database            # preview: counts per table, rolled back
    python -m scripts.sample_shop --reset --yes --database-url ... --allow-remote-database

An operator command on the migration OWNER connection (``DATABASE_DIRECT_URL``), never
``juli_app``: the append-only tables (card events, approvals, ...) stay ungranted for the app, so
reviewers' actions accumulate until the owner runs this (P100 S2-G, owner decision (c)).

Safety (all before anything is deleted):
- the shop must pass the loader's ``check_target``: Shopee, ``shopee_shop_id`` in the reserved
  synthetic range, no credential, not Fujiwa or the sandbox shop;
- the tables come from the live catalogue (every table with a ``shop_id`` column, plus the
  ``shop_id``-less tables whose foreign key points at one of them); every DELETE is filtered to
  this one shop's rows; one transaction, so a failure deletes nothing;
- kept: the ``shops`` row (its id is in ``REVIEWER_SHOP_IDS``), consent, membership, the audit
  log (``reviewer_sample_write`` rows) and the per-shop settings in ``KEEP_TABLES``.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

#: Rows the reset leaves in place (``schema.table``).
KEEP_TABLES = frozenset(
    {
        "public.shops",
        "public.data_use_consents",
        "public.shop_members",
        "public.ops_shop_invites",
        "public.ops_audit_log",
        "public.ops_shop_settings",
        "public.shop_pseudonym_keys",
        "public.shop_subscription_periods",
        "public.llm_call_log",
    }
)

_SHOP_TABLES = sa.text(
    """
    SELECT n.nspname, c.relname
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE a.attname = 'shop_id' AND a.attnum > 0 AND NOT a.attisdropped
      AND c.relkind IN ('r', 'p') AND NOT c.relispartition
      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND n.nspname NOT LIKE 'pg_toast%'
    """
)

_FOREIGN_KEYS = sa.text(
    """
    SELECT cn.nspname, cc.relname, pn.nspname, pc.relname,
           ARRAY(SELECT a.attname FROM unnest(con.conkey) WITH ORDINALITY k(n, i)
                 JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.n
                 ORDER BY k.i),
           ARRAY(SELECT a.attname FROM unnest(con.confkey) WITH ORDINALITY k(n, i)
                 JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.n
                 ORDER BY k.i)
    FROM pg_constraint con
    JOIN pg_class cc ON cc.oid = con.conrelid
    JOIN pg_namespace cn ON cn.oid = cc.relnamespace
    JOIN pg_class pc ON pc.oid = con.confrelid
    JOIN pg_namespace pn ON pn.oid = pc.relnamespace
    WHERE con.contype = 'f' AND NOT cc.relispartition
    """
)


class ResetRefused(Exception):
    """The catalogue holds a shape the reset does not handle; nothing was deleted."""


@dataclass(frozen=True)
class ForeignKey:
    child: str
    parent: str
    child_cols: tuple[str, ...]
    parent_cols: tuple[str, ...]


@dataclass(frozen=True)
class Step:
    """Delete ``table``'s rows of the shop: by its own ``shop_id``, or through ``via``."""

    table: str
    via: ForeignKey | None = None


@dataclass
class ResetReport:
    shop_id: uuid.UUID
    committed: bool
    deleted: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.deleted.values())


def plan_deletes(
    shop_tables: set[str], fks: list[ForeignKey], keep: frozenset[str] = KEEP_TABLES
) -> list[Step]:
    """The DELETEs in a foreign-key-safe order (every referencing table before its parent)."""
    keep_set = set(keep)
    # a kept row may point at a shop row (shop_members.invite_id -> ops_shop_invites): keep that too
    changed = True
    while changed:
        changed = False
        for fk in fks:
            if fk.child in keep_set and fk.parent in shop_tables and fk.parent not in keep_set:
                keep_set.add(fk.parent)
                changed = True
    direct = {t for t in shop_tables if t not in keep_set}
    via: dict[str, ForeignKey] = {}
    for fk in fks:
        if fk.parent in direct and fk.child not in shop_tables and fk.child not in keep_set:
            if fk.child in via and via[fk.child].parent != fk.parent:
                continue  # one parent is enough to find the shop's rows
            via[fk.child] = fk
    for child, fk in via.items():
        for other in fks:
            if other.parent == child and other.child != child and other.child not in shop_tables:
                raise ResetRefused(
                    f"{other.child} references {child} (via {fk.parent}), which has no "
                    "shop_id: not handled"
                )
    tables = direct | set(via)
    children: dict[str, set[str]] = defaultdict(set)
    for fk in fks:
        if fk.child in tables and fk.parent in tables and fk.child != fk.parent:
            children[fk.parent].add(fk.child)
    order: list[str] = []
    state: dict[str, int] = {}

    def visit(table: str, path: tuple[str, ...]) -> None:
        if state.get(table) == 2:
            return
        if state.get(table) == 1:
            raise ResetRefused(f"foreign-key cycle: {' -> '.join((*path, table))}")
        state[table] = 1
        for child in sorted(children[table]):
            visit(child, (*path, table))
        state[table] = 2
        order.append(table)

    for table in sorted(tables):
        visit(table, ())
    # `order` lists each table after every table that references it: children first
    return [Step(t, via.get(t)) for t in order]


def _table(qualified: str, *cols: str) -> sa.TableClause:
    schema, name = qualified.split(".", 1)
    return sa.table(name, *(sa.column(c) for c in cols), schema=schema)


def _delete(step: Step, shop_id: uuid.UUID) -> sa.Delete:
    if step.via is None:
        t = _table(step.table, "shop_id")
        return sa.delete(t).where(t.c.shop_id == shop_id)
    fk = step.via
    child = _table(fk.child, *fk.child_cols)
    parent = _table(fk.parent, "shop_id", *fk.parent_cols)
    keys = sa.select(*(parent.c[c] for c in fk.parent_cols)).where(parent.c.shop_id == shop_id)
    target = (
        child.c[fk.child_cols[0]]
        if len(fk.child_cols) == 1
        else sa.tuple_(*(child.c[c] for c in fk.child_cols))
    )
    return sa.delete(child).where(target.in_(keys))


async def read_catalogue(session: AsyncSession) -> tuple[set[str], list[ForeignKey]]:
    shop_tables = {f"{s}.{t}" for s, t in (await session.execute(_SHOP_TABLES)).all()}
    fks = [
        ForeignKey(f"{cs}.{ct}", f"{ps}.{pt}", tuple(cc), tuple(pc))
        for cs, ct, ps, pt, cc, pc in (await session.execute(_FOREIGN_KEYS)).all()
    ]
    return shop_tables, fks


async def wipe(
    factory: async_sessionmaker[AsyncSession], shop_id: uuid.UUID, *, commit: bool
) -> ResetReport:
    """Delete the shop's rows (``commit=False``: count them and roll back)."""
    from juli_backend.database.tenant_context import with_shop_scope
    from scripts.sample_shop.loader import _has_credentials, check_target

    report = ResetReport(shop_id, committed=False)
    async with factory() as session:
        from juli_backend.database import Shop

        shop = await session.get(Shop, shop_id)
        if shop is None:
            raise ResetRefused(f"shop {shop_id} does not exist")
        check_target(
            shop.id,
            platform=shop.platform,
            shopee_shop_id=shop.shopee_shop_id,
            has_credentials=await _has_credentials(session, shop.id),
        )
        steps = plan_deletes(*await read_catalogue(session))
        async with with_shop_scope(session, shop_id):
            for step in steps:
                result = await session.execute(_delete(step, shop_id))
                if result.rowcount:
                    report.deleted[step.table] = result.rowcount
        if commit:
            await session.commit()
            report.committed = True
        else:
            await session.rollback()
    return report


__all__ = [
    "KEEP_TABLES",
    "ForeignKey",
    "ResetRefused",
    "ResetReport",
    "Step",
    "plan_deletes",
    "read_catalogue",
    "wipe",
]
