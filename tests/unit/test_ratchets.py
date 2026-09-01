"""Debt ratchets are identity sets, not counts (#1462, HE-E/P-EVAL-19).

Two of these tests are load-bearing and are written to be *discriminating*: they
must fail against a count-based ratchet. Each one first asserts that the count
is unchanged (or has fallen) — which is what a count-based gate would look at
and pass on — and only then asserts that the ratchet fails anyway.

If you can make `test_identity_move_fails_where_count_would_pass` or
`test_widened_ignore_fails_on_coverage_not_count` pass by comparing two integers,
the implementation has regressed and the test is no longer evidence.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from eval.ratchets import (
    BASELINE_PATH,
    IDENTITY_CLASS,
    MUST_NOT_FALL,
    REPORTED_SUPPRESSION_LINES,
    SCALAR_CLASS,
    Identity,
    MeasurementError,
    baseline_from,
    check,
    load_baseline,
    measure,
    tighten,
    write_baseline,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

SUPPRESSIONS = "suppressions"
COVERAGE = "mypy_statement_coverage"


# --------------------------------------------------------------------------
# synthetic repo helpers
#
# The measurers take a `repo_root`, so a test can build a miniature repository
# on disk and run the *real* measurement against it. Nothing here monkeypatches
# the measurement itself — a fake measurer would only prove the comparison
# logic, not that the comparison is fed a real reading.
# --------------------------------------------------------------------------


def _write(root: Path, rel: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return path


def _mini_repo(tmp_path: Path) -> Path:
    """A repo with the src layout and a mypy config the coverage class can read."""
    root = tmp_path / "repo"
    _write(
        root,
        "backend/pyproject.toml",
        """
        [tool.mypy]
        python_version = "3.12"
        ignore_missing_imports = true
        """,
    )
    _write(root, "backend/src/juli_backend/__init__.py", '"""pkg."""\n')
    return root


def _suppressed_module(count: int) -> str:
    lines = ['"""Module docstring."""', "", "import os", "", ""]
    lines.append("def handler(payload):")
    for i in range(count):
        lines.append(f"    value_{i} = os.environ.get(payload)  # type: ignore[arg-type]")
    lines.append("    return value_0")
    return "\n".join(lines) + "\n"


def _clean_module() -> str:
    return '"""Module docstring."""\n\n\ndef handler(payload):\n    return payload\n'


# --------------------------------------------------------------------------
# AC1 — the baseline captures every suppression currently in the tree
# --------------------------------------------------------------------------


def test_baseline_captures_394_suppression_identities() -> None:
    """The committed baseline is exactly what the tree measures right now.

    #1462 reports 394 suppression *lines* (144 `type: ignore` + 250 `noqa`).
    That number was verified against an earlier `origin/main`; the ratchet's job
    is to freeze what is actually there, so the assertion below is set equality
    against a live measurement, and the reported figure is carried as a recorded
    reference with its divergence spelled out rather than quietly rounded away.
    """
    baseline = load_baseline(BASELINE_PATH)
    live = measure(REPO_ROOT, classes=[SUPPRESSIONS])

    assert not live.errors, f"suppression measurement must not fail closed: {live.errors}"

    measured = live.classes[SUPPRESSIONS]
    recorded = baseline["classes"][SUPPRESSIONS]

    assert recorded["kind"] == IDENTITY_CLASS
    assert {i.key(): n for i, n in measured.occurrences.items()} == recorded["occurrences"], (
        "the committed baseline has drifted from the tree; regenerate it with "
        "`python -m eval.ratchets measure --write` on merge, never mid-PR"
    )

    # Every suppression in the tree is in the set — nothing is silently dropped.
    assert measured.total == recorded["stats"]["occurrences"]
    assert measured.stats["lines"] == recorded["stats"]["lines"]

    # The reported figure, and the divergence from it, are both recorded facts.
    # `measured` is the like-for-like reading over the four roots #1462 counted.
    assert REPORTED_SUPPRESSION_LINES == 394
    divergence = baseline["classes"][SUPPRESSIONS]["reportedLineDivergence"]
    like_for_like = measured.stats["lines_in_reported_roots"]
    assert divergence["reported"] == REPORTED_SUPPRESSION_LINES
    assert divergence["measured"] == like_for_like
    assert divergence["delta"] == like_for_like - REPORTED_SUPPRESSION_LINES
    assert divergence["measuredAllRoots"] == measured.stats["lines"]

    # A real repository, not an empty scan.
    assert like_for_like >= REPORTED_SUPPRESSION_LINES
    assert measured.stats["files_scanned"] > 500


# --------------------------------------------------------------------------
# AC2 — the first gaming path: same count, worse codebase
# --------------------------------------------------------------------------


def test_identity_move_fails_where_count_would_pass(tmp_path: Path) -> None:
    """Move five suppressions from a dead module into a shipped one.

    The count is unchanged, so a count-based ratchet passes. The identity set
    has five new members, so this one fails.
    """
    root = _mini_repo(tmp_path)
    dead = _write(root, "backend/src/juli_backend/dead_module.py", _suppressed_module(5))
    shipped = _write(root, "backend/src/juli_backend/shipped_module.py", _clean_module())

    before = measure(root, classes=[SUPPRESSIONS])
    baseline = baseline_from(before)
    assert before.classes[SUPPRESSIONS].total == 5

    # The move: five suppressions leave dead code and land in shipped code.
    dead.write_text(_clean_module(), encoding="utf-8")
    shipped.write_text(_suppressed_module(5), encoding="utf-8")

    after = measure(root, classes=[SUPPRESSIONS])

    # --- what a count-based ratchet sees -------------------------------------
    # Identical totals *and* identical per-rule-code tallies. Any gate that
    # reduces debt to a number passes here. This assertion is what makes the
    # test discriminating; do not delete it.
    assert after.classes[SUPPRESSIONS].total == before.classes[SUPPRESSIONS].total == 5
    assert after.classes[SUPPRESSIONS].stats["lines"] == before.classes[SUPPRESSIONS].stats["lines"]
    assert (
        after.classes[SUPPRESSIONS].stats["by_rule_code"]
        == (before.classes[SUPPRESSIONS].stats["by_rule_code"])
    )

    # --- what the identity ratchet sees --------------------------------------
    result = check(baseline, after)
    assert result.ok is False

    new_paths = {v.identity.path for v in result.violations if v.identity is not None}
    assert new_paths == {"backend/src/juli_backend/shipped_module.py"}
    assert all(v.kind == "new_identity" for v in result.violations)

    # The dead-code identities are recorded as departed, not as credit that
    # offsets the arrivals.
    assert {i.path for i in result.departed} == {"backend/src/juli_backend/dead_module.py"}


# --------------------------------------------------------------------------
# AC3 — the second gaming path: the count *falls* and the codebase is worse
# --------------------------------------------------------------------------


def test_widened_ignore_fails_on_coverage_not_count(tmp_path: Path) -> None:
    """Widen `ignore_errors` and delete the suppressions it makes unnecessary.

    The suppression count falls to zero, so a count-based ratchet reads the
    single worst available action as the largest possible improvement. The
    paired `mypy_statement_coverage` guard is what catches it.
    """
    root = _mini_repo(tmp_path)
    legacy = _write(root, "backend/src/juli_backend/legacy.py", _suppressed_module(6))

    before = measure(root, classes=[SUPPRESSIONS, COVERAGE])
    baseline = baseline_from(before)
    assert before.classes[SUPPRESSIONS].total == 6
    assert before.classes[COVERAGE].scalar == pytest.approx(1.0)
    assert before.classes[COVERAGE].direction == MUST_NOT_FALL

    # The widening: mypy stops checking the module, so the ignores can go.
    _write(
        root,
        "backend/pyproject.toml",
        """
        [tool.mypy]
        python_version = "3.12"
        ignore_missing_imports = true

        [[tool.mypy.overrides]]
        module = ["juli_backend.legacy"]
        ignore_errors = true
        """,
    )
    legacy.write_text(_clean_module(), encoding="utf-8")

    after = measure(root, classes=[SUPPRESSIONS, COVERAGE])

    # --- what a count-based ratchet sees -------------------------------------
    # The count did not merely hold, it fell to zero. A count-based gate scores
    # this as progress and tightens the baseline to reward it.
    assert after.classes[SUPPRESSIONS].total == 0
    assert after.classes[SUPPRESSIONS].total < before.classes[SUPPRESSIONS].total
    # No new identity entered the suppression set either, so the identity half
    # of the ratchet is clean on its own. Only the coverage guard can fail here.
    suppression_result = check(
        {"classes": {SUPPRESSIONS: baseline["classes"][SUPPRESSIONS]}},
        measure(root, classes=[SUPPRESSIONS]),
    )
    assert suppression_result.ok is True

    # --- what the paired coverage guard sees ---------------------------------
    assert after.classes[COVERAGE].scalar < before.classes[COVERAGE].scalar

    result = check(baseline, after)
    assert result.ok is False
    assert [v.debt_class for v in result.violations] == [COVERAGE]
    assert result.violations[0].kind == "scalar_regression"
    assert "juli_backend.legacy" in json.dumps(after.classes[COVERAGE].stats)


# --------------------------------------------------------------------------
# AC4 — a genuine fix passes, and only merge tightens the baseline
# --------------------------------------------------------------------------


def test_genuine_fix_passes_and_tightens_on_merge(tmp_path: Path) -> None:
    root = _mini_repo(tmp_path)
    module = _write(root, "backend/src/juli_backend/service.py", _suppressed_module(3))
    baseline_file = tmp_path / "baseline.json"

    before = measure(root, classes=[SUPPRESSIONS])
    write_baseline(baseline_file, baseline_from(before))
    baseline = load_baseline(baseline_file)
    frozen_bytes = baseline_file.read_bytes()

    # The fix: one suppression removed because the underlying error is gone.
    module.write_text(_suppressed_module(2), encoding="utf-8")
    after = measure(root, classes=[SUPPRESSIONS])

    result = check(baseline, after)
    assert result.ok is True
    assert result.violations == ()
    assert after.classes[SUPPRESSIONS].total == 2

    # Mid-PR, `check` is read-only. The baseline on disk is byte-identical.
    assert baseline_file.read_bytes() == frozen_bytes

    # On merge, `tighten` moves the floor down.
    tightened = tighten(baseline, after)
    write_baseline(baseline_file, tightened)
    assert tightened["classes"][SUPPRESSIONS]["stats"]["occurrences"] == 2
    assert check(load_baseline(baseline_file), after).ok is True

    # And the floor holds: putting the third suppression back now fails, which
    # it did not before the merge tightened the baseline.
    module.write_text(_suppressed_module(3), encoding="utf-8")
    regressed = measure(root, classes=[SUPPRESSIONS])
    assert check(baseline, regressed).ok is True  # against the pre-merge floor
    assert check(load_baseline(baseline_file), regressed).ok is False  # against the tightened one


# --------------------------------------------------------------------------
# AC5 — an unmeasurable class fails; it is never treated as clean
# --------------------------------------------------------------------------


def test_unmeasurable_class_fails_closed(tmp_path: Path) -> None:
    root = _mini_repo(tmp_path)
    _write(root, "backend/src/juli_backend/service.py", _suppressed_module(2))

    good = measure(root, classes=[SUPPRESSIONS])
    baseline = baseline_from(good)

    # (a) the measurer itself raises
    def _explode(_repo_root: Path):
        raise MeasurementError("mypy config unreadable")

    broken = measure(root, classes=[SUPPRESSIONS], measurers={SUPPRESSIONS: _explode})
    assert broken.errors[SUPPRESSIONS]
    assert SUPPRESSIONS not in broken.classes
    result = check(baseline, broken)
    assert result.ok is False
    assert [v.kind for v in result.violations] == ["unmeasurable"]
    assert "mypy config unreadable" in result.violations[0].detail

    # (b) an unparseable source file is a measurement failure, not a clean scan
    (root / "backend/src/juli_backend/broken.py").write_text("def (:\n", encoding="utf-8")
    syntax = measure(root, classes=[SUPPRESSIONS])
    assert syntax.errors, "a file that cannot be parsed must fail the class"
    assert check(baseline, syntax).ok is False

    # (c) a baselined class that the measurement never produced
    empty = measure(root, classes=[])
    assert check(baseline, empty).ok is False
    assert check(baseline, empty).violations[0].kind == "missing_class"

    # (d) a measured class with no baseline entry — unknown is not clean
    assert check({"classes": {}}, good).ok is False
    assert check({"classes": {}}, good).violations[0].kind == "unbaselined_class"

    # (e) a corrupt baseline file is an error, never an empty (permissive) set
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    with pytest.raises(MeasurementError):
        load_baseline(corrupt)

    # (f) an absent baseline file
    with pytest.raises(MeasurementError):
        load_baseline(tmp_path / "nope.json")

    # (g) a real measurer against a repo missing its inputs
    bare = tmp_path / "bare"
    bare.mkdir()
    tier1 = measure(bare, classes=["tier1_always_on_tokens"])
    assert tier1.errors, "a missing CLAUDE.md must fail the Tier-1 class, not read as 0 tokens"


# --------------------------------------------------------------------------
# identity shape
# --------------------------------------------------------------------------


def test_identity_is_a_triple_and_round_trips() -> None:
    identity = Identity(SUPPRESSIONS, "backend/src/juli_backend/x.py", "Foo.bar", "noqa:E501")
    assert Identity.parse(identity.key()) == identity
    assert identity.path and identity.symbol and identity.rule_code


def test_scalar_and_identity_classes_are_both_present_in_the_committed_baseline() -> None:
    baseline = load_baseline(BASELINE_PATH)
    kinds = {name: cls["kind"] for name, cls in baseline["classes"].items()}
    assert kinds[SUPPRESSIONS] == IDENTITY_CLASS
    assert kinds[COVERAGE] == SCALAR_CLASS
    assert baseline["classes"][COVERAGE]["direction"] == MUST_NOT_FALL
    # every debt class named in the issue is baselined
    assert {
        SUPPRESSIONS,
        COVERAGE,
        "unused_ts_exports",
        "broken_doc_refs",
        "tier1_always_on_tokens",
    } <= set(kinds)
