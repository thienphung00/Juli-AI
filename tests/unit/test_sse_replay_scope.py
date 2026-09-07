"""The stream's own session must take a scope, because it inherits none (#1700).

`GET /v1/demo/runs/{id}/events` returned `HTTP 200` with a **zero-byte body** for
a run with 8 events. `workflow_run_events_select_public` is an
`EXISTS (SELECT 1 FROM workflow_runs ...)` policy; with no tenant context it
denies, and the stream yields nothing.

Measured on production as `juli_app`:

    no GUC                    events visible: 0
    app.current_shop_id set   events visible: 8

WHY THE SESSION IS DIFFERENT. `stream_run_events` takes its sessions from
`get_run_events_session_factory`, whose docstring says why: *"Sessions for the
stream's own reads; the request session closes too early."* That reasoning is
sound — a stream outlives the request — but the new session never inherited the
scope `get_active_shop` applied to the request session.

A DIFFERENT CLASS FROM #1691 AND #1697. Those are reads that run BEFORE the
request scope exists, and they are bounded at two. This one runs after it, on a
session that never had it. The rule the three share: **a session that opens its
own connection inherits no scope and must take one.**

WHY AN EMPTY STREAM IS THE WORST SHAPE OF THIS BUG. `200` with no events is
indistinguishable from "this run has no events". Nothing raises, nothing logs an
error, and the client renders an empty timeline that looks like truth.
"""

from __future__ import annotations

import uuid
from typing import cast

import pytest

from juli_backend.services.agent_runs.events import replay_events


class _ScopeRecordingSession:
    """Captures whether a shop scope was set before the events query ran."""

    def __init__(self) -> None:
        self.shop_guc: str | None = None
        self.guc_at_query: str | None = None

    class _Dialect:
        name = "postgresql"

    class _Bind:
        dialect = None

    def get_bind(self):
        bind = self._Bind()
        bind.dialect = self._Dialect()
        return bind

    async def execute(self, statement, *args, **kwargs):
        params = dict(statement.compile().params) if hasattr(statement, "compile") else {}
        if params.get("shop_key") == "app.current_shop_id":
            self.shop_guc = params.get("shop_val")
            return _Row()
        text = str(statement)
        if "current_setting" in text:
            return _Row()
        # The events SELECT itself.
        self.guc_at_query = self.shop_guc
        return _Scalars()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


class _Row:
    def one(self):
        return (None, None)


class _Scalars:
    def scalars(self):
        return []


@pytest.mark.asyncio
async def test_the_events_read_is_scoped_before_it_queries() -> None:
    """The regression: without the scope the policy denies and the stream is empty."""
    session = _ScopeRecordingSession()
    shop_id = uuid.uuid4()

    def factory():
        return session

    rows = [r async for r in replay_events(cast("object", factory), uuid.uuid4(), 0, shop_id)]

    assert rows == []
    assert session.guc_at_query == str(shop_id), (
        f"the shop GUC was {session.guc_at_query!r} when the events query ran; without "
        f"it the RLS policy denies and the stream returns 200 with no events — which "
        f"reads exactly like a run that has none"
    )


@pytest.mark.asyncio
async def test_shop_id_is_required_not_optional() -> None:
    """A caller that forgets the scope must fail loudly, not stream nothing.

    An optional `shop_id` would default to no scope, and the resulting empty
    stream is indistinguishable from a run with no events. That is the failure
    mode this fix removes, so it must not be reachable by omission.
    """
    session = _ScopeRecordingSession()

    def factory():
        return session

    with pytest.raises(TypeError) as excinfo:
        _ = [r async for r in replay_events(cast("object", factory), uuid.uuid4(), 0)]

    # Named rather than left to the bare raise. The corpus guard counts a test
    # whose only assertion lives inside `pytest.raises` as having none, and the
    # honest fix is to say what is being asserted rather than to move the
    # committed figure — the figure is the point of the guard.
    assert "shop_id" in str(excinfo.value), (
        f"the missing argument must be named `shop_id`, or a caller cannot tell which "
        f"scope it forgot: {excinfo.value}"
    )
