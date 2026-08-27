"""The compare-before-write basis must survive the pause/resume boundary.

DEFECT THIS PINS (#1382). `ConcurrencyGuard` holds the basis in memory;
`RunState.basis_snapshots` is what gets persisted and what
`workers/tasks/agent_workflow.py` reads back to seed a fresh guard on resume.
Nothing wrote to it, so the basis was captured on leg 1, discarded at the
pause, and the resume leg started empty.

Every `CONFIRM`-policy write happens on the resume leg **by construction** —
that is what the pause is for — so compare-before-write always compared
against nothing and refused the write as a conflict. Gate #1226 walk run
`675bb11e-3630-4aa4-8950-47837ce9d313` hit exactly this: the seller approved,
the write dispatched, and the tool returned
`{"conflict": true, "current_values": {...}}` with `basis_snapshots` empty.

No existing test crossed that boundary — every concurrency test lived inside
one leg — which is why this shipped. These tests span it.
"""

from __future__ import annotations

from juli_backend.services.agent.runner.concurrency import (
    ConcurrencyGuard,
    capture_basis_snapshot,
    extract_mutable_fields,
)
from juli_backend.services.agent.runner.state import RunState


def _fields(title: str, description: str) -> dict:
    return extract_mutable_fields(
        {"title": title, "description": description, "images": [{"uri": "img-1"}]}
    )


class TestBasisIsCarriedIntoRunState:
    def test_a_recorded_basis_is_mirrored_into_state_and_serializes(self):
        """The write half of the round trip: what the guard captured must land
        in `RunState.basis_snapshots` and survive `to_dict()`."""
        guard = ConcurrencyGuard()
        guard.record_basis(_fields("Nồi lẩu điện mini 1.5L", "<p>mô tả</p>"))

        state = RunState()
        assert state.basis_snapshots == {}, "precondition: a fresh run has no basis"

        state.basis_snapshots = dict(guard.basis_snapshot)

        assert state.basis_snapshots, "the guard's basis must reach state"
        assert state.to_dict()["basis_snapshots"] == state.basis_snapshots

    def test_a_resumed_guard_seeded_from_state_matches_the_original(self):
        """The read half: `agent_workflow.py` seeds a NEW guard from the
        persisted blob. That guard must hold the same basis the first leg
        captured, or the write it authorises is compared against nothing."""
        original = ConcurrencyGuard()
        original.record_basis(_fields("Nồi lẩu điện mini 1.5L", "<p>mô tả</p>"))

        state = RunState()
        state.basis_snapshots = dict(original.basis_snapshot)
        blob = state.to_dict()

        # Exactly what workers/tasks/agent_workflow.py does on resume.
        resumed = ConcurrencyGuard(basis_snapshot=blob.get("basis_snapshots", {}))

        assert resumed.basis_snapshot == original.basis_snapshot
        assert resumed.basis_snapshot, (
            "a resumed guard with an empty basis is the #1382 defect: every "
            "seller-confirmed write is then refused as a conflict"
        )

    def test_an_unpersisted_basis_leaves_the_resumed_guard_empty(self):
        """Non-vacuity — this is the pre-fix path, kept executable so the two
        assertions above cannot quietly become tautologies. Capturing into the
        guard alone, without mirroring into state, strands the basis."""
        guard = ConcurrencyGuard()
        guard.record_basis(_fields("Nồi lẩu điện mini 1.5L", "<p>mô tả</p>"))

        state = RunState()  # nothing mirrored
        resumed = ConcurrencyGuard(basis_snapshot=state.to_dict().get("basis_snapshots", {}))

        assert guard.basis_snapshot, "the guard itself did capture a basis"
        assert resumed.basis_snapshot == {}, (
            "and it was lost across the boundary — the exact failure #1382 fixes"
        )


class TestBasisContentIsMeaningful:
    def test_a_changed_listing_produces_a_different_basis(self):
        """The basis must actually discriminate, or persisting it proves
        nothing: two different listings cannot hash alike."""
        before = capture_basis_snapshot(_fields("Nồi lẩu điện mini 1.5L", "<p>cũ</p>"))
        after = capture_basis_snapshot(_fields("Nồi lẩu điện mini 1.5L", "<p>mới</p>"))
        assert before != after

    def test_an_unchanged_listing_produces_a_stable_basis(self):
        """And it must be stable, or a correct write would be refused as a
        false conflict on every resume."""
        fields = _fields("Nồi lẩu điện mini 1.5L", "<p>mô tả</p>")
        assert capture_basis_snapshot(fields) == capture_basis_snapshot(fields)
