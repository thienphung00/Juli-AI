"""Snapshot gate -- issue #1039 (W2-A/P12-4, ADR-072 decision 6, gate 1 of 4),
parametrised per workflow by issue #1705 (W9-A/P-SHARED-5).

ADR-072 d.4: a released `vN.md` is never edited; any change becomes a new
version. This test is what makes that immutability promise *enforced* rather
than merely documented: it pins every registered workflow's composed bytes,
at every version it has released, against a committed golden fixture under
`tests/fixtures/agent_prompt_gates/`, so an edit to a released prose file --
**or to a shared section a released version composes from** (#1705) -- breaks
this test loudly, naming the mismatch.

## Parametrised, not hand-listed (#1705)

The cases come from `registered_workflow_keys()` x `released_versions(key)`,
both read off the composer's own registry and the prose files actually on
disk. A second workflow's prompt is covered by this gate the moment its
binding is registered, with no edit here; a new released version is covered
the moment its `vN.md` lands. Each case is its own pytest parameter with its
own golden file, so a failure names the workflow and version that drifted
rather than reporting "the snapshot broke".

## The proofs, by execution rather than by assertion in prose

`TestSnapshotCatchesAOneByteMutation` copies the real `prompts/` tree to a
pytest `tmp_path`, mutates the **copy** by exactly one ASCII byte, points a
fresh `compose()` call at the copy via the same `_PROMPTS_ROOT` monkeypatch
seam `test_agent_prompt_compose.py` already uses, and shows the mutated
output no longer matches the golden snapshot. `TestSharedSectionMutation`
does the same to a shared section file and shows the asymmetry that proves
the extraction is real: the post-extraction version's snapshot breaks, the
pre-extraction versions' snapshots do not. **The real, released files in the
repo are never touched by this file** -- every mutation happens on a
`shutil.copytree` copy under `tmp_path`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import juli_backend.services.agent.prompts.composer as compose_module
from juli_backend.services.agent.playbooks.optimize_product import WORKFLOW_KEY
from juli_backend.services.agent.prompts.composer import (
    SHARED_SECTIONS,
    compose,
    production_version,
    registered_workflow_keys,
    released_versions,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "agent_prompt_gates"

#: The real `prompts/` directory `compose()` reads from in production --
#: `composer.py`'s own `_PROMPTS_ROOT` (that module's parent directory).
#: Read here only to build `shutil.copytree` copies in the mutation proofs
#: below; never written to.
_REAL_PROMPTS_ROOT = compose_module._PROMPTS_ROOT


def golden_path(workflow_key: str, version: int) -> Path:
    """The committed golden snapshot for one `(workflow_key, version)` pair.

    Named by the *prompt directory*, not the `workflow_key` -- the same
    namespace `prompt_version()` uses (ADR-072 d.4), so a fixture file name
    and a recorded `prompt_version` string read as the same thing.
    """
    prompt_dir = compose_module._binding_for(workflow_key).prompt_dir
    return GOLDEN_DIR / f"{prompt_dir}_v{version}_composed.golden.md"


def released_workflow_versions() -> list[tuple[str, int]]:
    """Every `(workflow_key, version)` pair this gate covers, read at call
    time from the registry and the prose files on disk."""
    return [
        (workflow_key, version)
        for workflow_key in registered_workflow_keys()
        for version in released_versions(workflow_key)
    ]


_CASES = released_workflow_versions()
_CASE_IDS = [f"{key}-v{version}" for key, version in _CASES]


def _regenerate_golden_fixtures() -> None:
    """Regenerate the committed golden snapshots. Run directly, never
    imported/called by pytest:

        PYTHONPATH=$PWD/backend/src python3 tests/unit/test_agent_prompt_snapshot_gate.py

    Deterministic and idempotent: with no source change, running it again
    produces byte-identical files. Covers exactly the cases the gate below
    asserts, so a released version can never have a gate case with no
    fixture or a fixture with no gate case.
    """
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for workflow_key, version in released_workflow_versions():
        path = golden_path(workflow_key, version)
        path.write_bytes(compose(workflow_key, version).encode("utf-8"))
        print(f"wrote {path.relative_to(REPO_ROOT)}")


def _assert_matches_golden_snapshot(composed: str, golden_bytes: bytes) -> None:
    """The one comparison this whole gate exists to make: byte-for-byte,
    never a normalized/stripped/re-encoded comparison. Used by the real gate
    tests below, by the mutation proofs, and by
    `test_agent_prompt_shared_sections.py`'s second-workflow case, so every
    one of them exercises the *actual* gate logic rather than a parallel
    hand-written inequality check.
    """
    actual_bytes = composed.encode("utf-8")
    assert actual_bytes == golden_bytes, (
        "composed prompt no longer matches the committed golden snapshot -- "
        f"a released prompt version file changed after release (expected "
        f"{len(golden_bytes)} bytes, got {len(actual_bytes)} bytes)"
    )


# ---------------------------------------------------------------------------
# The real gate, once per registered workflow per released version.
# ---------------------------------------------------------------------------


def test_the_gate_has_at_least_one_case_per_registered_workflow():
    """A parametrisation that collected nothing would pass in silence."""
    assert _CASES, "the snapshot gate collected no (workflow, version) cases"
    covered = {workflow_key for workflow_key, _ in _CASES}
    assert covered == set(registered_workflow_keys())


@pytest.mark.parametrize(("workflow_key", "version"), _CASES, ids=_CASE_IDS)
def test_golden_fixture_is_present_and_non_empty(workflow_key: str, version: int):
    path = golden_path(workflow_key, version)
    assert path.is_file(), f"missing golden snapshot fixture at {path}"
    assert path.stat().st_size > 0


@pytest.mark.parametrize(("workflow_key", "version"), _CASES, ids=_CASE_IDS)
def test_composed_prompt_matches_golden_snapshot_byte_for_byte(workflow_key: str, version: int):
    composed = compose(workflow_key, version)
    _assert_matches_golden_snapshot(composed, golden_path(workflow_key, version).read_bytes())


@pytest.mark.parametrize(("workflow_key", "version"), _CASES, ids=_CASE_IDS)
def test_golden_fixture_matches_the_deterministic_regeneration_byte_for_byte(
    workflow_key: str, version: int
):
    """The committed golden file is not hand-edited -- it is exactly what
    `_regenerate_golden_fixtures` would (re)write."""
    composed = compose(workflow_key, version)
    assert composed.encode("utf-8") == golden_path(workflow_key, version).read_bytes()


def test_no_orphan_golden_fixture_survives_a_retired_version():
    """Every committed golden belongs to a case the gate actually asserts.

    Without this, deleting a prose version would leave its golden behind as
    a file nothing reads -- and a stale fixture that nothing compares against
    is indistinguishable from a passing one.
    """
    expected = {golden_path(key, version) for key, version in _CASES}
    actual = set(GOLDEN_DIR.glob("*_composed.golden.md"))
    assert actual == expected, f"orphan golden fixture(s): {sorted(actual - expected)}"


# ---------------------------------------------------------------------------
# Proof: a one-byte mutation to a released prose file fails the snapshot --
# by execution against a COPY, never against the real repo file.
# ---------------------------------------------------------------------------


class TestSnapshotCatchesAOneByteMutation:
    @pytest.mark.parametrize(("workflow_key", "version"), _CASES, ids=_CASE_IDS)
    def test_mutating_a_copy_of_the_prose_file_by_one_byte_fails_the_snapshot(
        self, workflow_key: str, version: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # 1. Copy the real prompts tree -- never mutate the repo's own file.
        copied_root = tmp_path / "prompts_copy"
        shutil.copytree(_REAL_PROMPTS_ROOT, copied_root)

        prompt_dir = compose_module._binding_for(workflow_key).prompt_dir
        copied_prose = copied_root / prompt_dir / f"v{version}.md"
        assert copied_prose.is_file()

        # 2. Prove the copy is byte-identical to the real file before
        #    mutation -- otherwise "one byte different" below would be
        #    meaningless.
        real_prose = _REAL_PROMPTS_ROOT / prompt_dir / f"v{version}.md"
        original_bytes = real_prose.read_bytes()
        assert copied_prose.read_bytes() == original_bytes

        # 3. Mutate the COPY by exactly one ASCII byte -- append a single
        #    trailing character. An ASCII character is always one UTF-8 byte
        #    (unlike this file's Vietnamese prose), and appending after the
        #    end does not disturb the file's slots, which sit earlier.
        mutated_bytes = original_bytes + b"."
        copied_prose.write_bytes(mutated_bytes)
        assert len(mutated_bytes) == len(original_bytes) + 1

        # 4. Confirm the real repo file is untouched by step 3.
        assert real_prose.read_bytes() == original_bytes

        # 5. Point compose() at the mutated COPY only, via the same
        #    _PROMPTS_ROOT monkeypatch seam test_agent_prompt_compose.py
        #    already uses -- never edits composer.py itself.
        monkeypatch.setattr(compose_module, "_PROMPTS_ROOT", copied_root)
        mutated_composed = compose(workflow_key, version)

        # 6. The mutated compose() output must differ from the committed
        #    golden bytes -- read from the static fixture file, so this
        #    comparison is unaffected by the _PROMPTS_ROOT monkeypatch above.
        golden_bytes = golden_path(workflow_key, version).read_bytes()
        assert mutated_composed.encode("utf-8") != golden_bytes

        # 7. The actual assertion this whole gate exists to make: running the
        #    real snapshot comparison helper against the mutated output
        #    raises, naming the mismatch.
        with pytest.raises(AssertionError, match="no longer matches"):
            _assert_matches_golden_snapshot(mutated_composed, golden_bytes)

        # 8. Final confirmation: the real repo file is still untouched after
        #    the whole test ran.
        assert real_prose.read_bytes() == original_bytes


# ---------------------------------------------------------------------------
# Proof (#1705): editing a SHARED section moves every post-extraction
# workflow's snapshot, and leaves the pre-extraction versions alone.
# ---------------------------------------------------------------------------


class TestSharedSectionMutation:
    """The asymmetry here is the whole claim of the extraction.

    If mutating a shared section did not break the post-extraction golden,
    the shared file would not actually be in the composition and this gate
    would be testing nothing about it. If it also broke the pre-extraction
    goldens, ADR-072 d.4's promise -- that `compose("optimize_product_2", 1)`
    still reproduces exactly the bytes v1 shipped -- would be gone.
    """

    def _copy_with_mutated_shared_section(self, tmp_path: Path) -> Path:
        copied_root = tmp_path / "prompts_copy"
        shutil.copytree(_REAL_PROMPTS_ROOT, copied_root)
        section = SHARED_SECTIONS[0]
        copied_section = copied_root / section.relative_path
        assert copied_section.is_file(), f"no shared section file at {copied_section}"
        copied_section.write_bytes(copied_section.read_bytes() + b".")
        return copied_root

    def test_mutating_a_shared_section_breaks_the_post_extraction_snapshot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        version = production_version(WORKFLOW_KEY)
        golden_bytes = golden_path(WORKFLOW_KEY, version).read_bytes()

        copied_root = self._copy_with_mutated_shared_section(tmp_path)
        monkeypatch.setattr(compose_module, "_PROMPTS_ROOT", copied_root)

        with pytest.raises(AssertionError, match="no longer matches"):
            _assert_matches_golden_snapshot(compose(WORKFLOW_KEY, version), golden_bytes)

    def test_mutating_a_shared_section_leaves_the_pre_extraction_snapshots_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        pre_extraction = [
            version
            for version in released_versions(WORKFLOW_KEY)
            if "{shared_"
            not in compose_module._prose_path("optimize_product", version).read_text(
                encoding="utf-8"
            )
        ]
        assert pre_extraction, "expected at least one pre-extraction released version"

        copied_root = self._copy_with_mutated_shared_section(tmp_path)
        monkeypatch.setattr(compose_module, "_PROMPTS_ROOT", copied_root)

        for version in pre_extraction:
            # Must not raise: a version that composes from no shared section
            # cannot be moved by editing one.
            _assert_matches_golden_snapshot(
                compose(WORKFLOW_KEY, version), golden_path(WORKFLOW_KEY, version).read_bytes()
            )

    def test_the_real_shared_section_files_are_untouched_by_the_mutation_proofs(
        self, tmp_path: Path
    ):
        before = {
            section.relative_path: (_REAL_PROMPTS_ROOT / section.relative_path).read_bytes()
            for section in SHARED_SECTIONS
        }
        self._copy_with_mutated_shared_section(tmp_path)
        after = {
            section.relative_path: (_REAL_PROMPTS_ROOT / section.relative_path).read_bytes()
            for section in SHARED_SECTIONS
        }
        assert before == after


if __name__ == "__main__":
    _regenerate_golden_fixtures()
