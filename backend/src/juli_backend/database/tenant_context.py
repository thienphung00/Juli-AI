"""Tenant context seam for setting app.current_shop_id and app.current_user_id.

Issue #1327, ADR-085 decision 2.

Every transaction-scoped unit of work sets app.current_shop_id and
app.current_user_id via SET LOCAL (transaction-scoped), failing closed in
Python before any SQL when tenant context is unavailable and system_scope()
is not active.

Two paths apply context:
1. HTTP requests: middleware calls _apply_tenant_context_to_session() directly
   on the request's session after resolving the shop and user via X-Shop-Id header
2. Celery tasks: set_tenant_context() sets contextvars; with_tenant_scope()
   applies context when the task opens a session

Fleet-wide work (reconcile, backfill, credential refresh, reaper) uses
system_scope() to opt out of tenant requirement, with logging.

The setter and fail-closed assertion are paired in the same module so they
cannot be separated by a revert.

Implementation:
- contextvars store shop_id and user_id for internal use (task paths)
- _apply_tenant_context_to_session() directly applies SET LOCAL to a session
  via parameterized set_config(name, val, is_local=true) to avoid SQL injection
- set_tenant_context() sets contextvars (used by Celery paths)
- system_scope() sets a flag to bypass the fail-closed assertion for fleet-wide work
"""

import contextvars
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Context variables: per-request/task tenant identity
_current_shop_id: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "current_shop_id", default=None
)
_current_user_id: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "current_user_id", default=None
)

# Global flag: when True, system_scope() is active and fail-closed is bypassed
_system_scope_active = False

# When True, `with_shop_scope()` is active: a shop id is still required, a user
# id is not.
#
# A ContextVar rather than a module global, deliberately. `_system_scope_active`
# above is a plain global, so two coroutines in the same event loop share it and
# one can clear the other's exemption while it is still inside its own scope.
# That hazard is pre-existing and recorded rather than copied — this flag is
# per-context and cannot leak between concurrent tasks.
_shop_scope_active: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "shop_scope_active", default=False
)


class TenantContextRequiredError(RuntimeError):
    """Raised when a tenant-scoped unit of work is attempted without
    tenant context and without system_scope() active.

    This is the fail-closed assertion: no transaction can proceed without
    either a tenant context (shop_id + user_id) or an explicit system_scope()
    exemption.
    """

    pass


