"""#1732 AC3 — `acceptance_criteria_mapped` derives its count from the issue
body, not from the artifact under review, and fails when the two disagree,
naming both numbers.

#1879 extends the same gate: the issue-body parser only ever recognised
numbered lists (`1.`, `2.`, ...), but the canonical shape `to-issues` writes
— and every architect-authored issue carries — is a GIVEN/WHEN/THEN bullet
(`- GIVEN ... WHEN ... THEN ...`). The parser was blind to that shape and
reported the section as "missing" even when it was present and populated.

The gate calls `load_review_artifact` first and returns early ("Review
artifact missing") if it is None — stubbing only the issue-body lookup and
leaving `load_review_artifact` unstubbed makes every exhibit fail for the
wrong reason (a missing artifact, not a count mismatch). Both must be
stubbed for the three branches below to prove anything.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _cam():
    """Import the gate behind its path shim, without an E402 suppression.

    A module-level sys.path.insert followed by a late import is an E402;
    silencing it adds a suppression identity the ratchet then carries forever.
    Deferring the import keeps the debt set unchanged.
    """
    sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts" / "ci"))
    sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts" / "validate"))
    import check_acceptance_mapping

    return check_acceptance_mapping


# A real, stable pytest node that the gate's `pytest_node_exists` /
# `criterion_matches_test` checks can resolve — this very function, in this
# very file. Not "test_"-prefixed so pytest does not also collect it as a
# test in its own right; `pytest_node_exists` only requires a FunctionDef.
def acceptance_mapping_fixture_target() -> None:
    pass


FIXTURE_NODE = "tests/unit/test_check_acceptance_mapping.py::acceptance_mapping_fixture_target"


def _review(total: int, mapped: int) -> dict:
    mappings = [
        {"criterion": "Acceptance mapping fixture target", "test": FIXTURE_NODE}
        for _ in range(mapped)
    ]
    return {
        "testCoverage": {
            "acceptance": {
                "total": total,
                "mapped": mapped,
                "mappings": mappings,
                "unmapped": [],
            }
        }
    }


def _no_gh_available(*_args: object, **_kwargs: object) -> None:
    """Stand-in for a sandbox with no `gh` binary at all."""
    raise FileNotFoundError("gh: command not found")


class _GhResult:
    """A minimal stand-in for `subprocess.run`'s return value."""

    def __init__(self, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode


def _spy_run_returning(stdout: str) -> callable:
    calls: list[list[str]] = []

    def _run(cmd: list[str], **_kwargs: object) -> _GhResult:
        calls.append(cmd)
        return _GhResult(stdout)

    _run.calls = calls  # type: ignore[attr-defined]
    return _run


def test_lookup_unavailable_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The issue body is unreadable (gh unavailable/unauthenticated/no
    section) — the gate must fail closed rather than trust the artifact's
    own count."""
    cam = _cam()
    monkeypatch.setattr(cam, "load_review_artifact", lambda issue: _review(1, 1))
    monkeypatch.setattr(cam, "extract_criteria_count_from_issue_body", lambda issue: None)
    # run_check also derives a *reason* for its message, via a real (second)
    # gh call on the failure path — mock it too so this test makes no
    # network call regardless of what run_check does internally.
    monkeypatch.setattr(cam.subprocess, "run", _no_gh_available)

    passed, message, details = cam.run_check(1732)

    assert passed is False
    assert any("cannot read the acceptance-criteria count" in p for p in details["problems"])
    assert "issue_criteria_count" not in details


def test_count_matches_issue_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The middle case: a real count from the issue body that agrees with the
    artifact. Without this branch a gate that always fails looks identical to
    one that correctly fails closed."""
    monkeypatch.setattr(_cam(), "load_review_artifact", lambda issue: _review(1, 1))
    monkeypatch.setattr(_cam(), "extract_criteria_count_from_issue_body", lambda issue: 1)

    passed, message, details = _cam().run_check(1732)

    assert passed is True, details
    assert details["problems"] == []
    assert details["issue_criteria_count"] == 1


def test_count_disagrees_fails_naming_both_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exhibit from the issue: total: 1 recorded against a three-criterion
    issue must fail, and the failure must name both numbers."""
    monkeypatch.setattr(_cam(), "load_review_artifact", lambda issue: _review(1, 1))
    monkeypatch.setattr(_cam(), "extract_criteria_count_from_issue_body", lambda issue: 3)

    passed, message, details = _cam().run_check(1732)

    assert passed is False
    problem = next(p for p in details["problems"] if "criteria count from issue" in p)
    assert "1" in problem
    assert "3" in problem
    assert details["issue_criteria_count"] == 3


# ---------------------------------------------------------------------------
# #1761 — the criteria-count fact becomes injectable, without ever letting
# production pass because the fact was withheld.
# ---------------------------------------------------------------------------


def test_ac2_no_provider_and_gh_unavailable_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC2 (critical, ADR-092): with no provider registered for this issue and
    `gh` itself unavailable, the REAL (unstubbed) `extract_criteria_count_from_issue_body`
    must return None, and `run_check` must fail closed — never PASS, never SKIP,
    because the fact was unreachable. The seam must never become a way to make
    a gate green by withholding the fact."""
    cam = _cam()
    monkeypatch.delenv(cam.CRITERIA_COUNT_OVERRIDE_ENV, raising=False)
    monkeypatch.setattr(cam.subprocess, "run", _no_gh_available)

    # The seam itself, exercised directly and unstubbed.
    assert cam.extract_criteria_count_from_issue_body(1761) is None

    # And the gate that consumes it, end to end.
    monkeypatch.setattr(cam, "load_review_artifact", lambda issue: _review(1, 1))
    passed, message, details = cam.run_check(1761)

    assert passed is False
    assert any("cannot read the acceptance-criteria count" in p for p in details["problems"])
    assert "issue_criteria_count" not in details


def test_ac3_default_provider_is_the_real_gh_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC3: fails if the seam is removed, or its default stops being the real
    `gh` lookup. With no override registered, the seam must actually invoke
    `gh issue view <issue> ...` — not a canned answer, not a skip."""
    cam = _cam()
    monkeypatch.delenv(cam.CRITERIA_COUNT_OVERRIDE_ENV, raising=False)

    calls: list[list[str]] = []

    class _Result:
        returncode = 0
        stdout = "## Acceptance criteria\n1. one\n2. two\n"

    def _spy_run(cmd: list[str], **_kwargs: object) -> _Result:
        calls.append(cmd)
        return _Result()

    monkeypatch.setattr(cam.subprocess, "run", _spy_run)

    result = cam.extract_criteria_count_from_issue_body(1761)

    assert calls, "the default path must call subprocess.run at all"
    assert calls[0][:3] == ["gh", "issue", "view"]
    assert "1761" in calls[0]
    assert result == 2


def test_harness_override_bypasses_gh_for_the_matching_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The mutation harness's provider: an env-var override scoped to one
    synthetic issue, so the offline sweep can reach the record comparison
    without a live `gh` lookup. Registered via `criteria_count_override_env`,
    the same helper `eval/gate_scoring.py` calls."""
    cam = _cam()

    def _gh_must_not_be_called(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("gh must not be called when a matching override is registered")

    monkeypatch.setattr(cam.subprocess, "run", _gh_must_not_be_called)
    for key, value in cam.criteria_count_override_env(9_900_123, 4).items():
        monkeypatch.setenv(key, value)

    assert cam.extract_criteria_count_from_issue_body(9_900_123) == 4


def test_harness_override_ignored_for_a_different_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale override left over for one issue must never answer for another
    — the harness always scopes its provider to the exact synthetic issue."""
    cam = _cam()

    calls: list[list[str]] = []

    class _Result:
        returncode = 0
        stdout = "## Acceptance criteria\n1. one\n"

    def _spy_run(cmd: list[str], **_kwargs: object) -> _Result:
        calls.append(cmd)
        return _Result()

    monkeypatch.setattr(cam.subprocess, "run", _spy_run)
    for key, value in cam.criteria_count_override_env(9_900_123, 4).items():
        monkeypatch.setenv(key, value)

    result = cam.extract_criteria_count_from_issue_body(9_900_999)

    assert calls, "a mismatched override must fall through to the real gh lookup"
    assert result == 1


# ---------------------------------------------------------------------------
# #1879 — the parser is blind to the repo's canonical GIVEN/WHEN/THEN bullet
# format, and mislabels "found but unparseable" as "section missing".
# ---------------------------------------------------------------------------

# Real "Acceptance criteria" section bodies, verbatim from `gh issue view
# <n> --json body -q .body`, captured 2026-09-10. These are the exact shapes
# the parser must handle — not a synthetic stand-in for them.

_ISSUE_1460_BODY = """## What to build
Some prose paragraph that is not part of the section.

## Acceptance criteria
- GIVEN any judge invocation WHEN it runs THEN every canary for the invoked rubric is evaluated ...
  Observable at: the judge runner under `eval/`
  Verified by: tests/unit/test_judge.py::test_canary_pass_aborts_with_exit_2
- GIVEN a rubric set WHEN the canary directory is checked THEN every canary ID named in the rubr ...
  Verified by: tests/unit/test_judge.py::test_missing_canary_is_hard_error
- GIVEN an uncalibrated rubric WHEN the judge produces a verdict THEN the verdict is recorded as ...
  Verified by: tests/unit/test_judge.py::test_advisory_verdict_never_blocks
- GIVEN a corpus of merged records WHEN the judge runs as a sampler THEN it emits a stratified c ...
  Verified by: tests/unit/test_judge.py::test_sampler_emits_stratified_candidates
- GIVEN a rubric whose prompt, anchors or model changed WHEN it is loaded THEN its `rubric_hash` ...
  Verified by: tests/unit/test_judge.py::test_rubric_edit_resets_to_advisory

## Blocked by
Blocked by #1457
"""

_ISSUE_1461_BODY = """## Acceptance criteria
- GIVEN a week of merged records WHEN the sampler runs THEN it presents 10 records stratified 5/ ...
  Observable at: the labelling entrypoint under `eval/`
  Verified by: tests/unit/test_calibrate.py::test_stratification_is_enforced_and_shortfall_reported
- GIVEN ≥ 40 human labels under one `rubric_hash` WHEN calibration runs THEN it reports κ agains ...
  Verified by: tests/unit/test_calibrate.py::test_kappa_refuses_to_pool_across_rubric_hashes
- GIVEN a rubric meeting all four thresholds WHEN promotion is requested THEN it opens a PR chan ...
  Verified by: tests/unit/test_calibrate.py::test_promotion_emits_pr_not_runtime_change
- GIVEN a rubric failing any one of the four thresholds WHEN promotion is requested THEN it is r ...
  Verified by: tests/unit/test_calibrate.py::test_promotion_refused_names_failing_threshold

## Blocked by
Blocked by #1460
"""

_ISSUE_1436_BODY = """## Acceptance criteria
- GIVEN the fast-track lane instructions WHEN read after this change THEN they either no longer ...
  Observable at: `.cursor/rules/git-baseline.mdc`
  Verified by: tests/unit/test_wave_free_merge_docs.py::test_fast_track_lane_bypass_language_is_ ...
- GIVEN a merge performed with `--admin` after this change WHEN the PR is inspected THEN a recor ...
  Observable at: the PR
  Verified by: a linked example PR on this issue
- GIVEN the repository ruleset WHEN bypass privileges are reviewed THEN the bypass actor list is ...
  Observable at: GitHub → Settings → Rules → Ruleset "Protect main" → Bypass list
  Verified by: the decision and its reasoning recorded on this issue

## Blocked by
None - can start immediately
"""

_ISSUE_1761_BODY = """## Acceptance criteria

1. `check_acceptance_mapping` catches `unbacked_claim` again in the scored
   table, and `check_review_artifact` catches `self_reported_pass` again.
2. With no provider registered and `gh` unavailable, both still fail closed.
   Exhibit: the existing lookup-unavailable test stays green.
3. `caught` returns to at least 4 in `eval/results/gate_operator_scores.json`,
   regenerated by a real sweep, and the three-way partition still covers every
   row.
4. No gate is added to the fail-closed exclusion list by hand.

Refs #1732, #1664. Parent #1434.
"""

_ISSUE_1732_BODY = """## Acceptance criteria

1. An implementation artifact recording `{available: false, reason}` for
   `executionDurationMs` or `toolInvocationCount` validates and passes
   `check_implementation_artifact`. Exhibit: the same artifact with a bare `0`
   and no measurement is still accepted only if a measurement genuinely exists.
2. `harness_optimizer` reports an unmeasured run as unmeasured. Exhibit
   (ADR-092): given an artifact on the unavailable branch,
   `baselineMetrics.tokenUsageTotal` is not `0`.
3. `acceptance_criteria_mapped` reads the criteria count from the issue and fails
   when the artifact disagrees, naming both numbers. Exhibit: an artifact
   recording `total: 1` against a three-criterion issue fails.
4. A review artifact with `dynamicTestsExecuted: false` cannot carry a PASS.
   Exhibit: each of the four shapes in the table above fails.
5. Every `gateVersion: 2` record already committed keeps validating, with no
   `sha256` changed. No backfill, no history rewrite.

Closes #1534, #1537, #1539, #1664.
"""

_ISSUE_1865_BODY = """## Acceptance criteria

1. A successful live run leaves `git status --porcelain tests/fixtures/` empty.
2. Regeneration is explicitly invoked (a flag or its own entry point), not a side effect of runn ...
3. The three existing safety assertions (no vendor SKU id, no vendor product id, no `access_toke ...

Refs #1677. Parent #1434.
"""


@pytest.mark.parametrize(
    ("body", "expected_count"),
    [
        (_ISSUE_1460_BODY, 5),
        (_ISSUE_1461_BODY, 4),
        (_ISSUE_1436_BODY, 3),
    ],
)
def test_ac1_given_when_then_bullets_are_counted(
    monkeypatch: pytest.MonkeyPatch, body: str, expected_count: int
) -> None:
    """AC1: a GIVEN/WHEN/THEN bullet section parses to the bullet count —
    demonstrated against the real bodies of #1460 (5), #1461 (4) and #1436
    (3), the exact three the issue measured as reading `None`."""
    cam = _cam()
    monkeypatch.setattr(cam.subprocess, "run", _spy_run_returning(body))

    result = cam.extract_criteria_count_from_issue_body(1)

    assert result == expected_count


@pytest.mark.parametrize(
    ("body", "expected_count"),
    [
        (_ISSUE_1761_BODY, 4),
        (_ISSUE_1732_BODY, 5),
        (_ISSUE_1865_BODY, 3),
    ],
)
def test_ac2_numbered_lists_still_parse(
    monkeypatch: pytest.MonkeyPatch, body: str, expected_count: int
) -> None:
    """AC2: numbered criteria keep parsing unchanged — demonstrated against
    the real bodies of #1761 (4) and #1732 (5), plus #1865 (3)."""
    cam = _cam()
    monkeypatch.setattr(cam.subprocess, "run", _spy_run_returning(body))

    result = cam.extract_criteria_count_from_issue_body(1)

    assert result == expected_count


def test_continuation_lines_do_not_inflate_the_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """`Observable at:` / `Verified by:` continuation lines must never be
    counted as their own criterion — widening the parser to match any bullet
    would make the artifact-vs-issue comparison meaningless in the other
    direction (#1879 requirement 3). #1460's body has 5 bullets and 9
    continuation lines (5 `Verified by:` + 4 `Observable at:`); the count
    must be exactly 5, not 14."""
    cam = _cam()
    monkeypatch.setattr(cam.subprocess, "run", _spy_run_returning(_ISSUE_1460_BODY))

    result = cam.extract_criteria_count_from_issue_body(1)

    assert result == 5


def test_section_present_but_unparseable_names_that_distinctly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1879 requirement 2 / AC3: when the "Acceptance criteria" section is
    present but nothing under it matches either recognised shape, the gate's
    message must say so distinctly from "section missing" — not send the
    reader hunting for a heading that is right there."""
    cam = _cam()
    body = (
        "## Acceptance criteria\n"
        "The seller can reprice a listing and see the change reflected.\n"
        "\n"
        "## Blocked by\nNone\n"
    )
    monkeypatch.setattr(cam.subprocess, "run", _spy_run_returning(body))
    monkeypatch.setattr(cam, "load_review_artifact", lambda issue: _review(1, 1))

    assert cam.extract_criteria_count_from_issue_body(1) is None

    passed, message, details = cam.run_check(1)

    assert passed is False
    problem = next(p for p in details["problems"] if "cannot read" in p)
    assert "no criteria recognised" in problem
    assert "no 'Acceptance criteria' section found" not in problem


def test_section_missing_entirely_still_fails_closed_and_names_that(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1879 requirement 2 / AC4: with no "Acceptance criteria" heading at
    all, the gate still fails closed, and the message names the section as
    missing — the case this must stay distinct from is 'found but
    unparseable', proven by the assertion below. A test proving only that it
    fails, without checking *which* reason fired, could not tell this defect
    apart from its own fix."""
    cam = _cam()
    body = "## What to build\nNo acceptance section anywhere in this body.\n"
    monkeypatch.setattr(cam.subprocess, "run", _spy_run_returning(body))
    monkeypatch.setattr(cam, "load_review_artifact", lambda issue: _review(1, 1))

    assert cam.extract_criteria_count_from_issue_body(1) is None

    passed, message, details = cam.run_check(1)

    assert passed is False
    problem = next(p for p in details["problems"] if "cannot read" in p)
    assert "no 'Acceptance criteria' section found" in problem
    assert "no criteria recognised" not in problem
