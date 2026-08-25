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

    Called on the HTTP path by the get_active_shop_and_set_context middleware
    dependency (applied directly to the request's session), and by
    with_tenant_scope. Uses parameterized set_config() to avoid SQL injection.

    Args:
        session: AsyncSession to apply context to
        shop_id: The shop ID (from contextvars)
        user_id: The user ID (from contextvars)

    Raises:
        TenantContextRequiredError: If context is required but not available.
    """
    global _system_scope_active

    # Fail-closed in Python before any SQL
    if not _system_scope_active and (shop_id is None or user_id is None):
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
        per-route opt-in: the get_active_shop_and_set_context middleware
        dependency calls _apply_tenant_context_to_session on the request's
        own session. Celery/fleet paths use system_scope() explicitly.
    """
    await _apply_tenant_context_to_session(session, shop_id, user_id)
    try:
        yield
    finally:
        # GUCs are automatically cleared when the transaction ends due to SET LOCAL
        pass


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
