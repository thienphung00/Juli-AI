"""The one definition of "this test needs a real Postgres".

Thirty modules used to define ``_database_url`` and ``requires_postgres``
each; a change to the gate (say, making it fail closed in CI) had thirty
places to land. Import these instead.

Today the gate is *fail-open*: without a reachable ``DATABASE_URL`` the test
skips, in CI too. ``tests/conftest.py`` already refuses a non-disposable URL in
CI; refusing a *missing* one is the next step and is blocked on the
``-k "contract or boundary or ownership"`` job in ``pr.yml``, which runs unit
tests with no Postgres service and relies on these skips. Consolidating the
definition here is the prerequisite for flipping it in one place.
"""

from __future__ import annotations

import os

import pytest


def database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def postgres_reachable() -> bool:
    return database_url().startswith("postgresql")


requires_postgres = pytest.mark.skipif(
    not postgres_reachable(),
    reason="DATABASE_URL does not point at a Postgres database",
)

__all__ = ["database_url", "postgres_reachable", "requires_postgres"]
