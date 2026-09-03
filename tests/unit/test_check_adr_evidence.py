"""#1529: check_adr must not conclude "no architectural change" from a review
artifact it could not read.

Review artifact bodies under ``agent-runtime/artifacts/reviews/`` are gitignored
by policy (ADR-003: emit is not commit), so in any CI checkout
``load_review_artifact`` returns nothing. The gate wrote
``load_review_artifact(issue) or {}`` and then evaluated its two review-derived
limbs against that empty dict -- both structurally dead in CI -- and reported
PASS. Same commit, opposite verdict, decided by whether a gitignored file
happened to be on local disk, on a gate wired *blocking* in pr.yml.

Every test below plants that lie and asserts the gate now catches it: absence is
not evidence of absence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

# An issue number with no artifact body anywhere in the repo, so a bug in the
# redirection below surfaces as a failure rather than as a real file being read.
ISSUE = 152900

VALID_ADR = """# 900. Something architectural

**Status:** Accepted

## Context
Context.

## Decision
Decision.

## Rationale
Rationale.

## Consequences
Consequences.
"""


def _load_seam() -> tuple[Any, Any]:
    """Import the gate under test and the ``common`` module it reads through.

    Imported inside a function body rather than at module scope: both live
    outside any importable package and need a ``sys.path`` insert first, which
    at module scope would cost a ``# noqa: E402`` suppression unit that the
    repo's debt ratchet counts (``tests/unit/test_ratchets.py``). Same pattern
    as ``tests/unit/test_command_subsumption_provider.py::_load_seam``.
    """
    import importlib
    import sys

    root = Path(__file__).resolve().parents[2]
    for rel in ("agent-runtime/scripts/ci", "agent-runtime/scripts/validate"):
        entry = str(root / rel)
        if entry not in sys.path:
            sys.path.insert(0, entry)
    return importlib.import_module("check_adr"), importlib.import_module("common")


class _Harness:
    """Drives the real gate against a real (temporary) filesystem.

    The three inputs are redirected at directories, not stubbed behind fake
    loaders: ``load_review_artifact`` and the status-record read execute for
    real, so a change to how the gate reads its evidence is exercised here
    rather than mocked away. ``git_changed_files`` is the one substitution --
    a git diff cannot be conjured cheaply -- and it is bound to the real
    signature, never ``**kwargs``.
    """

    def __init__(self, check_adr: Any, common: Any, tmp_path: Path, monkeypatch: Any) -> None:
        self.check_adr = check_adr
        self.monkeypatch = monkeypatch
        self.reviews = tmp_path / "reviews"
        self.status = tmp_path / "status"
        self.repo = tmp_path / "repo"
        (self.repo / "docs" / "adr").mkdir(parents=True)
        self.reviews.mkdir()
        self.status.mkdir()
        monkeypatch.setattr(common, "REVIEWS_DIR", self.reviews)
        monkeypatch.setattr(check_adr, "STATUS_DIR", self.status, raising=False)
        monkeypatch.setattr(check_adr, "REPO_ROOT", self.repo)
        self.changed("backend/src/juli_backend/services/scoring/engine.py")

    def changed(self, *files: str) -> None:
        def _git_changed_files(base_ref: str | None = None) -> list[str]:
            return list(files)

        self.monkeypatch.setattr(self.check_adr, "git_changed_files", _git_changed_files)

    def write_review(self, **overrides: Any) -> None:
        payload: dict[str, Any] = {
            "issue": ISSUE,
            "status": "PASS",
            "criticalFindings": [],
            "interfaceChanges": [],
        }
        payload.update(overrides)
        (self.reviews / f"review-issue-{ISSUE}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def write_status(self, **metrics: Any) -> None:
        payload = {
            "issue": ISSUE,
            "gateVersion": 2,
            "review": {"status": "PASS", "sha256": "0" * 64},
            "metrics": {"criticalFindings": 0, "modulesTouched": [], **metrics},
        }
        (self.status / f"issue-{ISSUE}.json").write_text(json.dumps(payload), encoding="utf-8")

    def write_adr(self, name: str = "900-something-architectural.md") -> str:
        (self.repo / "docs" / "adr" / name).write_text(VALID_ADR, encoding="utf-8")
        return f"docs/adr/{name}"

    def run(self) -> tuple[bool, str, dict[str, Any]]:
        return self.check_adr.run_check(ISSUE)


@pytest.fixture()
def gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Harness:
    check_adr, common = _load_seam()
    return _Harness(check_adr, common, tmp_path, monkeypatch)


def test_absent_review_artifact_fails_closed(gate: _Harness) -> None:
    """The defect itself: no review body on disk -- CI's permanent condition.

    Nothing about this diff says "no architectural change"; the gate simply
    could not read the only input that would have told it. It must not spend
    that silence as a PASS.
    """
    passed, description, details = gate.run()

    assert passed is False, f"gate passed on unreadable review evidence: {description}"
    assert details["evidenceSource"] == "unresolved"
    assert details["architecturalChange"] is None
    assert "No architectural change detected" not in description


def test_present_and_clean_review_passes(gate: _Harness) -> None:
    """The distinction the gate has to make: the artifact is here, and it says
    no interface changed. That is a real answer, and it is PASS."""
    gate.write_review()

    passed, description, details = gate.run()

    assert passed is True, description
    assert details["evidenceSource"] == "review-artifact"
    assert details["architecturalChange"] is False


def test_present_review_requiring_an_adr_fails(gate: _Harness) -> None:
    """A breaking interface change with no ADR in the diff -- still FAIL, and
    for the ADR reason, not the unresolved-evidence reason."""
    gate.write_review(interfaceChanges=[{"symbol": "score_shop", "breaking": True}])

    passed, description, details = gate.run()

    assert passed is False
    assert details["evidenceSource"] == "review-artifact"
    assert details["architecturalChange"] is True
    assert "ADR" in description


def test_present_review_requiring_an_adr_passes_when_the_adr_is_there(gate: _Harness) -> None:
    gate.write_review(criticalFindings=[{"type": "interface_change", "severity": "WARNING"}])
    gate.changed("backend/src/juli_backend/services/scoring/engine.py", gate.write_adr())

    passed, description, details = gate.run()

    assert passed is True, description
    assert details["architecturalChange"] is True
    assert details["adrPresent"] is True


def test_map_md_change_is_conclusive_without_any_review(gate: _Harness) -> None:
    """The one limb CI could always see must keep its teeth: a map.md edit is
    an architectural change on the diff's own evidence, so it never reaches the
    unresolved path."""
    gate.changed("docs/architecture/map.md")

    passed, description, details = gate.run()

    assert passed is False
    assert details["evidenceSource"] == "diff"
    assert details["architecturalChange"] is True
    assert "ADR" in description


def test_status_record_critical_findings_escalate_without_a_body(gate: _Harness) -> None:
    """agent-runtime/artifacts/status/ is the one artifact directory that is not
    gitignored, so it is the only review-derived evidence CI can see. A non-zero
    critical finding count is a real positive signal. The record has no typed
    findings, so the count cannot be narrowed to an interface change and the
    gate resolves it the only safe way, upward."""
    gate.write_status(criticalFindings=1)

    passed, _, details = gate.run()

    assert passed is False
    assert details["evidenceSource"] == "status-record"
    assert details["architecturalChange"] is True


def test_status_record_answers_in_the_negative_but_declares_its_blind_spot(
    gate: _Harness,
) -> None:
    """The gate must not become a false positive on ordinary diffs (issue #1529
    AC3), so a clean record is a real "no" -- but it is a narrower "no" than the
    review body's, and the gate says so out loud.

    `criticalFindings == 0` rules out the
    `criticalFindings[].type == "interface_change"` limb. It cannot rule out
    `interfaceChanges[].breaking`: the record does not carry that array, and
    `derive_review_status` forces neither a critical finding nor a non-PASS
    status for a breaking entry. Closing that needs an `architecturalChange`
    boolean on the record itself. Until then the gap is reported in the verdict's
    own details rather than left to a comment nobody reads.
    """
    gate.write_status(criticalFindings=0)

    passed, description, details = gate.run()

    assert passed is True, description
    assert details["evidenceSource"] == "status-record"
    assert details["architecturalChange"] is False
    assert any("interfaceChanges" in note for note in details["evidenceLimitations"])


def test_the_review_body_reports_no_blind_spot(gate: _Harness) -> None:
    """The declaration has to discriminate, or it is decoration: the full-fidelity
    source sees both limbs and must claim no gap."""
    gate.write_review()

    passed, _, details = gate.run()

    assert passed is True
    assert details["evidenceLimitations"] == []


def test_unresolved_evidence_is_satisfied_by_a_valid_adr(gate: _Harness) -> None:
    """Fail-closed, not fail-always. When the diff carries a well-formed ADR the
    requirement is met whichever way the unreadable review would have gone, so
    there is nothing left to be uncertain about."""
    gate.changed("backend/src/juli_backend/services/scoring/engine.py", gate.write_adr())

    passed, description, details = gate.run()

    assert passed is True, description
    assert details["evidenceSource"] == "unresolved"
    assert details["adrPresent"] is True


def test_unresolved_evidence_still_rejects_a_malformed_adr(gate: _Harness) -> None:
    """An ADR-shaped file is not an ADR. The escape hatch above must not become
    a way to buy a PASS with an empty file."""
    (gate.repo / "docs" / "adr" / "901-hollow.md").write_text("# 901\n", encoding="utf-8")
    gate.changed("docs/adr/901-hollow.md")

    passed, description, details = gate.run()

    assert passed is False
    assert details["adrProblems"]["901-hollow.md"], description
