"""Authentication needs a scope of its own, or it cannot read the user (#1691).

`users` carries `users_select_public USING (id = app_current_user_id())`. The
authentication step has to read `users` to learn who the caller is — but the
policy demands that answer before it will hand it over. Under the owner-exempt
runtime the policy did not apply and the read worked. Once `DATABASE_URL` moved
to `juli_app`, EVERY authenticated request returned
`401 {"detail": "User not found"}` for a row that plainly exists.

Measured on production 2026-09-07:

    as juli_app, no GUC          users row visible: 0
    as the owner connection      users row visible: 1
    as juli_app, GUC from `sub`  own row 1, another user's row 0, total 1

The third line is why this is not a bypass: the policy still narrows the read to
exactly one row. The id is `sub` from a JWT already verified against
`SUPABASE_JWT_SECRET`, so the application is asserting an identity it has
cryptographic grounds to assert — not taking the caller's word for it.

WHAT IS PROVABLE HERE. Which `set_config` calls are emitted and which are
withheld is a Python-level decision made before any SQL leaves the process.
Whether the resulting policies then deny is a Postgres claim and belongs in the
integration suite; the production measurement above is the evidence for it today.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import cast

import pytest

from juli_backend.database.tenant_context import (
    TenantContextRequiredError,
    with_user_scope,
)
from tests.unit.test_with_shop_scope import _RecordingSession


def _run(coro_fn) -> None:
    asyncio.run(coro_fn())


def test_user_scope_sets_the_user_guc() -> None:
    session = _RecordingSession()
    user_id = uuid.uuid4()

    async def run() -> None:
        async with with_user_scope(cast("object", session), user_id):
            pass

    _run(run)

    assert "app.current_user_id" in session.gucs_set()
    assert any(str(user_id) in str(params) for _t, params in session.statements), (
        "the user id must reach set_config; without it the policy matches nothing and "
        "authentication fails for every caller"
    )


def test_user_scope_withholds_the_shop_guc() -> None:
    """The half that keeps this narrow.

    Authentication knows a user and no shop. `get_active_shop` establishes the
    shop afterwards from `X-Shop-Id`, checked against the user's own shops. If
    this scope also set a shop GUC it would confer tenant access before anything
    had decided which tenant — and it would do so invisibly.

    Asserted as an outcome rather than as an absent statement: the shop GUC is
    written as EMPTY, deliberately, so that an enclosing scope or a second pass
    cannot leave a stale value inherited. Checking only "no shop statement" would
    pass on the inheriting version, which is the bug.
    """
    session = _RecordingSession()
    user_id = uuid.uuid4()

    async def run() -> None:
        async with with_user_scope(cast("object", session), user_id):
            pass

    _run(run)

    shop_values = [params for text, params in session.statements if "app.current_shop_id" in text]
    assert shop_values, "the shop GUC must be written explicitly, not left to inheritance"
    assert all(str(v) == "" for p in shop_values for k, v in p.items() if k.endswith("shop_val")), (
        f"the shop GUC must be set EMPTY inside a user scope, got: {shop_values}"
    )


def test_a_missing_user_id_refuses_before_any_sql() -> None:
    """A scope with no subject must not reach the database at all.

    Setting the GUC to the string "None" would match no row and read as an
    ordinary auth failure, hiding a programming error as a credentials error.
    """
    session = _RecordingSession()

    async def run() -> None:
        # `cast` rather than a type-checker suppression: passing None here is the
        # point of the test, and the debt ratchet counts a new suppression as new
        # debt — rightly, since one in a test is still one. (Worded without the
        # literal marker: the detector scans comment text, so naming it here would
        # create the very identity this avoids.)
        async with with_user_scope(cast("object", session), cast("uuid.UUID", None)):
            pass

    with pytest.raises(TenantContextRequiredError):
        _run(run)

    assert session.statements == [], (
        f"a refused scope must emit no SQL; it emitted {session.statements}"
    )


def test_the_prior_gucs_are_put_back_on_exit() -> None:
    """The scope is a loan, not a handover.

    `get_current_user` runs early in a request that goes on to establish a shop
    scope. Leaving the user GUC set behind would widen whatever ran next.
    """
    session = _RecordingSession()
    user_id = uuid.uuid4()

    async def run() -> None:
        async with with_user_scope(cast("object", session), user_id):
            pass

    _run(run)

    # The double reports no prior context, so the restore writes the empty pair
    # back. What matters is that a restore happened after the body.
    assert len(session.statements) >= 3, (
        f"expected read, write, restore; got {len(session.statements)} statements"
    )
    last_text, _ = session.statements[-1]
    assert "set_config" in last_text, (
        f"the last statement must put the prior GUCs back, got: {last_text}"
    )


def test_the_scope_is_restored_even_when_the_body_raises() -> None:
    """An auth failure inside the scope must not leave the GUC set."""
    session = _RecordingSession()

    async def run() -> None:
        async with with_user_scope(cast("object", session), uuid.uuid4()):
            raise RuntimeError("lookup blew up")

    with pytest.raises(RuntimeError):
        _run(run)

    last_text, _ = session.statements[-1]
    assert "set_config" in last_text, "the scope must be restored on the failure path too"


class _ScopeAwareSession(_RecordingSession):
    """Records whether the user GUC was set at the moment the row was read."""

    def __init__(self) -> None:
        super().__init__()
        self.user_guc: str | None = None
        self.guc_at_read: str | None = None

    async def execute(self, statement, *args, **kwargs):
        result = await super().execute(statement, *args, **kwargs)
        # The GUC NAME travels as a bind parameter, not in the SQL text — the
        # write is `set_config(:user_key, :user_val, true)`. Matching on the text
        # instead catches only the *read* statement, whose params are empty, and
        # reports None for a GUC that was in fact set.
        params = dict(statement.compile().params)
        if params.get("user_key") == "app.current_user_id":
            self.user_guc = params.get("user_val")
        return result

    async def get(self, _model, user_id):
        # This is the ORM read `UsersRepo.get` performs. Snapshot the GUC as it
        # happens — the whole defect is that this ran with no user context.
        self.guc_at_read = self.user_guc
        return object()


@pytest.mark.asyncio
async def test_the_real_repo_sets_the_guc_before_it_reads() -> None:
    """The regression, against the REAL `UsersRepo` — not a stand-in.

    Before #1691 the read ran with no user GUC, so under `juli_app` the policy on
    `users` matched nothing and every authenticated request 401'd. An earlier
    draft of this test asserted against a hand-written fake repo, which only
    proved the fake did what the fake was written to do.
    """
    from juli_backend.repositories.identity import UsersRepo

    session = _ScopeAwareSession()
    user_id = uuid.uuid4()

    await UsersRepo(cast("object", session)).get_for_authentication(user_id)

    assert session.guc_at_read == str(user_id), (
        f"the user GUC was {session.guc_at_read!r} when the row was read; it must "
        f"already be the JWT's sub, or the RLS policy on `users` matches nothing and "
        f"authentication fails for every caller"
    )


@pytest.mark.asyncio
async def test_the_plain_get_still_sets_no_scope() -> None:
    """The exception must stay confined to the authentication path.

    `get` is called from places that already hold a scope. If it silently set one
    too, the narrow, greppable exception would have become a general one.
    """
    from juli_backend.repositories.identity import UsersRepo

    session = _ScopeAwareSession()
    await UsersRepo(cast("object", session)).get(uuid.uuid4())

    assert session.user_guc is None, (
        f"plain `get` set a user scope ({session.user_guc!r}); the scoped read must "
        f"stay a separate, named method"
    )
