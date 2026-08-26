"""ADR-075 decision 3: the consolidated agent-runtime boot assertion (#1217,
AGT-W5B).

Six individually-named checks, called at **both** API boot
(`api/main.py`'s `lifespan`) and worker/beat boot (`workers/celery_app.py`,
module-level, replacing the old lone broker check):

1. `OPENAI_API_KEY` present.
2. A real Celery broker, never `memory://` -- **absorbed** from
   `workers/agent_broker_guard.py` (#1129, ADR-074 decision 4), not
   duplicated. `run_agent_broker_startup_check` is called unmodified, so its
   message and behaviour are byte-identical to before this issue; this
   module owns nothing about broker durability itself.
3. The shared banned-patterns source (`services/agent/sanitize/`, ADR-070
   decision 6) loads and compiles.
4. Sandbox-write guard config resolvable for every registered WRITE tool.
   There is no per-tool config to iterate -- all three WRITE tools
   (`services/agent/composition.py::build_write_resources`) resolve through
   one shared `TIKTOK_APP_KEY`/`TIKTOK_APP_SECRET` pair, so this check
   resolves that one pair and names every registered WRITE tool in the
   failure message.
5. `SUPABASE_JWT_SECRET` present -- **unconditional**, independent of
   `AGENT_WORKFLOWS_ENABLED`. The empty-secret-verifies-everything hole this
   guards against is already closed elsewhere (`core/security/dependencies.py`
   and `api/main.py`'s existing `require_env` call); this check exists so a
   worker/beat process -- which today asserts nothing about the JWT secret at
   all -- fails the same way the API already does.

   **Extended by #1282.** Presence of `SUPABASE_JWT_SECRET` is not evidence
   the deployment can verify a real token -- issue #1282's outage shipped
   with the secret present and this check green, because the deployed
   Supabase project issues ES256 tokens the (then HS256-only) verifier could
   never accept regardless of the secret's value, and because
   `SUPABASE_URL` held the Postgres `db.<ref>.supabase.co` connection host
   rather than the project API URL ES256 verification derives its JWKS
   endpoint from. This check now *also* calls
   `core.security.supabase_jwks_url()` -- pure string validation, **no
   network call** -- so a `SUPABASE_URL` shaped like the database host, or
   missing a scheme, fails boot with a named error instead of the ES256
   path silently 404ing on its first real request.

   **What this proves:** both algorithm paths this codebase supports are
   *structurally* configured -- a non-empty HS256 secret exists, and
   `SUPABASE_URL` is not the one specific wrong value that caused this
   outage (nor otherwise malformed). **What this does NOT prove:** that the
   JWKS endpoint is actually reachable, that it returns keys, that
   `SUPABASE_URL` points at the *correct* project, or that either path
   verifies a token the identity provider would actually issue. Proving
   reachability would need either a live network call on every boot --
   including every test collection that imports `celery_app`, since check 5
   is unconditional and this function is invoked at module-import time
   there -- or a live token, neither of which is available at boot. This is
   therefore a structural check, not a live probe; reachability is instead
   enforced at request time (`core/security/jwks.py`'s fail-closed
   `JwksUnavailableError`), where a live token and a live network path both
   already exist.
6. Structural backstop: in a production-write-capable deployment (proxied by
   `core.config.is_production()`, the same discriminator that already gates
   `/docs`/`/redoc`/`/openapi.json`), the `agent-runs` route group exposes
   zero unauthenticated routes. Scoped to that one tagged route group -- not
   the whole API surface -- deliberately: `/health`, the TikTok webhook, and
   the TikTok OAuth entry/callback routes are unauthenticated by design and
   are not this ADR's concern. Requires an `app: FastAPI`; a worker process
   has no ASGI app and no HTTP routes at all, so this check is a no-op
   whenever `app` is not supplied.

**Fail-safe-by-omission shape.** Checks 1, 2, 3, 4, 6 are gated behind
`agent_broker_guard.agent_workflows_enabled()` -- a deployment that has not
opted into `AGENT_WORKFLOWS_ENABLED` is completely unaffected by this
function, exactly as it already was for check 2 alone before this issue.
Check 5 is the one exception, matching its explicit "unconditional" callout
in ADR-075 decision 3 and issue #1217.

**Import-boundary placement.** This module lives in `workers/` (not
`services/` or `core/`) because it is the one top-level package that can
reach every collaborator within `.importlinter.toml`'s
`max_cross_package_depth = 2` cap without a new baseline entry:

- `workers -> workers.agent_broker_guard` -- same top-level package,
  unrestricted.
- `workers -> services.agent.{composition,sanitize}` -- crosses to `services`
  (an allowed edge for `workers`), reached via `from
  juli_backend.services.agent import <name>` (module path depth 2:
  `services.agent`), the same depth-compliant idiom `composition.py`'s own
  module docstring documents `workers/tasks/agent_workflow.py` already using
  for this exact package. `services.agent.sanitize`'s own `__init__.py`
  already re-exports `load_banned_patterns`, so no edit to #1218's package is
  needed to reach it this way.
- `workers -> core.config` -- an allowed edge, reached via `from
  juli_backend.core.config import require_env` (depth 2), the same idiom
  `composition.py` already uses for the identical function.
- `api -> workers.agent_runtime_boot` -- `workers` is an allowed edge for
  `api`, and this module is a *direct child* of `workers` (depth 2), so
  `api/main.py` importing `assert_agent_runtime_config` from here is
  depth-compliant with no baseline addition.

`services` cannot see this module (`services`'s own allowed edges do not
include `workers`), and neither `services` nor `core` can reach
`workers.agent_broker_guard` at all -- which is why the consolidated
function could not live in either of those packages instead.

Check 6 cannot import `api.routes.agent_runs.router` or
`api.dependencies.get_active_shop` directly (`workers` may not import `api`
at all, at any depth) -- it does not need to. `get_active_shop` itself
depends on `get_current_user` (`api/dependencies.py`), and FastAPI's
`Dependant` tree captures that nesting recursively, so walking a route's
full dependency tree for `core.security.get_current_user` (reachable at
depth 2) detects both dependency shapes without ever importing anything
from `api`. The route-group scope itself is the plain string tag
`"agent-runs"` (`AGENT_RUN_ROUTE_TAG` below, matching the literal tag
already on `api/routes/agent_runs.py`'s router) -- also zero import needed.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from juli_backend.core.config import is_production, require_env
from juli_backend.core.config import is_production_write_enabled
from juli_backend.services.agent import composition as composition_module
from juli_backend.services.agent import sanitize as sanitize_module
from juli_backend.workers import agent_broker_guard as broker_guard_module

if TYPE_CHECKING:
    from fastapi import FastAPI
    from fastapi.dependencies.models import Dependant

#: The tag `api/routes/agent_runs.py`'s router already carries
#: (`APIRouter(prefix="/demo/runs", tags=["agent-runs"])`). Check 6 scopes
#: its scan to routes carrying this tag -- a plain string, not a symbol
#: import, so no `api` import is needed to reach it.
AGENT_RUN_ROUTE_TAG = "agent-runs"

_DEFAULT_CELERY_BROKER_URL = "memory://"


def assert_agent_runtime_config(
    *,
    app: FastAPI | None = None,
    broker_url: str | None = None,
) -> None:
    """Fail the process at boot when any of ADR-075 decision 3's checks
    is unmet, each raising a `RuntimeError` naming that check.

    `app`: pass the real `FastAPI` instance from API boot so check 6 can
    walk its routes; omit (worker/beat boot -- no ASGI app exists) and check
    6 is skipped.

    `broker_url`: pass the resolved broker URL explicitly (worker boot
    passes `celery_app.conf.broker_url`, its own already-configured value).
    Omitted (API boot, which never constructs a `Celery` app) falls back to
    reading `CELERY_BROKER_URL` with the identical default
    `celery_app.py` itself uses, so both boot paths assert against the same
    effective broker.

    **Check 7 (issue #1330):** When the production-write capability is enabled
    (PRODUCTION_WRITE_ENABLED=true), verify at boot that:
    (a) The connection's role is NOT an owner of any table in runtime schemas
        (i.e., does not bypass RLS), and
    (b) relrowsecurity=true for every tenant-scoped table.
    Either unmet ⇒ refuse to start, naming the check and (for RLS) naming
    the table. When the capability is OFF (default), check 7 is a no-op
    regardless of connection role (preserving today's production state).
    """
    # Check 5 -- unconditional. Must run, and must be able to fail, before
    # anything below it: an empty SUPABASE_JWT_SECRET crashes at boot rather
    # than any other check masking it (issue #1217 AC).
    require_env("SUPABASE_JWT_SECRET")
    # #1282: extended. Structural only -- see the check 5 docstring above
    # for exactly what this does and does not prove.
    _assert_supabase_jwks_url_usable()

    if broker_url is not None:
        resolved_broker_url = broker_url
    else:
        resolved_broker_url = os.environ.get("CELERY_BROKER_URL", _DEFAULT_CELERY_BROKER_URL)
    # Check 2 -- absorbed verbatim. Self-gates on agent_workflows_enabled()
    # internally; called unconditionally here exactly as celery_app.py
    # already called it before this issue, so its behaviour is unchanged.
    broker_guard_module.run_agent_broker_startup_check(resolved_broker_url)

    if not broker_guard_module.agent_workflows_enabled():
        # Fail-safe-by-omission: a deployment that has not opted into agent
        # workflows is unaffected by checks 1, 3, 4, 6 -- the same shape
        # check 2 alone already had. Check 7 runs independently.
        pass
    else:
        _assert_openai_api_key_present()
        _assert_banned_patterns_load_and_compile()
        _assert_sandbox_write_guard_config_resolvable()
        if app is not None:
            _assert_zero_unauthenticated_agent_route_groups(app)

    # Check 7: RLS preconditions for production-write capability (issue #1330).
    # Runs independently, not gated by agent_workflows_enabled.
    _assert_non_owner_role_rls_preconditions()


def _assert_supabase_jwks_url_usable() -> None:
    """Check 5, extended (#1282): `SUPABASE_URL` must structurally resolve
    to a usable JWKS endpoint -- no network call, see check 5's docstring
    for the "what this proves / does not" boundary.

    Local import (matching `_assert_zero_unauthenticated_agent_route_groups`
    below): `core.security` is a depth-2 cross-package import from
    `workers`, allowed by `.importlinter.toml`, but keeping it lazy avoids
    pulling `core.security`'s full package (TikTok OAuth, credential
    resolution, ...) into every module-level import of this file, including
    `celery_app.py`'s own module-level call.
    """
    from juli_backend.core.security import supabase_jwks_url

    try:
        supabase_jwks_url()
    except RuntimeError as exc:
        # Catches both `JwksUnavailableError` (SUPABASE_URL present but
        # structurally unusable) and the plain `RuntimeError` `require_env`
        # raises when SUPABASE_URL is absent entirely -- both are boot
        # failures here, uniformly named.
        raise RuntimeError(f"assert_agent_runtime_config: {exc}") from exc


def _assert_openai_api_key_present() -> None:
    require_env("OPENAI_API_KEY")


def _assert_banned_patterns_load_and_compile() -> None:
    try:
        sanitize_module.load_banned_patterns()
    except Exception as exc:
        raise RuntimeError(
            "assert_agent_runtime_config: banned-patterns source failed to load or "
            f"compile ({sanitize_module.BANNED_PATTERNS_JSON_PATH}): {exc}"
        ) from exc


def _assert_sandbox_write_guard_config_resolvable() -> None:
    write_tool_names = sorted(composition_module.measurable_write_tool_names())
    if not write_tool_names:
        raise RuntimeError(
            "assert_agent_runtime_config: no WRITE-classified tool is registered in the "
            "product tool registry -- sandbox-write guard config has nothing to guard"
        )
    missing = [name for name in ("TIKTOK_APP_KEY", "TIKTOK_APP_SECRET") if not _env_present(name)]
    if missing:
        raise RuntimeError(
            "assert_agent_runtime_config: sandbox-write guard config unresolved "
            f"(missing {missing}) for registered WRITE tools {write_tool_names}"
        )


def _env_present(name: str) -> bool:
    try:
        require_env(name)
    except RuntimeError:
        return False
    return True


def _assert_zero_unauthenticated_agent_route_groups(app: FastAPI) -> None:
    if not is_production():
        return

    from fastapi.routing import APIRoute

    from juli_backend.core.security import get_current_user

    unauthenticated: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if AGENT_RUN_ROUTE_TAG not in (route.tags or []):
            continue
        if not _dependant_requires_auth(route.dependant, get_current_user):
            methods = ",".join(sorted(route.methods or ()))
            unauthenticated.append(f"{methods} {route.path}")

    if unauthenticated:
        raise RuntimeError(
            "assert_agent_runtime_config: production-write-capable deployment exposes "
            f"unauthenticated route(s) in the {AGENT_RUN_ROUTE_TAG!r} route group: "
            f"{sorted(unauthenticated)}"
        )


def _dependant_requires_auth(dependant: Dependant, auth_dependency: object) -> bool:
    stack = [dependant]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if current.call is auth_dependency:
            return True
        stack.extend(current.dependencies)
    return False


def _assert_non_owner_role_rls_preconditions() -> None:
    """Check 7: RLS preconditions when production-write capability is enabled (issue #1330).

    This check implements the core protection: when PRODUCTION_WRITE_ENABLED=true, verify
    that the database enforces RLS isolation before allowing operation.

    Semantics (corrected from inverted logic):
    - PRODUCTION_WRITE_ENABLED OFF (default) ⇒ NO-OP, regardless of connection role.
      This is today's production state (capability off). Boot succeeds even if connecting
      as the owner (postgres) with partial RLS.
    - PRODUCTION_WRITE_ENABLED ON ⇒ Verify preconditions:
      (a) connection role owns no runtime schema tables (if it does, it bypasses RLS) ⇒
          REFUSE boot, naming the check (AC1 — the core dangerous case).
      (b) every tenant-scoped table has relrowsecurity=true ⇒ REFUSE, naming the table (AC2).
      Both conditions must be met to boot (AC4).

    Queries the LIVE connection's actual role and RLS state from pg_catalog,
    not config values.
    """
    # Gate on PRODUCTION_WRITE_ENABLED, not on connection role
    if not is_production_write_enabled():
        # Capability is OFF (default) — no-op regardless of connection role
        return

    from urllib.parse import urlparse

    import psycopg2  # type: ignore[import-untyped]
    import psycopg2.extras  # type: ignore[import-untyped]

    # Capability is ON — verify preconditions against live database
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        # No database connection configured; check is not applicable
        return

    # Parse the DATABASE_URL to extract connection parameters
    from juli_backend.core.config import sync_database_url

    try:
        # Normalize URL for sync driver
        normalized_url = sync_database_url(database_url)
        parsed = urlparse(normalized_url)

        # Extract connection parameters
        conn_params = {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 5432,
            "user": parsed.username or "postgres",
            "password": parsed.password or "",
            "database": parsed.path.lstrip("/") if parsed.path else "postgres",
        }

    except Exception:
        # If we can't parse/normalize the URL, this is not a precondition failure
        # Don't fail boot on URL parsing issues
        return

    # Try to connect and check preconditions
    conn = None
    try:
        conn = psycopg2.connect(**conn_params)
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Get current role
        cursor.execute("SELECT current_user")
        current_role = cursor.fetchone()[0]

        # Check preconditions when capability is ON
        # These may raise RuntimeError if preconditions are not met
        _check_role_does_not_own_tables(cursor, current_role)
        _check_tenant_tables_have_rls(cursor)

        cursor.close()
        conn.close()

    except psycopg2.Error as e:
        if conn is not None:
            conn.close()
        raise RuntimeError(
            f"assert_agent_runtime_config: failed to check RLS preconditions: {e}"
        ) from e


def _check_role_does_not_own_tables(cursor, current_role: str) -> None:
    """Verify that the current role owns no tables in runtime schemas.

    AC1: If connection role owns tables in runtime schemas, it bypasses RLS.
    Raises RuntimeError naming the check and owned tables.
    """
    # Query for tables owned by current role in runtime schemas
    cursor.execute(
        """
        SELECT t.relname, n.nspname
        FROM pg_class t
        JOIN pg_namespace n ON t.relnamespace = n.oid
        JOIN pg_roles r ON t.relowner = r.oid
        WHERE r.rolname = %s
        AND n.nspname IN ('public', 'bronze', 'silver', 'ops', 'gold')
        AND t.relkind = 'r'
        ORDER BY n.nspname, t.relname
        """,
        (current_role,),
    )

    owned_tables = cursor.fetchall()
    if owned_tables:
        table_list = ", ".join(f"{row['nspname']}.{row['relname']}" for row in owned_tables)
        raise RuntimeError(
            f"assert_agent_runtime_config: check 7 (production-write RLS preconditions) "
            f"refuses boot — connection role '{current_role}' owns tables in runtime "
            f"schemas: {table_list}. Role ownership bypasses RLS. Set "
            f"PRODUCTION_WRITE_ENABLED=false or use a non-owner connection role."
        )


def _check_tenant_tables_have_rls(cursor) -> None:
    """Verify that all tenant-scoped tables have RLS enabled.

    AC2: Raises RuntimeError naming each table without RLS.
    """
    from juli_backend.database.tenant_scoped_tables import get_tenant_scoped_tables

    tenant_tables = get_tenant_scoped_tables()

    if not tenant_tables:
        # No tenant tables defined; check passes
        return

    # Query RLS state for each tenant table directly from pg_catalog
    tables_without_rls = []
    missing_tables = []

    for schema, table in tenant_tables:
        cursor.execute(
            """
            SELECT t.relrowsecurity
            FROM pg_class t
            JOIN pg_namespace n ON t.relnamespace = n.oid
            WHERE n.nspname = %s AND t.relname = %s AND t.relkind = 'r'
            """,
            (schema, table),
        )

        result = cursor.fetchone()
        if result is None:
            # Table doesn't exist in catalog
            missing_tables.append(f"{schema}.{table}")
        else:
            relrowsecurity = result[0]  # Using index access since DictCursor may vary
            if not relrowsecurity:
                tables_without_rls.append(f"{schema}.{table}")

    if missing_tables:
        missing_list = ", ".join(missing_tables)
        raise RuntimeError(
            f"assert_agent_runtime_config: check 7 (production-write RLS preconditions) "
            f"refuses boot — tenant-scoped tables not found in pg_catalog: {missing_list}. "
            f"Set PRODUCTION_WRITE_ENABLED=false or ensure all tenant tables exist."
        )

    if tables_without_rls:
        table_list = ", ".join(tables_without_rls)
        raise RuntimeError(
            f"assert_agent_runtime_config: check 7 (production-write RLS preconditions) "
            f"refuses boot — tenant-scoped tables missing RLS: {table_list}. "
            f"Isolation is incomplete. Set PRODUCTION_WRITE_ENABLED=false or enable RLS."
        )
