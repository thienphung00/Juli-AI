"""The enumerations cross tenants; their callers still cannot (#1487 / ADR-089).

Three `SECURITY DEFINER` functions, which is to say three deliberate RLS bypasses. Each exists
so a fleet-scoped beat task can learn *which* items to act on without the runtime role being able
to read across tenants itself.

That makes this module a check on a privilege boundary rather than on a query, and it asserts
three separate things:

  1. **The bypass works.** The function returns rows for BOTH tenants — otherwise it is not an
     enumeration and the task it serves still does nothing.
  2. **The bypass is confined.** The SAME session that just called the function still sees only
     its own tenant when it reads the underlying table directly. If that fails, the definer
     right has leaked out of the function and into the session, and every RLS guarantee behind
     it is void.
  3. **The bypass is not public.** Postgres grants `EXECUTE` to `PUBLIC` by default on a new
     function; on one of these that would hand cross-tenant reads to every role in the cluster.

It also pins the returned column list. ADR-089 decision 3 restricts these to identifiers and
scheduling metadata — never tokens, payloads, analytics values or PII — and a returned column
list asserted from the catalog fails CI on a later widening, where a review might not.

The module is in `_ISOLATED_DATABASE_MODULES` because it uses the seeding fixture from #1483.
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest
from sqlalchemy import text

from tests.integration.two_tenant import ACTIVE_RUNS_PER_TENANT, juli_app_session

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

# What each function is permitted to return. ADR-089 decision 3: identifiers and
# scheduling metadata only. A name appearing here that carries tenant data is a
# defect in the migration, not in this list.
EXPECTED_COLUMNS: dict[str, set[str]] = {
    "enumerate_expiring_credentials": {"out_credential_id", "out_shop_id", "out_expires_at"},
    "enumerate_measurable_executions": {"out_execution_id", "out_shop_id", "out_updated_at"},
    "enumerate_active_workflow_runs": {
        "out_run_id",
        "out_shop_id",
        "out_status",
        "out_created_at",
        "out_running_seconds_elapsed",
    },
}

# Substrings that must never appear in a returned column name. Crude on purpose:
# the point is that widening the row type trips something, and a reviewer who
# adds `payload_json` should hit this before CI goes green.
FORBIDDEN_FRAGMENTS = ("token", "payload", "secret", "phone", "email", "revenue", "name")


def test_execute_is_not_granted_to_public(owner_engine) -> None:
    """The single most important property in the migration.

    A SECURITY DEFINER function left at the default PUBLIC grant hands its
    bypass to every role in the cluster — including read-only and per-developer
    roles that do not exist yet.
    """
    with owner_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT proname, has_function_privilege('public', oid, 'EXECUTE'), "
                "       has_function_privilege('juli_app', oid, 'EXECUTE'), prosecdef "
                "  FROM pg_proc WHERE proname = ANY(:names)"
            ),
            {"names": list(EXPECTED_COLUMNS)},
        ).all()

    assert len(rows) == len(EXPECTED_COLUMNS), f"expected all three functions, found {rows}"
    for name, public_can, app_can, is_definer in rows:
        assert is_definer, f"{name} is not SECURITY DEFINER, so it cannot enumerate at all"
        assert not public_can, (
            f"PUBLIC can execute {name}. It is SECURITY DEFINER and reads across tenants, so "
            "the default PUBLIC grant hands that bypass to every role in the cluster."
        )
        assert app_can, f"juli_app cannot execute {name}, so the task it serves cannot enumerate"


def test_each_function_returns_identifiers_and_nothing_else(owner_engine) -> None:
    """Pin the row type, read from the catalog.

    ADR-089 decision 3 restricts these to identifiers and scheduling metadata. A
    later change that adds `payload_json` to make a caller simpler is exactly
    the widening this asserts against.
    """
    with owner_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT p.proname, a.parameter_name "
                "  FROM pg_proc p "
                "  JOIN information_schema.parameters a "
                "    ON a.specific_name = p.proname || '_' || p.oid "
                # Postgres reports a RETURNS TABLE function's columns with mode
                # 'OUT' here, not 'TABLE'; accepting both keeps this working
                # across versions rather than silently matching nothing.
                " WHERE p.proname = ANY(:names) AND a.parameter_mode IN ('OUT', 'TABLE')"
            ),
            {"names": list(EXPECTED_COLUMNS)},
        ).all()

    actual: dict[str, set[str]] = {}
    for name, parameter in rows:
        actual.setdefault(name, set()).add(parameter)

    assert actual == EXPECTED_COLUMNS, (
        f"the returned column lists have drifted from what ADR-089 permits.\n"
        f"expected: {EXPECTED_COLUMNS}\nactual:   {actual}"
    )

    for name, columns in actual.items():
        leaking = [c for c in columns if any(f in c.lower() for f in FORBIDDEN_FRAGMENTS)]
        assert not leaking, (
            f"{name} returns {leaking}, which reads as tenant data rather than an identifier. "
            "These functions bypass RLS; what they return is what the bypass exposes."
        )


@pytest.mark.asyncio
async def test_the_enumeration_crosses_tenants(two_tenants) -> None:
    """Property 1: the bypass works.

    Asserted first, because the other two are satisfied by a function that
    returns nothing — and a function that returns nothing leaves the beat task
    exactly as broken as `system_scope` did.
    """
    tenant_a, tenant_b = two_tenants

    async with juli_app_session(tenant_a.shop_id) as session:
        shops = {
            row[0]
            for row in (
                await session.execute(
                    text("SELECT out_shop_id FROM enumerate_active_workflow_runs()")
                )
            ).all()
        }

    assert str(tenant_a.shop_id) in {str(s) for s in shops}, (
        "the enumeration did not return the calling tenant's own runs"
    )
    assert str(tenant_b.shop_id) in {str(s) for s in shops}, (
        "the enumeration returned only the calling tenant's runs, so it is not enumerating — "
        "the beat task it serves would still process one shop and miss the fleet"
    )


@pytest.mark.asyncio
async def test_the_bypass_does_not_leak_into_the_calling_session(two_tenants) -> None:
    """Property 2, and the one that would be a breach rather than a bug.

    Calling a definer function must not change what the CALLER can see. Same
    session, immediately afterwards, reading the same table directly: still one
    tenant.
    """
    tenant_a, tenant_b = two_tenants

    async with juli_app_session(tenant_a.shop_id) as session:
        enumerated = (
            await session.execute(text("SELECT count(*) FROM enumerate_active_workflow_runs()"))
        ).scalar()
        direct = (await session.execute(text("SELECT count(*) FROM public.workflow_runs"))).scalar()
        other = (
            await session.execute(
                text("SELECT count(*) FROM public.workflow_runs WHERE shop_id = :s"),
                {"s": str(tenant_b.shop_id)},
            )
        ).scalar()

    assert enumerated >= 2 * ACTIVE_RUNS_PER_TENANT, (
        f"the enumeration returned {enumerated} rows; both tenants seeded "
        f"{ACTIVE_RUNS_PER_TENANT} active runs each, so fewer than "
        f"{2 * ACTIVE_RUNS_PER_TENANT} means it is not crossing tenants"
    )
    assert direct == ACTIVE_RUNS_PER_TENANT, (
        f"a direct read returned {direct} rows. The session should still see only its own "
        f"tenant's {ACTIVE_RUNS_PER_TENANT} runs — {enumerated} through the function and "
        f"{ACTIVE_RUNS_PER_TENANT} without it. Seeing more means the definer right leaked "
        "out of the function into the session."
    )
    assert other == 0, "the calling session could read the other tenant's runs directly"


@pytest.mark.asyncio
async def test_the_credential_enumeration_returns_no_token_material(two_tenants) -> None:
    """The narrowest, most load-bearing exclusion.

    `TikTokCredentialRepo.list_expiring_within` hydrates DECRYPTED tokens. This
    enumeration deliberately does not, so the loop re-fetches per shop under
    real tenant context and decrypts there. A row type that carried the token
    would move decrypted credentials across the tenant boundary in the one call
    that is allowed to cross it.
    """
    tenant_a, _tenant_b = two_tenants
    # A real datetime, not a string: asyncpg binds by type and rejects a str
    # for a timestamp parameter outright.
    cutoff = datetime(2999, 1, 1)

    async with juli_app_session(tenant_a.shop_id) as session:
        result = await session.execute(
            text("SELECT * FROM enumerate_expiring_credentials(:c)"),
            {"c": cutoff},
        )
        columns = set(result.keys())
        rows = result.all()

    assert columns == EXPECTED_COLUMNS["enumerate_expiring_credentials"], (
        f"unexpected columns from the credential enumeration: {columns}"
    )
    assert len(rows) >= 4, (
        f"expected both tenants' credentials past a far-future cutoff, got {len(rows)}"
    )
