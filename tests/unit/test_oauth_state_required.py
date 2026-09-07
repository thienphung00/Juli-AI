"""A missing OAuth `state` must be refused in production, not waved through (#1748).

Found by the Observation 2 red-team pass on deployed sha `189b5399`.

    ?code=x&state=forged   401   state verified, rejected
    ?code=x                502   state NEVER verified; exchange attempted

The check was guarded by a bare `if state:`, so **omitting** the parameter
skipped it — no forgery required, which is the weakest possible failure mode for
a CSRF control.

AND THE BYPASS PATH WROTE. It fell through to `handle_callback`, then
`get_or_create` on a user, `provision_shop_and_credentials`, and `commit` — bound
to `_app_review_user_id()`, whose default `00000000-0000-4000-8000-000000000001`
is a REAL existing user, not a throwaway.

The no-state path is kept outside production because TikTok's app-review callback
carries no state. In production it is now refused exactly like a forged one,
which is what `docs/security/threat-model.md` already claimed.
"""

from __future__ import annotations

import pytest

from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.services.tiktok import oauth


class _Service:
    """Records whether anything downstream of the guard was reached."""

    def __init__(self) -> None:
        self.verify_state_calls = 0
        self.handle_callback_calls = 0

    def verify_state(self, state):
        self.verify_state_calls += 1
        return "user-from-state"

    async def handle_callback(self, *a, **k):
        self.handle_callback_calls += 1
        raise AssertionError("handle_callback must not be reached in this test")


@pytest.mark.asyncio
async def test_missing_state_is_refused_in_production(monkeypatch) -> None:
    """The regression: no state, production, must raise before any exchange."""
    monkeypatch.setattr(oauth, "is_production", lambda: True)
    svc = _Service()

    with pytest.raises(Unauthorized) as excinfo:
        await oauth.complete_tiktok_oauth_callback(
            object(), code="x", state=None, oauth_service=svc
        )

    assert "state" in str(excinfo.value).lower(), (
        f"the refusal must name the missing parameter, got: {excinfo.value}"
    )
    assert svc.handle_callback_calls == 0, (
        "the unverified path was reached; it provisions a shop and persists "
        "credentials, so reaching it at all is the defect"
    )


@pytest.mark.asyncio
async def test_empty_state_is_refused_too(monkeypatch) -> None:
    """`state=` is as unverified as no state at all — `if state:` treats both falsy."""
    monkeypatch.setattr(oauth, "is_production", lambda: True)
    svc = _Service()

    with pytest.raises(Unauthorized):
        await oauth.complete_tiktok_oauth_callback(object(), code="x", state="", oauth_service=svc)
    assert svc.handle_callback_calls == 0


@pytest.mark.asyncio
async def test_a_present_state_still_goes_through_verification(monkeypatch) -> None:
    """The guard must not swallow the working path.

    A test that only asserted the refusal would pass on code that refused
    everything, which would be an outage rather than a fix.
    """
    monkeypatch.setattr(oauth, "is_production", lambda: True)

    class _Verifying(_Service):
        async def exchange_code(self, code, *, user_id):
            raise RuntimeError("reached the exchange, which is the point")

    svc = _Verifying()
    with pytest.raises(RuntimeError, match="reached the exchange"):
        await oauth.complete_tiktok_oauth_callback(
            object(), code="x", state="a-real-state", oauth_service=svc
        )
    assert svc.verify_state_calls == 1, "state was present and must have been verified"


@pytest.mark.asyncio
async def test_app_review_path_survives_outside_production(monkeypatch) -> None:
    """TikTok's app-review callback carries no state; that flow is deliberately kept.

    Refusing it everywhere would break app review, which is why the guard is
    scoped to production rather than made unconditional.
    """
    monkeypatch.setattr(oauth, "is_production", lambda: False)

    class _Reached(_Service):
        async def handle_callback(self, *a, **k):
            self.handle_callback_calls += 1
            raise RuntimeError("reached app-review path")

    svc = _Reached()
    with pytest.raises(RuntimeError, match="reached app-review path"):
        await oauth.complete_tiktok_oauth_callback(
            object(), code="x", state=None, oauth_service=svc
        )
    assert svc.handle_callback_calls == 1
