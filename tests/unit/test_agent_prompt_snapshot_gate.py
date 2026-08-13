"""Snapshot gate — issue #1039 (W2-A/P12-4, ADR-072 decision 6, gate 1 of 4).

ADR-072 d.4: a released `vN.md` is never edited; any change becomes a new
version. This test is what makes that immutability promise *enforced* rather
than merely documented: it pins `compose("optimize_product_2", 1)`'s exact
composed bytes against a committed golden fixture
(`tests/fixtures/agent_prompt_gates/optimize_product_v1_composed.golden.md`),
so an edit to the real `v1.md` after release breaks this test loudly, naming
the mismatch.

`TestSnapshotCatchesAOneByteMutation` below proves that claim by *execution*
rather than by asserting it in prose: it copies the real prompts directory
tree to a pytest `tmp_path`, mutates the copy's `v1.md` by exactly one ASCII
byte, points a fresh `compose()` call at the copy via the same
`_PROMPTS_ROOT` monkeypatch seam `test_agent_prompt_compose.py` already uses
for its own integrity-guard tests, and shows the mutated output no longer
matches the golden snapshot. **The real, released `v1.md` in the repo is
never touched by this file** — every mutation happens on a `shutil.copytree`
copy under `tmp_path`, never on the source tree.

This file writes paths only under `tests/unit/` and
`tests/fixtures/agent_prompt_gates/` (a snapshot fixture location under
`tests/`, per issue #1039's write-path constraint) -- it does not edit
`v1.md`, the `Playbook`, or `composer.py`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import juli_backend.services.agent.prompts.composer as compose_module
from juli_backend.services.agent.playbooks.optimize_product import WORKFLOW_KEY
from juli_backend.services.agent.prompts.composer import compose

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PATH = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "agent_prompt_gates"
    / "optimize_product_v1_composed.golden.md"
)

#: The real `prompts/` directory `compose()` reads from in production --
#: `composer.py`'s own `_PROMPTS_ROOT` (this module's parent directory).
#: Read here only to build a `shutil.copytree` copy in the mutation-proof
#: test below; never written to.
_REAL_PROMPTS_ROOT = compose_module._PROMPTS_ROOT


def _regenerate_golden_fixture() -> None:
    """Regenerate the committed golden snapshot. See the module docstring's
    "Regenerating the golden fixtures" convention already established by
    `tests/unit/test_agent_sanitize_golden.py` -- run directly, never
    imported/called by pytest:

        PYTHONPATH=$PWD/backend/src python3 tests/unit/test_agent_prompt_snapshot_gate.py

    Deterministic and idempotent: with no source change, running it again
    produces a byte-identical file.
    """
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    composed = compose(WORKFLOW_KEY, 1)
    GOLDEN_PATH.write_bytes(composed.encode("utf-8"))


def _assert_matches_golden_snapshot(composed: str, golden_bytes: bytes) -> None:
    """The one comparison this whole gate exists to make: byte-for-byte,
    never a normalized/stripped/re-encoded comparison. Used by both the real
    gate test below and the mutation-proof test, so the mutation-proof test
    exercises the *actual* gate logic rather than a parallel hand-written
    inequality check.
    """
    actual_bytes = composed.encode("utf-8")
    assert actual_bytes == golden_bytes, (
        "composed prompt no longer matches the committed golden snapshot -- "
        f"a released prompt version file changed after release (expected "
        f"{len(golden_bytes)} bytes, got {len(actual_bytes)} bytes)"
    )


# ---------------------------------------------------------------------------
# The real gate: compose(WORKFLOW_KEY, 1) matches the committed golden bytes.
# ---------------------------------------------------------------------------


def test_golden_fixture_is_present_and_non_empty():
    assert GOLDEN_PATH.is_file(), f"missing golden snapshot fixture at {GOLDEN_PATH}"
    assert GOLDEN_PATH.stat().st_size > 0


def test_composed_prompt_matches_golden_snapshot_byte_for_byte():
    composed = compose(WORKFLOW_KEY, 1)
    golden_bytes = GOLDEN_PATH.read_bytes()
    _assert_matches_golden_snapshot(composed, golden_bytes)


def test_golden_fixture_matches_the_deterministic_regeneration_byte_for_byte():
    """The committed golden file is not hand-edited -- it is exactly what
    `_regenerate_golden_fixture` would (re)write, checked the same way
    `test_agent_sanitize_golden.py` checks its own golden fixtures against
    their deterministic builder.
    """
    composed = compose(WORKFLOW_KEY, 1)
    assert composed.encode("utf-8") == GOLDEN_PATH.read_bytes()


# ---------------------------------------------------------------------------
# Proof: a one-byte mutation to v1.md fails the snapshot -- by execution
# against a COPY, never against the real repo file.
# ---------------------------------------------------------------------------


class TestSnapshotCatchesAOneByteMutation:
    def test_mutating_a_copy_of_v1_md_by_one_byte_fails_the_snapshot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # 1. Copy the real prompts tree -- never mutate the repo's own file.
        copied_root = tmp_path / "prompts_copy"
        shutil.copytree(_REAL_PROMPTS_ROOT, copied_root)

        binding = compose_module._binding_for(WORKFLOW_KEY)
        copied_v1 = copied_root / binding.prompt_dir / "v1.md"
        assert copied_v1.is_file()

        # 2. Prove the copy is byte-identical to the real file before mutation
        #    -- otherwise "one byte different" below would be meaningless.
        real_v1 = _REAL_PROMPTS_ROOT / binding.prompt_dir / "v1.md"
        original_bytes = real_v1.read_bytes()
        assert copied_v1.read_bytes() == original_bytes

        # 3. Mutate the COPY by exactly one ASCII byte -- append a single
        #    trailing character. This changes the copy's length by exactly
        #    one byte in UTF-8 (an ASCII character is always one byte,
        #    unlike this file's Vietnamese prose, where a single character
        #    can be multiple UTF-8 bytes) and does not disturb the file's
        #    lone `{playbook}` slot, which sits earlier in the file.
        mutated_bytes = original_bytes + b"."
        copied_v1.write_bytes(mutated_bytes)
        assert len(mutated_bytes) == len(original_bytes) + 1

        # 4. Confirm the real repo file is untouched by step 3.
        assert real_v1.read_bytes() == original_bytes

        # 5. Point compose() at the mutated COPY only, via the same
        #    _PROMPTS_ROOT monkeypatch seam test_agent_prompt_compose.py
        #    already uses -- never edits composer.py itself.
        monkeypatch.setattr(compose_module, "_PROMPTS_ROOT", copied_root)
        mutated_composed = compose(WORKFLOW_KEY, 1)

        # 6. The mutated compose() output must differ from the committed
        #    golden bytes -- read from the static fixture file, so this
        #    comparison is unaffected by the _PROMPTS_ROOT monkeypatch above.
        golden_bytes = GOLDEN_PATH.read_bytes()
        assert mutated_composed.encode("utf-8") != golden_bytes

        # 7. The actual assertion this whole gate exists to make: running
        #    the real snapshot comparison helper against the mutated output
        #    raises, naming the mismatch.
        with pytest.raises(AssertionError, match="no longer matches"):
            _assert_matches_golden_snapshot(mutated_composed, golden_bytes)

        # 8. Final confirmation: the real repo file is still untouched after
        #    the whole test ran.
        assert real_v1.read_bytes() == original_bytes


if __name__ == "__main__":
    _regenerate_golden_fixture()