def set_tenant_context(shop_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Set the tenant context for the current request/task.

    Called by:
    - HTTP routes via a dependency/middleware after user/shop resolution
    - Celery tasks after resolving the run's shop_id/user_id

    Args:
        shop_id: The active shop ID
        user_id: The authenticated user ID
    """
    _current_shop_id.set(shop_id)
    _current_user_id.set(user_id)


def get_tenant_context() -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Get the tenant context for the current request/task.

    Returns:
        (shop_id, user_id) tuple, or (None, None) if not set
    """
    return _current_shop_id.get(), _current_user_id.get()


def clear_tenant_context() -> None:
    """Clear the tenant context.

    Used for testing and by system_scope() to reset context.
    """
    _current_shop_id.set(None)
    _current_user_id.set(None)


async def _apply_tenant_context_to_session(
    session: AsyncSession,
    shop_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
) -> None:
    """Apply tenant context to a session by setting GUCs via set_config().

    Called on the HTTP path by the get_active_shop dependency (applied
    directly to the request's session after the shop is resolved), and by
    with_tenant_scope. Uses parameterized set_config() to avoid SQL injection.

    Args:
        session: AsyncSession to apply context to
        shop_id: The shop ID (from contextvars)
        user_id: The user ID (from contextvars)

    Raises:
        TenantContextRequiredError: If context is required but not available.
    """
    global _system_scope_active

    # Fail-closed in Python before any SQL.
    #
    # Three modes, narrowest first:
    #   - shop scope  — a shop id is required, a user id is not. The user GUC is
    #     left unset, so after #1467 it reads NULL and every user-keyed policy
    #     denies. That denial is the point, not a shortfall.
    #   - system scope — neither is required. A named, logged exemption for
    #     fleet work; ADR-089 is the constraint on what it may then read.
    #   - otherwise — both are required.
    shop_scope = _shop_scope_active.get()
    if shop_scope:
        _require_shop_for_shop_scope(shop_id)
    elif not _system_scope_active and (shop_id is None or user_id is None):
        raise TenantContextRequiredError(
            f"Tenant context required: shop_id={shop_id}, user_id={user_id}, "
            f"system_scope_active={_system_scope_active}"
        )

    # Use set_config() with parameterized queries to avoid SQL injection.
    # set_config(name, value, is_local) with is_local=true == SET LOCAL.
    try:
        bind = session.get_bind()
        dialect_name = bind.dialect.name if hasattr(bind, "dialect") else "postgresql"

        # Skip GUC setting on SQLite (no support for set_config)
        if dialect_name == "sqlite":
            return

        if shop_id is not None:
            await session.execute(
                text("SELECT set_config('app.current_shop_id', :val, true)").bindparams(
                    val=str(shop_id)
                )
            )
        if user_id is not None:
            await session.execute(
                text("SELECT set_config('app.current_user_id', :val, true)").bindparams(
                    val=str(user_id)
                )
            )
    except TenantContextRequiredError:
        raise
    except Exception:
        # Unexpected errors should propagate (not swallowed)
        logger.error("Failed to apply tenant context", exc_info=True)
        raise


_SHOP_GUC = "app.current_shop_id"
_USER_GUC = "app.current_user_id"


def _require_shop_for_shop_scope(shop_id: uuid.UUID | None) -> None:
    """Refuse a shop scope with no shop, before anything reaches the database.

    Extracted so `with_shop_scope` can run it ahead of the GUC read it now does
    on entry. `system_scope` exists for work with no tenant at all; a shop scope
    without a shop is neither, and admitting it would make "which shop" an
    omission rather than a decision in the code.
    """
    if shop_id is None:
        raise TenantContextRequiredError(
            "Shop context required: with_shop_scope() was entered without a shop_id. "
            "A shop-scoped unit of work must name its shop; use system_scope() if the "
            "work is genuinely fleet-wide."
        )


def _session_is_sqlite(session: AsyncSession) -> bool:
    """SQLite has no set_config and no RLS, so every GUC operation is a no-op."""
    bind = session.get_bind()
    dialect_name = bind.dialect.name if hasattr(bind, "dialect") else "postgresql"
    return dialect_name == "sqlite"


async def _read_tenant_gucs(session: AsyncSession) -> tuple[str, str]:
    """Read the current GUC pair so a scope can put it back on exit.

    `current_setting(name, true)` returns NULL rather than raising when the
    parameter was never set in this session; both are normalised to the empty
    string, which is the same value `SET LOCAL` restores at commit and which
    `app_current_shop_id()` (migration 050) maps to NULL via `nullif`.
    """
    if _session_is_sqlite(session):
        return "", ""
    row = (
        await session.execute(
            text(
                f"SELECT current_setting('{_SHOP_GUC}', true), "  # nosec B608
                f"       current_setting('{_USER_GUC}', true)"
            )
        )
    ).one()
    return (row[0] or "", row[1] or "")


async def _write_tenant_gucs(session: AsyncSession, shop: str, user: str) -> None:
    """Set both GUCs to explicit values, empty string meaning 'no context'."""
    if _session_is_sqlite(session):
        return
    await session.execute(
        text(
            "SELECT set_config(:shop_key, :shop_val, true), "
            "       set_config(:user_key, :user_val, true)"
        ).bindparams(shop_key=_SHOP_GUC, shop_val=shop, user_key=_USER_GUC, user_val=user)
    )


async def _restore_tenant_gucs(
    session: AsyncSession, shop: str, user: str, *, body_failed: bool
) -> None:
    """Put the previous GUC pair back as a scope exits.

    WHY A FAILED RESTORE IS NOT ALWAYS AN ERROR.

    When the body raised, the transaction may already be aborted, and every
    statement on it — including this one — then raises
    `InFailedSqlTransaction`. Letting that propagate would replace the caller's
    real exception with a confusing one from the cleanup path. It is also
    unnecessary: the rollback that must follow an aborted transaction discards
    `SET LOCAL` anyway, which is the fail-closed state this function exists to
    reach.

    When the body did NOT raise, a failed restore is a genuine error and is
    raised. Swallowing it there would leave the leak in place silently, which
    is the whole defect (#1495).
    """
    try:
        await _write_tenant_gucs(session, shop, user)
    except Exception:
        if not body_failed:
            raise
        logger.warning(
            "tenant_context_restore_skipped",
            extra={"reason": "transaction already failed; rollback clears SET LOCAL"},
            exc_info=True,
        )


@asynccontextmanager
async def with_tenant_scope(
    session: AsyncSession,
    shop_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
) -> AsyncIterator[None]:
    """Context manager that sets app.current_shop_id and app.current_user_id
    via SET LOCAL for the duration of the transaction.

    Args:
        session: AsyncSession to set GUCs on
        shop_id: The shop ID (or None if system_scope is active)
        user_id: The user ID (or None if system_scope is active)

    Raises:
        TenantContextRequiredError: If neither tenant context nor system_scope
            is available, raised BEFORE any SQL is executed.

    Note:
        On the HTTP path, tenant context is applied automatically without
        per-route opt-in: the get_active_shop dependency calls
        _apply_tenant_context_to_session on the request's own session after
        resolving the shop. Celery/fleet paths use system_scope() explicitly.
    """
    # `_apply_tenant_context_to_session` validates and can raise before setting
    # anything, so the read is ordered after nothing and the restore is guarded
    # on having actually applied — same reasoning as `with_shop_scope`.
    prior_shop, prior_user = await _read_tenant_gucs(session)
    await _apply_tenant_context_to_session(session, shop_id, user_id)
    applied = True
    body_failed = False
    try:
        yield
    except BaseException:
        body_failed = True
        raise
    finally:
        if applied:
            await _restore_tenant_gucs(session, prior_shop, prior_user, body_failed=body_failed)


@asynccontextmanager
async def with_shop_scope(
    session: AsyncSession,
    shop_id: uuid.UUID,
) -> AsyncIterator[None]:
    """Set shop context only, for work that has a shop but no user (ADR-089).

    The narrowest of the three scopes. `app.current_shop_id` is set with
    SET LOCAL; `app.current_user_id` is deliberately left unset, so it reads
    NULL and every USER-keyed policy denies. `users` is the clearest case:
    nothing shop-scoped needs to read a user, and the withheld GUC makes that
    structural rather than a convention.

    `shops` IS READABLE, but only the caller's own row. This paragraph used to
    name it alongside `users` as something a shop-level task "has no business"
    reading; #1518 found that too broad. `mock_analytics_reconcile` must
    resolve its own shop's vendor key, and under the user-keyed policy alone it
    read zero rows as `juli_app` and silently did nothing. Migration 053 adds
    `shops_shop_scope_select (id = app_current_shop_id())` — one row, the
    caller's own, and only when a shop context is set. Reading your own shop
    under your own scope is what tenancy means; its absence was the anomaly.

    WHY THIS EXISTS RATHER THAN RESOLVING A USER.

    `with_tenant_scope` requires both ids. A beat task that operates on one
    shop has no user, and looking one up is circular: reading `shops.user_id`
    needs `app.current_user_id` already set. The alternative — a
    SECURITY DEFINER owner lookup — would hand an exemption to tasks that need
    none, against ADR-089 decision 5.

    WHAT IT DOES NOT DO.

    It confers no cross-tenant access. A task that must see more than one shop
    needs an enumeration exemption (ADR-089 decision 3), not this. And it is not
    `system_scope`: the shop id is mandatory, so "which shop" stays a decision
    in the code rather than an omission.

    Args:
        session: AsyncSession to set the GUC on
        shop_id: the shop this unit of work belongs to

    Raises:
        TenantContextRequiredError: if shop_id is None, before any SQL is
            emitted.
    """
    token = _shop_scope_active.set(True)
    body_failed = False
    # Bound before the try: the finally reads them, and _read_tenant_gucs
    # itself can raise on a session whose transaction is already unusable.
    prior_shop, prior_user = "", ""
    # Nothing to put back until context has actually been applied. Without this
    # the finally would emit a set_config even on the refusal path, breaking the
    # contract that a scope with no shop reaches the database not at all.
    applied = False
    try:
        # Before the GUC read, not after: the read below is itself a statement.
        _require_shop_for_shop_scope(shop_id)
        prior_shop, prior_user = await _read_tenant_gucs(session)
        await _apply_tenant_context_to_session(session, shop_id, None)
        # Withhold the user GUC explicitly rather than by omission. The
        # docstring above promises every user-keyed policy denies inside this
        # scope; that only held while nothing had set the GUC earlier in the
        # transaction. Under an enclosing `with_tenant_scope`, or a second pass
        # through a loop, it would have been inherited and the promise would
        # have been quietly false.
        await _write_tenant_gucs(session, str(shop_id), "")
        applied = True
        yield
    except BaseException:
        body_failed = True
        raise
    finally:
        try:
            if applied:
                await _restore_tenant_gucs(session, prior_shop, prior_user, body_failed=body_failed)
        finally:
            _shop_scope_active.reset(token)


@asynccontextmanager
async def system_scope(
    session: AsyncSession,
    caller: str,
) -> AsyncIterator[None]:
    """Context manager that exempts fleet-wide work from tenant context requirement.

    Used for genuinely fleet-scoped work that operates across all tenants:
    - Reconcile
    - Backfill top-up
    - Impact reader
    - Credential refresh
    - Reaper

    Args:
        session: AsyncSession to use for the fleet-scoped work
        caller: Name of the caller (logged for audit trail)

    Usage:
        async with system_scope(session, caller="impact_reader.run"):
            # This code can run without tenant context
            await session.execute(...)
    """
    global _system_scope_active

    logger.info("system_scope_enter", extra={"caller": caller})
    old_system_scope_active = _system_scope_active
    _system_scope_active = True

    try:
        yield
    finally:
        _system_scope_active = old_system_scope_active
        logger.info("system_scope_exit", extra={"caller": caller})
