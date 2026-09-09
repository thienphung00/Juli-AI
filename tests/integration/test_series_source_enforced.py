"""The database enforces `series_source`, not just the model (#1766, ADR-099).

WHY THIS IS INTEGRATION-TIER. The model-level tests beside this one assert that
the attribute exists, that a Python object can carry it, and that a constraint
appears in `__table_args__`. All three pass against a model whose column the
database never received — `hasattr` and `__table_args__` are declarations, and a
declaration is not an enforcement.

The issue's acceptance criterion is behavioural: *"a write without
`series_source` raises rather than defaulting"*. Only a real Postgres can answer
that, for the same reason #1675 was invisible to the unit substrate — SQLite does
not enforce what this column is for.

WHAT THE NO-DEFAULT BUYS. A default would make the safe-looking value the one you
get by omission, for a field whose entire job is preventing a synthetic reading
from being mistaken for a measurement. The first test below is the one that
would notice a default being added back.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text

from tests.support.postgres import database_url, requires_postgres

pytestmark = requires_postgres

_BASE = (
    "insert into impact_readings "
    "(id, tool_execution_id, metric, kind, confidence, computed_at{extra_cols}) "
    "values (:i, :t, 'gmv', 'preliminary', 'suppressed', now(){extra_vals})"
)


@pytest.fixture
def conn():
    engine = create_engine(database_url())
    with engine.connect() as c:
        yield c
        c.rollback()
    engine.dispose()


def test_the_column_is_not_null_with_no_default(conn) -> None:
    """Read the catalog, not the model. This is the shape the migration produced."""
    row = conn.execute(
        text(
            "select is_nullable, column_default from information_schema.columns "
            "where table_name='impact_readings' and column_name='series_source'"
        )
    ).fetchone()
    assert row is not None, "series_source is absent from the deployed schema"
    assert row[0] == "NO", "series_source must be NOT NULL"
    assert row[1] is None, (
        f"series_source must have NO default; found {row[1]!r}. A default makes the "
        f"safe-looking value the one you get by forgetting, which inverts the point."
    )


def test_a_write_without_series_source_is_refused(conn) -> None:
    """The acceptance criterion, stated as behaviour.

    Every other required column is supplied, so the refusal can only be about
    `series_source` — an earlier version of this check omitted several columns
    and 'passed' on a `tool_execution_id` violation instead, proving nothing.
    """
    with pytest.raises(Exception) as excinfo:
        conn.execute(
            text(_BASE.format(extra_cols="", extra_vals="")),
            {"i": str(uuid.uuid4()), "t": str(uuid.uuid4())},
        )
    assert "series_source" in str(excinfo.value), (
        f"the refusal must be about series_source, not an unrelated NOT NULL column: "
        f"{str(excinfo.value)[:200]}"
    )


def test_an_undeclared_value_is_refused(conn) -> None:
    """`measured | synthetic` and nothing else — a third value would be unclassifiable."""
    with pytest.raises(Exception) as excinfo:
        conn.execute(
            text(_BASE.format(extra_cols=", series_source", extra_vals=", 'fabricated'")),
            {"i": str(uuid.uuid4()), "t": str(uuid.uuid4())},
        )
    assert "check" in str(excinfo.value).lower(), (
        f"expected the check constraint to reject it: {str(excinfo.value)[:160]}"
    )
