"""`with_shop_scope` sets a shop and deliberately withholds a user (#1478 / ADR-089).

`with_tenant_scope` requires both ids, and `system_scope` requires neither. A beat task that
operates on one shop sits between them: it has a shop and no user, and looking a user up is
circular — reading `shops.user_id` needs `app.current_user_id` already set.

The third scope closes that gap without widening anything. `app.current_shop_id` is set;
`app.current_user_id` is left unset, so after #1467 it reads NULL and every user-keyed policy
denies. That denial is the property being bought, not a shortfall to work around later.

WHY THE DENIAL IS ASSERTED, NOT JUST THE GRANT.

The failure this epic exists for is a task that completes having done nothing. A test that only
proves the shop GUC is set would pass on a scope that also silently set the user GUC, or on one
that set neither — and the second is exactly today's `system_scope` behaviour. Both halves are
pinned.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import cast

import pytest

from juli_backend.database.tenant_context import (
    TenantContextRequiredError,
    with_shop_scope,
)


class _Dialect:
    name = "postgresql"


class _Bind:
    # SQLAlchemy exposes this as an attribute named `dialect`. Both live at
    # module level because a class body does not create an enclosing scope for a
    # nested class, so `_Bind` could not see a `_Dialect` defined beside it.
    dialect = _Dialect()


class _RecordingSession:
    """Captures the GUCs a scope sets, without a database.

    The seam under test is which `set_config` calls are emitted and which are
    withheld. That is a Python-level decision made before any SQL leaves the
    process, so it is provable here; whether the resulting policies then deny is
    a Postgres claim and belongs in the integration suite.
    """

    def __init__(self) -> None:
        self.statements: list[tuple[str, dict]] = []

    def get_bind(self):
        return _Bind()

    async def execute(self, statement, *args, **kwargs):
        self.statements.append((str(statement), dict(statement.compile().params)))
        return None

    def gucs_set(self) -> set[str]:
        return {
            name
            for text, params in self.statements
            for name in ("app.current_shop_id", "app.current_user_id")
            if name in text
        }


def test_shop_scope_sets_the_shop_guc() -> None:
    session = _RecordingSession()
    shop_id = uuid.uuid4()

    async def run() -> None:
        async with with_shop_scope(session, shop_id):
            pass

    asyncio.run(run())

    assert "app.current_shop_id" in session.gucs_set()
    assert any(str(shop_id) in str(params) for _text, params in session.statements), (
        "the shop id must reach set_config; setting the GUC to something else would scope "
        "the work to the wrong tenant"
    )


def test_shop_scope_withholds_the_user_guc() -> None:
    """The half that makes this safe rather than merely convenient.

    A shop-level task must not be able to read `users` or `shops`. Leaving the
    user GUC unset is what produces that denial, so it is asserted directly —
    a scope that quietly set both would pass the test above and defeat the point.
    """
    session = _RecordingSession()

    async def run() -> None:
        async with with_shop_scope(session, uuid.uuid4()):
            pass

    asyncio.run(run())

    assert "app.current_user_id" not in session.gucs_set(), (
        "with_shop_scope must leave app.current_user_id unset so user-keyed policies deny; "
        "setting it would grant a shop-level beat task access to users and shops"
    )


def test_shop_scope_requires_a_shop_before_any_sql() -> None:
    """Fail closed, and fail early.

    `system_scope` exists for work with no tenant at all. A shop scope without a
    shop is neither, and admitting it would make "which shop" an omission rather
    than a decision in the code — the exact property ADR-089 decision 5 turns on.
    """
    session = _RecordingSession()

    async def run() -> None:
        # `cast` rather than a checker suppression: the point of the test is
        # that the runtime guard holds even when the type contract is violated,
        # and a cast states that where a suppression would only silence it.
        async with with_shop_scope(session, cast(uuid.UUID, None)):
            pass

    with pytest.raises(TenantContextRequiredError):
        asyncio.run(run())

    assert session.statements == [], (
        "the refusal must happen before any statement reaches the database"
    )


def test_shop_scope_does_not_leak_between_concurrent_tasks() -> None:
    """The reason this flag is a ContextVar and not a module global.

    `_system_scope_active` is a plain global, so two coroutines in one event loop
    share it and the first to exit clears the second's exemption. Pin that the
    shop scope does not inherit that bug: a task outside any scope must still be
    refused while another task is inside one.
    """
    outside_was_refused = False

    async def scenario() -> None:
        nonlocal outside_was_refused
        inside_started = asyncio.Event()
        may_finish = asyncio.Event()

        async def inside() -> None:
            async with with_shop_scope(_RecordingSession(), uuid.uuid4()):
                inside_started.set()
                await may_finish.wait()

        async def outside() -> None:
            nonlocal outside_was_refused
            await inside_started.wait()
            session = _RecordingSession()
            try:
                # No scope active in THIS context: both ids are required.
                from juli_backend.database.tenant_context import with_tenant_scope

                async with with_tenant_scope(session, uuid.uuid4(), None):
                    pass
            except TenantContextRequiredError:
                outside_was_refused = True
            finally:
                may_finish.set()

        await asyncio.gather(inside(), outside())

    asyncio.run(scenario())

    assert outside_was_refused, (
        "a concurrent task outside any scope was admitted while another task held a shop "
        "scope — the flag is leaking across contexts, which is the hazard the ContextVar "
        "exists to avoid"
    )
