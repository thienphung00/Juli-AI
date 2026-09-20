"""The OAuth `state` is a security boundary, not a correlation id (issue #1970).

`state` is the ONLY thing that tells the callback which signed-in seller
authorized a shop. If it can be forged, an attacker mints a state naming
somebody else's user id, completes an OAuth handshake with their own TikTok
shop, and the shop lands under the victim's account — or, run the other way,
binds the victim's shop under their own.

These tests hold the primitive to four properties, each one a way the binding
could be broken:

1. a state minted for A verifies back to A, and to nothing else;
2. a state whose payload is edited no longer verifies, even though the edit is
   trivially easy to make;
3. a state signed with a different secret is refused;
4. a state older than its TTL is refused, so a leaked one goes stale.
"""

from __future__ import annotations

import base64
import json
import uuid

import pytest

from juli_backend.core.security.exceptions import Unauthorized
from juli_backend.core.security.oauth_state import (
    DEFAULT_STATE_TTL_SECONDS,
    SELLER_CONNECT_FLOW,
    mint_oauth_state,
    verify_oauth_state,
)

SECRET = "app-secret-under-test"
OTHER_SECRET = "a-different-app-secret"


def _verify(state: str, **overrides):
    kwargs = {"secret": SECRET, "expected_flow": SELLER_CONNECT_FLOW}
    kwargs.update(overrides)
    return verify_oauth_state(state, **kwargs)


def test_round_trip_returns_the_user_the_state_was_minted_for() -> None:
    user_id = uuid.uuid4()
    state = mint_oauth_state(user_id, secret=SECRET, flow=SELLER_CONNECT_FLOW, now=1_000)

    verified = _verify(state, now=1_000)

    assert verified.user_id == user_id
    assert verified.flow == SELLER_CONNECT_FLOW
    assert verified.issued_at == 1_000


def test_two_states_for_the_same_user_differ() -> None:
    """A per-mint nonce, so two connects are not the same bytes on the wire."""
    user_id = uuid.uuid4()
    first = mint_oauth_state(user_id, secret=SECRET, flow=SELLER_CONNECT_FLOW, now=1_000)
    second = mint_oauth_state(user_id, secret=SECRET, flow=SELLER_CONNECT_FLOW, now=1_000)

    assert first != second
    assert _verify(first, now=1_000).user_id == _verify(second, now=1_000).user_id


def test_swapping_the_user_id_in_the_payload_is_refused() -> None:
    """THE attack this signature exists to stop.

    Re-encoding the payload with somebody else's user id is a two-line edit and
    needs no secret. Only the HMAC stands between that and a shop bound to the
    wrong account.
    """
    victim = uuid.uuid4()
    attacker = uuid.uuid4()
    state = mint_oauth_state(victim, secret=SECRET, flow=SELLER_CONNECT_FLOW, now=1_000)

    encoded, signature = state.split(".", 1)
    payload = json.loads(base64.urlsafe_b64decode(encoded))
    payload["user_id"] = str(attacker)
    forged_encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    forged = f"{forged_encoded}.{signature}"

    with pytest.raises(Unauthorized, match="signature"):
        _verify(forged, now=1_000)


def test_a_state_signed_with_another_secret_is_refused() -> None:
    state = mint_oauth_state(uuid.uuid4(), secret=OTHER_SECRET, flow=SELLER_CONNECT_FLOW, now=1_000)

    with pytest.raises(Unauthorized, match="signature"):
        _verify(state, now=1_000)


def test_an_unsigned_state_is_refused() -> None:
    """A bare payload with no signature part at all."""
    encoded = base64.urlsafe_b64encode(
        json.dumps(
            {"user_id": str(uuid.uuid4()), "flow": SELLER_CONNECT_FLOW, "iat": 1_000}
        ).encode()
    ).decode()

    with pytest.raises(Unauthorized):
        _verify(encoded, now=1_000)


def test_a_state_minted_for_another_flow_is_refused() -> None:
    """Flow binding: one handshake's state cannot be replayed into another's."""
    state = mint_oauth_state(uuid.uuid4(), secret=SECRET, flow="some_other_flow", now=1_000)

    with pytest.raises(Unauthorized, match="flow"):
        _verify(state, now=1_000)


def test_a_state_older_than_the_ttl_is_refused() -> None:
    """Expiry. Before #1970 a signed state was valid forever."""
    state = mint_oauth_state(uuid.uuid4(), secret=SECRET, flow=SELLER_CONNECT_FLOW, now=1_000)

    assert _verify(state, now=1_000 + DEFAULT_STATE_TTL_SECONDS).user_id  # boundary: still valid

    with pytest.raises(Unauthorized, match="expired"):
        _verify(state, now=1_000 + DEFAULT_STATE_TTL_SECONDS + 1)


def test_a_state_from_the_far_future_is_refused() -> None:
    """A forward-dated `iat` would otherwise extend the window indefinitely."""
    state = mint_oauth_state(uuid.uuid4(), secret=SECRET, flow=SELLER_CONNECT_FLOW, now=10_000)

    with pytest.raises(Unauthorized, match="not yet valid"):
        _verify(state, now=1_000)


def test_a_state_carrying_no_issue_time_is_refused() -> None:
    """Correctly signed, but undateable — so its window cannot be bounded.

    Guards the shape a pre-#1970 minter produced: same signature construction,
    no `iat`. Accepting it would leave an unexpiring state acceptable forever,
    which is exactly what the TTL was added to end.
    """
    payload = json.dumps({"user_id": str(uuid.uuid4()), "flow": SELLER_CONNECT_FLOW, "nonce": "n"})
    encoded = base64.urlsafe_b64encode(payload.encode()).decode()
    import hashlib
    import hmac

    signature = hmac.new(SECRET.encode(), encoded.encode(), hashlib.sha256).hexdigest()

    with pytest.raises(Unauthorized, match="issue time"):
        _verify(f"{encoded}.{signature}", now=1_000)


def test_garbage_is_refused_rather_than_crashing() -> None:
    for junk in ("", ".", "not-a-state", "a.b", "!!!.###"):
        with pytest.raises(Unauthorized):
            _verify(junk, now=1_000)


def test_minting_with_an_empty_secret_is_refused() -> None:
    """An empty HMAC key produces a signature anyone can reproduce."""
    with pytest.raises(ValueError):
        mint_oauth_state(uuid.uuid4(), secret="", flow=SELLER_CONNECT_FLOW)


def test_verifying_with_an_empty_secret_is_refused() -> None:
    state = mint_oauth_state(uuid.uuid4(), secret=SECRET, flow=SELLER_CONNECT_FLOW, now=1_000)

    with pytest.raises(Unauthorized):
        _verify(state, secret="", now=1_000)
