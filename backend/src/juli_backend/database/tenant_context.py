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
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

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


def _require_shop_for_shop_scope(shop_id: uuid.UUID | None) -> uuid.UUID:
    """Refuse a shop scope with no shop, before anything reaches the database.

    Extracted so `with_shop_scope` can run it ahead of the GUC read it now does
    on entry. `system_scope` exists for work with no tenant at all; a shop scope
    without a shop is neither, and admitting it would make "which shop" an
    omission rather than a decision in the code.

    Returns the shop id it just proved is present, so a caller that needs a
    non-optional one downstream can bind it here instead of asserting again
    (#1883). Callers that only want the refusal keep ignoring the return.
    """
    if shop_id is None:
        raise TenantContextRequiredError(
            "Shop context required: with_shop_scope() was entered without a shop_id. "
            "A shop-scoped unit of work must name its shop; use system_scope() if the "
            "work is genuinely fleet-wide."
        )
    return shop_id


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

    When the body did NOT raise AND the session is still usable, a failed
    restore is a genuine error and is raised. Swallowing it there would leave
    the leak in place silently, which is the whole defect (#1495).

    "THE BODY RAISED" IS NOT THE ONLY WAY THE SESSION BREAKS (#1576). A body can
    catch its own flush failure and return normally, leaving the transaction
    rolled back and the session unusable while `body_failed` is False. This
    guard then tried to write and raised PendingRollbackError from the `finally`,
    which REPLACED the caller's real error — in production it masked an RLS
    "new row violates row-level security policy" and turned a one-line diagnosis
    into reading past a misleading traceback.

    THIS NEVER RAISES. A cleanup step running in a `finally` must not replace the
    caller's exception, and #1495's original rule — re-raise when the body did not
    fail — could not tell the two apart. A body can catch its own flush failure
    and return normally, leaving the session unusable while `body_failed` is
    False; the write below then failed and its exception surfaced INSTEAD of the
    caller's. In production that masked an RLS "new row violates row-level
    security policy" behind a PendingRollbackError from this function.

    Narrowing to one exception type does not work either. Measured: the same
    broken-session condition raises PendingRollbackError when SQLAlchemy refuses
    the statement and DBAPIError when Postgres does. `session.in_transaction()`
    is no better — it still returns True after a caught statement error while the
    next execute raises.

    So the failure is always swallowed and always reported, at ERROR when the
    body was healthy — a genuine restore failure that deserves attention — and at
    WARNING when the body had already failed, where an unusable session is
    expected. Not restoring is safe on its own: SET LOCAL dies with the
    transaction, which is the fail-closed state this function exists to reach.
    """
    try:
        await _write_tenant_gucs(session, shop, user)
    except Exception:
        logger.log(
            logging.WARNING if body_failed else logging.ERROR,
            "tenant_context_restore_failed",
            extra={
                "body_failed": body_failed,
                "reason": (
                    "session unusable after the body failed; rollback clears SET LOCAL"
                    if body_failed
                    else "restore failed on a session the body left usable — investigate"
                ),
            },
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


async def reapply_shop_scope(session: AsyncSession, shop_id: uuid.UUID) -> None:
    """Re-establish the shop GUC after a COMMIT discarded it.

    `with_shop_scope` sets `app.current_shop_id` with SET LOCAL, which is
    transaction-scoped: a commit throws it away. Any caller that commits in the
    middle of a scope — because it wants progress to be durable rather than all
    -or-nothing — must put the GUC back, or every write after the first commit
    is refused by RLS. That is #1627 and #1631 in a different costume.

    `with_shop_scope` cannot serve here: it sets on entry and RESTORES on exit,
    so entering and leaving it immediately puts back the pre-commit value, which
    after a commit is nothing at all.

    The user GUC is deliberately left empty, exactly as `with_shop_scope` leaves
    it (#1478): shop-scoped work has no user, and a withheld GUC makes every
    user-keyed policy deny structurally rather than by convention.
    """
    _require_shop_for_shop_scope(shop_id)
    await _write_tenant_gucs(session, str(shop_id), "")


# --- sticky shop scope (#1883) --------------------------------------------
#
# `SET LOCAL` dies with the transaction, so `with_shop_scope` holds only until
# the first COMMIT inside its own block. `reapply_shop_scope` above is the
# answer when the caller knows where the commits are. It is not the answer on
# the agent-run path: `JsonbConversationStore.persist` commits on every turn
# and `ToolExecutionLedger` commits around every write, so "immediately after
# the callee returns" would have to be spelled at a dozen call sites inside a
# loop that lives in another module. The scope has to survive the commits
# instead of being rebuilt after each one.
#
# THE MECHANISM. A SQLAlchemy `after_begin` listener bound to ONE session
# re-applies the same GUC pair at the start of every transaction that session
# opens, including the one autobegun by the first statement after a commit. It
# is still `SET LOCAL`: nothing is ever set at session or connection level, so
# a pooled connection cannot carry a shop id into its next checkout. What
# changes is only that the value is put back as each new transaction starts.
#
# AUTHORITY IS UNCHANGED (ADR-089). One shop id, the same policies, the user
# GUC withheld as the empty string exactly as `with_shop_scope` withholds it,
# and no enumeration exemption — decision 3 is untouched.

_STICKY_GUC_SQL = (
    "SELECT set_config(:shop_key, :shop_val, true), set_config(:user_key, :user_val, true)"
)


def _shop_scope_guc_params(shop_id: uuid.UUID) -> dict[str, str]:
    """The GUC pair a shop scope writes: the shop, and a withheld user."""
    return {
        "shop_key": _SHOP_GUC,
        "shop_val": str(shop_id),
        "user_key": _USER_GUC,
        "user_val": "",
    }


def _make_sticky_after_begin_listener(
    shop_id: uuid.UUID,
) -> Callable[[Session, SessionTransaction, Connection], None]:
    """Build the `after_begin` handler that re-applies the shop GUC.

    The handler runs in the sync context — for an `AsyncSession` that is inside
    the greenlet SQLAlchemy already spawned for the enclosing await — so it
    issues the statement on the `Connection` it is handed rather than on the
    session. `set_config(name, value, true)` is bound as parameters, never
    interpolated: the shop id reaches Postgres as a value.

    A new closure per scope, deliberately. `event.remove` matches on the
    function object, so two concurrently open scopes on two sessions must not
    share one, or removing either would remove the other's.
    """
    params = _shop_scope_guc_params(shop_id)

    def _reapply_shop_guc_on_begin(
        session: Session, transaction: SessionTransaction, connection: Connection
    ) -> None:
        connection.execute(text(_STICKY_GUC_SQL), params)

    return _reapply_shop_guc_on_begin


@asynccontextmanager
async def with_sticky_shop_scope(
    session: AsyncSession,
    shop_id: uuid.UUID | None,
) -> AsyncIterator[None]:
    """`with_shop_scope` that survives the commits inside its own block (#1883).

    Same authority, same single shop, same withheld user GUC, same refusal
    before any SQL when no shop is named. The only difference is that a
    transaction begun after a COMMIT inside the block starts with the shop GUC
    already set, instead of starting with nothing and failing the next gated
    read.

    Use this when the unit of work contains a callee that commits and you
    cannot re-apply the scope after it — the agent-run worker path
    (`workers/tasks/agent_workflow.py`) is the case this exists for. When the
    commits are visible at the call site, `reapply_shop_scope` is smaller and
    is still the right tool.

    WHAT IT DOES NOT DO. It does not widen visibility by one row: the listener
    writes the same `SET LOCAL` pair `with_shop_scope` writes. It is not a
    session-level or connection-level `SET`, so it cannot leak through the
    pool. And it is not `system_scope`: the shop id is mandatory.

    Args:
        session: AsyncSession to hold the scope on
        shop_id: the shop this unit of work belongs to. Typed optional because
            refusing a `None` IS the contract — callers resolve the shop from a
            read that can legitimately come back empty, and this is where that
            becomes a fail-closed error rather than an unscoped transaction.

    Raises:
        TenantContextRequiredError: if shop_id is None, before any SQL is
            emitted and before a listener is bound.
    """
    token = _shop_scope_active.set(True)
    body_failed = False
    prior_shop, prior_user = "", ""
    applied = False
    listener = None
    listen_target = None
    try:
        # Before the GUC read, for the reason `with_shop_scope` gives: the read
        # is itself a statement, and a scope with no shop must reach the
        # database not at all.
        shop = _require_shop_for_shop_scope(shop_id)
        prior_shop, prior_user = await _read_tenant_gucs(session)
        listen_target, listener = _register_sticky_listener(session, shop)
        await _apply_tenant_context_to_session(session, shop, None)
        # Withhold the user GUC explicitly rather than by omission — the same
        # reasoning as `with_shop_scope`, and the same pair the listener puts
        # back on every subsequent transaction.
        await _write_tenant_gucs(session, str(shop), "")
        applied = True
        yield
    except BaseException:
        body_failed = True
        raise
    finally:
        try:
            _remove_sticky_listener(listen_target, listener)
        finally:
            try:
                if applied:
                    await _restore_tenant_gucs(
                        session, prior_shop, prior_user, body_failed=body_failed
                    )
            finally:
                _shop_scope_active.reset(token)


_StickyListener = Callable[[Session, SessionTransaction, Connection], None]


def _register_sticky_listener(
    session: AsyncSession | Session,
    shop_id: uuid.UUID,
) -> tuple[Session | None, _StickyListener | None]:
    """Bind the re-apply handler to THIS session, or to nothing on SQLite.

    SQLite has neither `set_config` nor RLS, so every GUC operation in this
    module is already a no-op there; registering a handler that emits one would
    turn the no-op into a syntax error on the unit-test dialect. The dialect
    check comes before `AsyncSession.sync_session` is ever touched, so a
    SQLite-backed caller never has to own one.

    Returns the pair the exit path needs — `event.remove` matches on both the
    target and the function object, so the caller must not have to re-derive
    either.
    """
    if _any_session_is_sqlite(session):
        return None, None
    listen_target = session.sync_session if isinstance(session, AsyncSession) else session
    listener = _make_sticky_after_begin_listener(shop_id)
    event.listen(listen_target, "after_begin", listener)
    return listen_target, listener


def _remove_sticky_listener(
    listen_target: Session | None,
    listener: _StickyListener | None,
) -> None:
    """Unbind the handler on the way out, on both the normal and error paths.

    Removal is not optional housekeeping. The session outlives the scope — the
    worker path hands the same session to the crash handler — and a handler
    left attached would keep re-asserting a shop id after the block that chose
    it has ended, which is precisely the leak `SET LOCAL` exists to prevent.
    """
    if listener is None or listen_target is None:
        return
    event.remove(listen_target, "after_begin", listener)


def _any_session_is_sqlite(session: AsyncSession | Session) -> bool:
    """`_session_is_sqlite` for either session flavour — the bind check is the
    same on both, only the annotation differs."""
    bind = session.get_bind()
    dialect_name = bind.dialect.name if hasattr(bind, "dialect") else "postgresql"
    return dialect_name == "sqlite"


def _read_tenant_gucs_sync(session: Session) -> tuple[str, str]:
    """`_read_tenant_gucs` for a sync `Session` — same statement, same
    empty-string normalisation."""
    if _any_session_is_sqlite(session):
        return "", ""
    row = session.execute(
        text(
            f"SELECT current_setting('{_SHOP_GUC}', true), "  # nosec B608
            f"       current_setting('{_USER_GUC}', true)"
        )
    ).one()
    return (row[0] or "", row[1] or "")


def _write_tenant_gucs_sync(session: Session, shop: str, user: str) -> None:
    """`_write_tenant_gucs` for a sync `Session`."""
    if _any_session_is_sqlite(session):
        return
    session.execute(
        text(_STICKY_GUC_SQL).bindparams(
            shop_key=_SHOP_GUC, shop_val=shop, user_key=_USER_GUC, user_val=user
        )
    )


def _restore_tenant_gucs_sync(session: Session, shop: str, user: str, *, body_failed: bool) -> None:
    """`_restore_tenant_gucs` for a sync `Session`.

    Never raises, for the reason spelled out at length on the async twin: a
    cleanup step in a `finally` must not replace the caller's exception, and a
    failed restore is safe on its own because `SET LOCAL` dies with the
    transaction anyway.
    """
    try:
        _write_tenant_gucs_sync(session, shop, user)
    except Exception:
        logger.log(
            logging.WARNING if body_failed else logging.ERROR,
            "tenant_context_restore_failed",
            extra={"body_failed": body_failed, "sync": True},
            exc_info=True,
        )


@contextmanager
def with_sticky_shop_scope_sync(
    session: Session,
    shop_id: uuid.UUID | None,
) -> Iterator[None]:
    """`with_sticky_shop_scope` for a synchronous `sqlalchemy.orm.Session`.

    WHY A SECOND FLAVOUR RATHER THAN ONE. `ToolExecutionLedger`
    (`services/agent/runner/ledger.py`) is sync by construction and runs on its
    own throwaway `Session` (`agent_workflow.py::_sync_ledger_session`), which
    it commits around every write to `tool_executions` — an RLS-gated table.
    Fixing only the async session would leave every ledger row unscoped, so the
    run would still fail, one layer down. Nothing about the mechanism differs:
    the same `after_begin` listener, the same `SET LOCAL` pair, the same single
    shop.

    Args:
        session: the sync Session to hold the scope on
        shop_id: the shop this unit of work belongs to. Optional for the same
            reason as the async twin: refusing a `None` is the contract.

    Raises:
        TenantContextRequiredError: if shop_id is None, before any SQL is
            emitted and before a listener is bound.
    """
    body_failed = False
    prior_shop, prior_user = "", ""
    applied = False
    listener = None
    listen_target = None
    try:
        shop = _require_shop_for_shop_scope(shop_id)
        prior_shop, prior_user = _read_tenant_gucs_sync(session)
        listen_target, listener = _register_sticky_listener(session, shop)
        _write_tenant_gucs_sync(session, str(shop), "")
        applied = True
        yield
    except BaseException:
        body_failed = True
        raise
    finally:
        try:
            _remove_sticky_listener(listen_target, listener)
        finally:
            if applied:
                _restore_tenant_gucs_sync(session, prior_shop, prior_user, body_failed=body_failed)


@asynccontextmanager
async def with_user_scope(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> AsyncIterator[None]:
    """Set user context only, for the authentication lookup itself (#1691).

    THE CIRCULARITY THIS BREAKS. `users` carries
    `users_select_public USING (id = app_current_user_id())`. Authentication has
    to read `users` to learn who the caller is — but the policy demands the
    answer before it will hand it over. Under the old owner-exempt runtime the
    policy simply did not apply and the read worked; once `DATABASE_URL` moved to
    `juli_app`, EVERY authenticated request began returning
    `401 {"detail":"User not found"}` for a row that plainly exists. Measured on
    production 2026-09-07: `users row visible: 0` as `juli_app` with no GUC,
    `1` on the owner connection.

    WHY THIS IS NOT A BYPASS. The id does not come from the database, and it does
    not come from the caller's say-so — it comes from `sub` in a JWT this process
    has already verified against `SUPABASE_JWT_SECRET`. The application asserts an
    identity it has cryptographic grounds to assert, and the policy still does the
    narrowing: a wrong or forged `sub` selects nothing, because the row it names
    does not exist or does not match. Measured with the GUC set from `sub`:

        own row visible: 1      another user's row: 0      total rows visible: 1

    The read stays exactly one row. Contrast a SECURITY DEFINER lookup function,
    which would hand the auth path a standing exemption to get the same result —
    more machinery, and an exemption where none is needed (ADR-089 decision 5).

    THE SHOP GUC IS WITHHELD, deliberately and explicitly rather than by
    omission, for the reason `with_shop_scope` withholds the user GUC: under an
    enclosing scope or a second pass it would otherwise be inherited, and this
    scope would quietly confer shop access it never intended to. Authentication
    knows a user and no shop; `get_active_shop` establishes the shop afterwards,
    from the `X-Shop-Id` header, against the user's own shops.

    Args:
        session: AsyncSession to set the GUC on
        user_id: the subject of the verified JWT

    Raises:
        TenantContextRequiredError: if user_id is None, before any SQL is
            emitted.
    """
    if user_id is None:
        msg = "with_user_scope requires a user_id"
        raise TenantContextRequiredError(msg)

    body_failed = False
    prior_shop, prior_user = "", ""
    applied = False
    try:
        prior_shop, prior_user = await _read_tenant_gucs(session)
        await _write_tenant_gucs(session, "", str(user_id))
        applied = True
        yield
    except BaseException:
        body_failed = True
        raise
    finally:
        if applied:
            await _restore_tenant_gucs(session, prior_shop, prior_user, body_failed=body_failed)


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
