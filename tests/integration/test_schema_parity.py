"""ORM model vs migration-built schema parity guard (#943 follow-on).

Two bugs shipped from the identical root cause: a model declared a column
(``products.revenue``/``units_sold``, then ``inventory_items.velocity``) that
no migration ever added, and every unit test still passed because
``tests/unit/conftest.py``'s ``engine`` fixture builds its schema straight off
``Base.metadata.create_all`` — it does not run the Alembic chain, so the model
and the migration chain can diverge indefinitely with nothing to notice.

This test closes that gap: it builds a real schema by running the full
Alembic migration chain against disposable Postgres (the same
``postgres_at_head`` fixture ``tests/integration/test_migrations.py`` already
uses to reach ``head``), then compares it against ``Base.metadata`` — the same
source every model-driven unit-test fixture in this repo trusts. It is
deliberately data-driven off ``Base.metadata``: it enumerates whatever tables
and columns the ORM models declare *right now*, so a column added to a model
tomorrow with no accompanying migration fails this test unaided, with no
hardcoded table/column list to keep in sync.

Direction chosen: model-not-in-db is a **hard failure** (a blocking test);
db-not-in-model is a **warning only** (a separate, always-passing test that
emits a ``pytest.warns``-visible ``UserWarning``). Rationale:

  - Model-in-DB-missing means an ORM ``SELECT``/``INSERT`` against that column
    will 500 in production the instant it is exercised — this is exactly the
    #943 class of bug, and it must block.
  - DB-has-extra-column-not-in-model is not automatically wrong: a column can
    legitimately outlive its model field during a deprecation window (drop
    the model reference first, drop the column in a later migration once
    nothing depends on it). Failing the build on that would make the guard
    noisy on a normal, safe deprecation sequence, and a guard the team has to
    silence to deploy is a guard that stops getting looked at.

Schemas covered: every schema an ORM model actually declares via
``__table_args__ = {"schema": ...}`` — ``bronze``, ``silver``, ``gold``,
``ops`` — plus ``public`` for everything else. The Alembic chain creates all
four (revisions 021/022/023/024/025), and ``test_migrations.py`` already
depends on them existing, so there is no schema this guard needs to skip.
"""

from __future__ import annotations

import warnings

import pytest
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

# Importing the models module is what registers every mapped class on
# Base.metadata. Without it Base.metadata.sorted_tables is EMPTY, this guard
# iterates nothing, and both tests below pass vacuously — a guard that cannot
# fail. Do not remove; _assert_metadata_populated() enforces it at runtime.
import juli_backend.models.models  # noqa: F401,E402  (side-effect import)
from juli_backend.database.database import Base
from tests.integration.test_migrations import postgres_at_head, requires_postgres  # noqa: F401

__all__ = ["postgres_at_head", "requires_postgres"]

# Deliberately its OWN marker, distinct from `migration_heavy` (#943/#948).
# `migration_heavy` covers the expensive seeded round-trip/restore-drill suite
# that only runs on merge_group or migration-path PRs. This guard is a single
# Alembic-chain replay + a metadata diff — cheap enough to run on every PR —
# so it must NOT be deselected by `-m "not migration_heavy"` in the issue-tier
# `test` job (.github/workflows/pr.yml). `@requires_postgres` (per test, below)
# still makes it skip cleanly wherever no DATABASE_URL/Postgres is reachable.
pytestmark = pytest.mark.schema_parity


MIN_EXPECTED_MODEL_TABLES = 20


def _assert_metadata_populated() -> None:
    """Fail loudly if Base.metadata is empty or suspiciously small.

    Guards the guard: if the models side-effect import above is ever dropped or
    reordered away, every parity assertion would silently compare an empty set
    and report success. That failure mode is worse than no test at all, because
    it looks like coverage.
    """
    count = len(Base.metadata.sorted_tables)
    assert count >= MIN_EXPECTED_MODEL_TABLES, (
        f"Base.metadata declares only {count} tables (expected >= "
        f"{MIN_EXPECTED_MODEL_TABLES}). The ORM models were not imported, so this "
        "parity guard would pass vacuously. Check the "
        "`import juli_backend.models.models` side-effect import at the top of this module."
    )


