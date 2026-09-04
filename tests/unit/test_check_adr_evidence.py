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

#: "the caller said nothing", distinguishable from "the caller said None".
_OMIT = object()

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

    def write_status(self, architectural: Any = _OMIT, **metrics: Any) -> None:
        """Write a committed-shaped status record.

        ``architectural`` defaults to ``_OMIT`` rather than to a valid block on
        purpose: the default is the shape of the ~317 records already on
        ``main``, which carry no such field and are never backfilled. A test
        that wants the field has to ask for it.
        """
        payload: dict[str, Any] = {
            "issue": ISSUE,
            "gateVersion": 2,
            "review": {"status": "PASS", "sha256": "0" * 64},
            "metrics": {"criticalFindings": 0, "modulesTouched": [], **metrics},
        }
        if architectural is not _OMIT:
            payload["architecturalChange"] = architectural
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


# --- #1562: rung 3 reads a typed signal, never a finding count -------------
#
# #1529 shipped rung 3 as ``metrics.criticalFindings > 0``. That is a count of
# findings of every type and every severity used as a proxy for "an interface
# moved". Measured on the committed corpus it fires on 109 of the 316 records
# with a guard-admitted review status -- a blocking gate demanding an ADR on a
# third of ordinary PRs. The two tests it replaces are rewritten rather than
# deleted, because each asserted a behaviour this issue reverses:
#
#   test_status_record_critical_findings_escalate_without_a_body asserted the
#   over-trigger *as a requirement* (cf==1 -> architectural). It becomes
#   test_ordinary_change_still_passes_from_the_status_record, which plants the
#   same input and asserts the opposite -- so the old signal cannot come back
#   without turning this file red.
#
#   test_status_record_answers_in_the_negative_but_declares_its_blind_spot
#   asserted that the gate names ``interfaceChanges`` as uncarried. The record
#   now carries it, so continuing to assert the declaration would require the
#   gate to keep announcing a gap it no longer has. It becomes
#   test_the_status_record_blind_spot_is_closed (this issue's AC2), which keeps
#   the "a clean record is a real no" half unchanged.


def test_status_record_reports_a_breaking_interface_change(gate: _Harness) -> None:
    """#1562 AC1, the under-trigger. A ``breaking: true`` interface entry that
    produced no critical finding was invisible to rung 3, because the only thing
    the record carried was a finding count. The typed signal makes it visible
    with no review body anywhere on disk -- CI's permanent condition."""
    gate.write_status(
        architectural={"value": True, "signals": ["breaking-interface-change"]},
        criticalFindings=0,
    )

    passed, description, details = gate.run()

    assert passed is False, description
    assert details["evidenceSource"] == "status-record"
    assert details["architecturalChange"] is True
    assert "ADR" in description


def test_the_status_record_blind_spot_is_closed(gate: _Harness) -> None:
    """#1562 AC2. A clean record is still a real "no" (that half is unchanged
    from the test this replaces), but the gate must stop declaring
    ``interfaceChanges`` uncarried -- it is carried now, and a limitation notice
    that outlives its limitation is worse than none: it trains readers to
    discount the whole list."""
    gate.write_status(architectural={"value": False, "signals": []})

    passed, description, details = gate.run()

    assert passed is True, description
    assert details["evidenceSource"] == "status-record"
    assert details["architecturalChange"] is False
    assert not any("interfaceChanges" in note for note in details["evidenceLimitations"])


def test_ordinary_change_still_passes_from_the_status_record(gate: _Harness) -> None:
    """#1562 AC4, and the anti-proxy test. Three critical findings, none of them
    an interface change -- the ordinary shape of 109 committed records. The gate
    must read the typed answer and pass. A boolean re-derived as
    ``criticalFindings > 0`` would satisfy the schema and fail here, which is the
    whole point of asserting it with a non-zero count present."""
    gate.write_status(
        architectural={"value": False, "signals": []},
        criticalFindings=3,
    )

    passed, description, details = gate.run()

    assert passed is True, description
    assert details["evidenceSource"] == "status-record"
    assert details["architecturalChange"] is False


def test_a_record_without_the_signal_is_unresolved_not_false(gate: _Harness) -> None:
    """No backfill: every record already on ``main`` lacks the field. Absence
    must mean "this source cannot answer", not "no" -- reading silence as a
    negative is the exact defect #1529 was filed for, and re-committing it one
    field to the left would not be a fix."""
    gate.write_status(criticalFindings=7)

    passed, _, details = gate.run()

    assert passed is False
    assert details["evidenceSource"] == "unresolved"
    assert details["architecturalChange"] is None


@pytest.mark.parametrize(
    ("block", "why"),
    [
        ({"value": True, "signals": []}, "claims a change but names no limb that fired"),
        ({"value": False, "signals": ["breaking-interface-change"]}, "names a limb, denies it"),
        ({"value": "yes", "signals": []}, "value is not a boolean"),
        ({"value": True, "signals": "breaking-interface-change"}, "signals is not a list"),
        ({"signals": []}, "no value at all"),
        ("true", "block is not an object"),
    ],
)
def test_an_internally_inconsistent_signal_is_unresolved(
    gate: _Harness, block: Any, why: str
) -> None:
    """The invariant is what makes the field harder to fake than the count it
    replaces: ``value`` is true exactly when ``signals`` names a limb that fired.
    A record that breaks it was not written by the generator, so the gate refuses
    to read it in either direction rather than trusting half of it."""
    gate.write_status(architectural=block)

    passed, _, details = gate.run()

    assert passed is False, why
    assert details["evidenceSource"] == "unresolved", why
    assert details["architecturalChange"] is None, why


