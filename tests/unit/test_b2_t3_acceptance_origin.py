"""t3 fix 4: the calibration pools every origin, but acceptance and the ranking tie-break stay
engine-only (a manual card never moves the defaults or the ranking the engine's cards use)."""

from __future__ import annotations

from juli_backend.services.shopee_recommendations import learning


def _event(event_type, origin, kind="price"):
    return {
        "event_type": event_type,
        "reason_code": None,
        "payload": {"change_kind": kind, "origin": origin},
    }


def test_a_manual_cards_decisions_never_move_the_engines_acceptance():
    engine_only = [_event("accepted", "engine"), _event("dismissed", "engine")]
    both = [*engine_only, *[_event("accepted", "manual")] * 5, _event("expired", "manual")]
    before = learning.acceptance_from_events(engine_only)
    after = learning.acceptance_from_events(both)
    assert after.rate("price") == before.rate("price")  # the ranking tie-break reads this rate
    assert after.json() == before.json()
    split = learning.acceptance_by_origin(both)
    assert split["manual"].approved["price"] == 5 and split["engine"].approved["price"] == 1


def test_acceptance_loading_defaults_to_the_engine_origin():
    import inspect

    from juli_backend.services.shopee_recommendations import store

    assert inspect.signature(store.load_acceptance).parameters["origin"].default == "engine"
    assert inspect.signature(learning.acceptance_from_events).parameters["origin"].default == (
        "engine"
    )