def _model_tables_by_schema() -> dict[str, dict[str, set[str]]]:
    """{db_schema: {table_name: {column_name, ...}}} for every ORM-mapped table."""
    grouped: dict[str, dict[str, set[str]]] = {}
    for table in Base.metadata.sorted_tables:
        db_schema = table.schema or "public"
        grouped.setdefault(db_schema, {})[table.name] = {col.name for col in table.columns}
    return grouped


@requires_postgres
def test_migration_schema_has_every_model_table_and_column(postgres_at_head: Engine):
    """Every table and column declared on an ORM model must exist in the
    Alembic-migration-built schema. This is what would have caught both
    products.revenue/units_sold (#943) and inventory_items.velocity years
    before either one crashed production.
    """
    _assert_metadata_populated()
    inspector = inspect(postgres_at_head)
    model_by_schema = _model_tables_by_schema()

    missing_tables: list[str] = []
    missing_columns: list[str] = []

    for db_schema, tables in sorted(model_by_schema.items()):
        db_table_names = set(inspector.get_table_names(schema=db_schema))
        for table_name, model_columns in sorted(tables.items()):
            qualified = f"{db_schema}.{table_name}" if db_schema != "public" else table_name
            if table_name not in db_table_names:
                missing_tables.append(qualified)
                continue
            db_column_names = {
                col["name"] for col in inspector.get_columns(table_name, schema=db_schema)
            }
            for column_name in sorted(model_columns):
                if column_name not in db_column_names:
                    missing_columns.append(f"{qualified}.{column_name}")

    failures: list[str] = []
    if missing_tables:
        failures.append(
            "Tables declared on an ORM model but missing from the migration-built "
            "schema (add a migration for each):\n  " + "\n  ".join(missing_tables)
        )
    if missing_columns:
        failures.append(
            "Columns declared on an ORM model but missing from the migration-built "
            "schema (add a migration for each — this is the #943 bug class):\n  "
            + "\n  ".join(missing_columns)
        )

    assert not failures, "\n\n".join(failures)


@requires_postgres
def test_migration_schema_extra_columns_not_on_model_is_informational_only(
    postgres_at_head: Engine,
):
    """Report DB columns/tables absent from the ORM model as a warning, never
    a failure — see module docstring for why this direction is non-blocking.
    """
    _assert_metadata_populated()
    inspector = inspect(postgres_at_head)
    model_by_schema = _model_tables_by_schema()

    extra: list[str] = []

    for db_schema, tables in sorted(model_by_schema.items()):
        db_table_names = set(inspector.get_table_names(schema=db_schema))
        model_table_names = set(tables.keys())
        for table_name in sorted(db_table_names - model_table_names):
            qualified = f"{db_schema}.{table_name}" if db_schema != "public" else table_name
            extra.append(f"{qualified} (table)")

        for table_name in sorted(db_table_names & model_table_names):
            qualified = f"{db_schema}.{table_name}" if db_schema != "public" else table_name
            db_column_names = {
                col["name"] for col in inspector.get_columns(table_name, schema=db_schema)
            }
            model_column_names = tables[table_name]
            # alembic_version and similar bookkeeping tables aren't ORM-mapped
            # at all, so they're already excluded by only walking model tables.
            for column_name in sorted(db_column_names - model_column_names):
                extra.append(f"{qualified}.{column_name}")

    if extra:
        warnings.warn(
            "Columns/tables present in the migration-built schema but absent from "
            "the ORM model (informational only — legitimate during a deprecation "
            "window; not a build failure):\n  " + "\n  ".join(extra),
            UserWarning,
            stacklevel=1,
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