def test_the_committed_corpus_is_never_failed_for_requiring_an_adr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The criterion that separates a real fix from a re-typed version of the
    same bug (#1562, added AC).

    Runs the real gate against every record committed under
    ``agent-runtime/artifacts/status/`` that carries ``criticalFindings > 0``
    with a guard-admitted ``review.status`` -- the 109 the count-based rung 3
    would fail -- in the CI condition: no review body on disk, an ordinary diff,
    no ADR. None of them may be failed *for requiring an ADR*.

    Note what this does and does not claim. These records predate the field and
    are never backfilled, so they resolve UNRESOLVED and the gate still fails
    closed on them; that is #1529's shipped posture for a record that cannot
    answer, and it is honest. What must not happen is the gate asserting an
    architectural change that the record never evidenced.
    """
    check_adr, common = _load_seam()
    repo = tmp_path / "repo"
    (repo / "docs" / "adr").mkdir(parents=True)
    monkeypatch.setattr(common, "REVIEWS_DIR", tmp_path / "no-reviews")
    monkeypatch.setattr(check_adr, "REPO_ROOT", repo)
    monkeypatch.setattr(
        check_adr,
        "git_changed_files",
        lambda base_ref=None: ["backend/src/juli_backend/services/scoring/engine.py"],
    )

    status_dir = Path(__file__).resolve().parents[2] / "agent-runtime" / "artifacts" / "status"
    monkeypatch.setattr(check_adr, "STATUS_DIR", status_dir, raising=False)

    subjects: list[int] = []
    for path in sorted(status_dir.glob("issue-*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        review = record.get("review") or {}
        metrics = record.get("metrics") or {}
        if (
            review.get("status") in {"PASS", "PASS_WITH_WARNINGS"}
            and (metrics.get("criticalFindings") or 0) > 0
        ):
            subjects.append(record["issue"])

    assert len(subjects) >= 100, (
        f"expected the ~109-record cf>0 cohort, found {len(subjects)} — the corpus "
        "moved, so this measurement no longer says what it claims"
    )

    demanded_an_adr = [
        issue
        for issue in subjects
        if check_adr.run_check(issue)[1] == "Architectural change requires new ADR in docs/adr/"
    ]
    asserted_a_change = [
        issue for issue in subjects if check_adr.run_check(issue)[2]["architecturalChange"] is True
    ]

    assert demanded_an_adr == [], (
        f"{len(demanded_an_adr)} of {len(subjects)} committed records were failed for "
        f"requiring an ADR: {demanded_an_adr[:10]}"
    )
    assert asserted_a_change == [], (
        f"{len(asserted_a_change)} of {len(subjects)} committed records were read as "
        f"architectural changes on evidence they do not carry: {asserted_a_change[:10]}"
    )


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


def test_the_gate_prints_the_evidence_it_advertises(
    gate: _Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    """#1562, folded in from #1560's review. ``main`` did
    ``passed, description, _ = run_check(issue)`` and handed
    ``"" if passed else description`` to ``print_check_result``, so the PASS path
    printed a bare ``adr_requirement: PASS``.

    ``evidenceSource`` and ``evidenceLimitations`` -- which this module's
    docstring says ride in the gate's own details "where a reader can see it" --
    were therefore reachable only from unit tests and never appeared in CI, the
    one place the gate blocks. AC2 asks what the gate *declares*; a declaration
    that reaches no reader is not one.

    Asserted on the PASS path specifically, because that is the path that
    printed nothing at all.
    """
    gate.write_status(architectural={"value": False, "signals": []}, criticalFindings=4)
    gate.monkeypatch.setattr(
        gate.check_adr, "resolve_issue_number", lambda raw=None: ISSUE, raising=True
    )
    gate.monkeypatch.setattr(gate.check_adr, "parse_args", lambda desc: _Args(), raising=True)

    exit_code = gate.check_adr.main()
    out = capsys.readouterr().out

    assert exit_code == 0, out
    assert "adr_requirement: PASS" in out
    assert "evidenceSource=status-record" in out, f"the gate printed no provenance: {out!r}"
    assert "architecturalChange=False" in out
    assert "limitations:" in out, f"the gate declared no limitation: {out!r}"


class _Args:
    """Stand-in for ``parse_args``'s namespace, bound to the one attribute
    ``main`` reads -- not a ``MagicMock`` that would accept any attribute and
    prove nothing about the real call."""

    issue: str | None = None


def test_the_unresolved_reason_says_which_silence_it_hit(gate: _Harness) -> None:
    """#1529 wrote one unresolved message asserting "no status record exists".
    That was true when a record could always answer. Now a record can be present
    and silent — every record on ``main`` predates the field and none is
    backfilled — so the message must not send a reader looking for a file that is
    already there. Both directions asserted; either alone would also be satisfied
    by a message that never varies."""
    passed, absent, _ = gate.run()
    assert passed is False
    assert "no status record exists" in absent

    gate.write_status(criticalFindings=9)
    passed, present, details = gate.run()

    assert passed is False
    assert details["architecturalChange"] is None
    assert "carries no architecturalChange signal" in present
    assert "no status record exists" not in present, (
        f"the record is on disk; the gate said it was not: {present!r}"
    )
