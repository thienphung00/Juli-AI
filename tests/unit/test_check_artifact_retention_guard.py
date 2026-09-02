"""Unit tests for the issue-tier artifact retention guard (#1064).

Design correction (issue #1064 comment "Design correction before implementation"):
CI cannot upload implementation artifacts because they are gitignored and never reach
the pushed branch. What CI *can* see is the committed compact status record at
``agent-runtime/artifacts/status/issue-<N>.json`` (ADR-052's #670 amendment). This guard
fails an issue-tier PR when that record is absent or not PASS, and it must never pass
because it could not determine an answer -- every unreadable/malformed/schema-invalid
path is a FAIL, never a silent pass.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

from check_artifact_retention_guard import (  # noqa: E402
    GENERATE_COMMAND,
    evaluate,
    parse_issue_number,
    status_record_path,
)


def _write_record(
    status_dir: Path,
    issue: int,
    *,
    payload: dict | None = None,
    raw_text: str | None = None,
    review_status: str = "PASS",
    validation_status: str = "PASS",
    record_issue: int | None = None,
    warnings_acknowledged: bool | None = None,
    owner_signoff_present: bool | None = None,
) -> Path:
    status_dir.mkdir(parents=True, exist_ok=True)
    path = status_dir / f"issue-{issue}.json"
    if raw_text is not None:
        path.write_text(raw_text, encoding="utf-8")
        return path
    if payload is None:
        payload = {
            "issue": record_issue if record_issue is not None else issue,
            "wave": None,
            "review": {
                "status": review_status,
                "artifactRef": (
                    f"git-history:agent-runtime/artifacts/reviews/review-issue-{issue}.json"
                ),
                "sha256": "a" * 64,
            },
            "validation": {
                "status": validation_status,
                "artifactRef": (
                    f"git-history:agent-runtime/artifacts/validation/validation-issue-{issue}.json"
                ),
                "sha256": "b" * 64,
            },
            "gateVersion": 1,
        }
        if warnings_acknowledged is not None:
            payload["review"]["warningsAcknowledged"] = warnings_acknowledged
        if owner_signoff_present is not None:
            payload["review"]["ownerSignoffPresent"] = owner_signoff_present
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --- parse_issue_number: the SKIP signal for docs/hotfix/non-issue branches ---


@pytest.mark.parametrize(
    "raw",
    [None, "", "   ", "abc", "0", "-1", "12.5"],
)
def test_parse_issue_number_returns_none_for_non_issue_input(raw) -> None:
    assert parse_issue_number(raw) is None


def test_parse_issue_number_parses_a_real_issue_number() -> None:
    assert parse_issue_number("1064") == 1064
    assert parse_issue_number(" 1064 ") == 1064


# --- Revised acceptance criteria ---


def test_fails_with_missing_path_and_producing_command_when_record_absent(
    tmp_path: Path,
) -> None:
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False
    assert str(status_record_path(1064, tmp_path)) in detail
    assert GENERATE_COMMAND in detail


def test_passes_once_a_pass_record_is_committed(tmp_path: Path) -> None:
    _write_record(tmp_path, 1064, review_status="PASS", validation_status="PASS")
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is True
    assert "PASS" in detail


def test_fails_and_names_the_gate_when_review_not_pass(tmp_path: Path) -> None:
    _write_record(tmp_path, 1064, review_status="FAIL", validation_status="PASS")
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False
    assert "review" in detail.lower()
    assert "FAIL" in detail


def test_fails_and_names_the_gate_when_validation_not_pass(tmp_path: Path) -> None:
    _write_record(tmp_path, 1064, review_status="PASS", validation_status="FAIL")
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False
    assert "validation" in detail.lower()
    assert "FAIL" in detail


# --- #1141: PASS_WITH_WARNINGS is landable, but only fully signed off ---


def test_pass_with_warnings_passes_when_both_signoffs_are_recorded(tmp_path: Path) -> None:
    """ADR-003's shippable warning state must be reachable, or `validate` can
    emit a status no PR can ever land (#1141)."""
    _write_record(
        tmp_path,
        1064,
        review_status="PASS_WITH_WARNINGS",
        validation_status="PASS",
        warnings_acknowledged=True,
        owner_signoff_present=True,
    )
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is True
    assert "PASS_WITH_WARNINGS" in detail


def test_pass_with_warnings_fails_without_owner_signoff(tmp_path: Path) -> None:
    _write_record(
        tmp_path,
        1064,
        review_status="PASS_WITH_WARNINGS",
        validation_status="PASS",
        warnings_acknowledged=True,
        owner_signoff_present=False,
    )
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False
    assert "ownerSignoffPresent" in detail


def test_pass_with_warnings_fails_without_per_finding_acknowledgement(tmp_path: Path) -> None:
    _write_record(
        tmp_path,
        1064,
        review_status="PASS_WITH_WARNINGS",
        validation_status="PASS",
        warnings_acknowledged=False,
        owner_signoff_present=True,
    )
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False
    assert "warningsAcknowledged" in detail


def test_pass_with_warnings_fails_on_a_pre_1141_record_with_neither_key(tmp_path: Path) -> None:
    """A record written before #1141 carries no signoff booleans at all. Absent
    must read as False — the guard never infers signoff it cannot see."""
    _write_record(tmp_path, 1064, review_status="PASS_WITH_WARNINGS", validation_status="PASS")
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False
    assert "warningsAcknowledged" in detail


@pytest.mark.parametrize("truthy", ["true", 1, "yes", [1], {"a": 1}])
def test_pass_with_warnings_requires_literal_true_not_merely_truthy(tmp_path: Path, truthy) -> None:
    """`is not True` rather than a falsy check: a string or a non-empty list must
    not buy a signoff."""
    _write_record(
        tmp_path,
        1064,
        payload={
            "issue": 1064,
            "wave": None,
            "review": {
                "status": "PASS_WITH_WARNINGS",
                "artifactRef": "git-history:x",
                "sha256": "a" * 64,
                "warningsAcknowledged": truthy,
                "ownerSignoffPresent": truthy,
            },
            "validation": {
                "status": "PASS",
                "artifactRef": "git-history:y",
                "sha256": "b" * 64,
            },
            "gateVersion": 1,
        },
    )
    passed, _ = evaluate(1064, status_dir=tmp_path)
    assert passed is False


def test_a_genuinely_failing_review_is_still_rejected_outright(tmp_path: Path) -> None:
    """The #1141 widening admits exactly one new status, not any status that
    happens to carry the booleans."""
    _write_record(
        tmp_path,
        1064,
        review_status="FAIL",
        validation_status="PASS",
        warnings_acknowledged=True,
        owner_signoff_present=True,
    )
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False
    assert "review" in detail.lower()


# --- Fail-closed: never pass because it could not determine an answer ---


def test_fails_when_json_is_malformed(tmp_path: Path) -> None:
    _write_record(tmp_path, 1064, raw_text="{not valid json")
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False
    assert "not valid JSON" in detail


def test_fails_when_record_is_not_a_json_object(tmp_path: Path) -> None:
    _write_record(tmp_path, 1064, raw_text="[1, 2, 3]")
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False


def test_fails_when_schema_is_violated(tmp_path: Path) -> None:
    # Missing required "gateVersion" and malformed sha256 -> schema-invalid.
    _write_record(
        tmp_path,
        1064,
        payload={
            "issue": 1064,
            "review": {"status": "PASS", "artifactRef": "x", "sha256": "not-a-sha"},
            "validation": {"status": "PASS", "artifactRef": "x", "sha256": "b" * 64},
        },
    )
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False
    assert "schema" in detail.lower()


def test_fails_when_review_or_validation_object_missing(tmp_path: Path) -> None:
    _write_record(
        tmp_path,
        1064,
        payload={
            "issue": 1064,
            "review": {"status": "PASS", "artifactRef": "x", "sha256": "a" * 64},
            "gateVersion": 1,
        },
    )
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False


def test_fails_when_status_record_issue_field_mismatches(tmp_path: Path) -> None:
    _write_record(tmp_path, 1064, record_issue=999)
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False
    assert "999" in detail


def test_fails_when_record_is_unreadable(tmp_path: Path, monkeypatch) -> None:
    record_path = _write_record(tmp_path, 1064)
    original_read_bytes = Path.read_bytes

    def _raise(self: Path):
        if self == record_path:
            raise OSError("permission denied (simulated)")
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _raise)
    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is False
    assert "could not read" in detail


@pytest.mark.parametrize(
    "setup",
    [
        "missing",
        "malformed_json",
        "not_an_object",
        "missing_gate_version",
        "review_not_pass",
        "validation_not_pass",
        "issue_mismatch",
    ],
)
def test_fail_closed_never_passes_when_it_cannot_determine_an_answer(
    tmp_path: Path, setup: str
) -> None:
    """The one property this whole guard exists to guarantee: no code path
    returns passed=True without having read a genuine PASS/PASS record for
    the right issue. Every ambiguous or broken input must FAIL, not pass."""
    issue = 1064
    if setup == "missing":
        pass  # no file written at all
    elif setup == "malformed_json":
        _write_record(tmp_path, issue, raw_text="{{{not json")
    elif setup == "not_an_object":
        _write_record(tmp_path, issue, raw_text="null")
    elif setup == "missing_gate_version":
        _write_record(
            tmp_path,
            issue,
            payload={
                "issue": issue,
                "review": {"status": "PASS", "artifactRef": "x", "sha256": "a" * 64},
                "validation": {
                    "status": "PASS",
                    "artifactRef": "x",
                    "sha256": "b" * 64,
                },
            },
        )
    elif setup == "review_not_pass":
        _write_record(tmp_path, issue, review_status="FAIL")
    elif setup == "validation_not_pass":
        _write_record(tmp_path, issue, validation_status="FAIL")
    elif setup == "issue_mismatch":
        _write_record(tmp_path, issue, record_issue=1)

    passed, detail = evaluate(issue, status_dir=tmp_path)
    assert passed is False
    assert detail  # a reason is always given -- no silent skip/fail


# --- #1438: the guard reads gateVersion 1 AND gateVersion 2 records ---------
# Architect lock: no backfill. The ~290 committed records stay at gateVersion 1
# and must keep passing unchanged, while records written after #1438 carry
# gateVersion 2 plus a run{} envelope of harness-captured evidence.


def test_gateversion_1_record_still_passes(tmp_path: Path) -> None:
    """An untouched pre-#1438 record — no run{}, gateVersion 1 — still validates
    and still passes the guard."""
    _write_record(tmp_path, 1064)
    payload = json.loads((tmp_path / "issue-1064.json").read_text(encoding="utf-8"))
    assert payload["gateVersion"] == 1
    assert "run" not in payload

    passed, detail = evaluate(1064, status_dir=tmp_path)
    assert passed is True, detail


def test_gateversion_1_record_from_the_real_status_dir_still_passes() -> None:
    """Not a fixture: read the actual committed records and assert the guard
    still accepts the v1 shape it has been reading all along."""
    real_status_dir = REPO_ROOT / "agent-runtime" / "artifacts" / "status"
    candidates = []
    for path in sorted(real_status_dir.glob("issue-*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            record.get("gateVersion") == 1
            and record.get("review", {}).get("status") in {"PASS", "PASS_WITH_WARNINGS"}
            and record.get("validation", {}).get("status") == "PASS"
        ):
            candidates.append((path, record))
    if not candidates:
        pytest.skip("no committed gateVersion 1 PASS record available in this checkout")

    for path, record in candidates[:25]:
        passed, detail = evaluate(int(record["issue"]), status_dir=real_status_dir)
        assert passed is True, f"{path.name} no longer passes the guard: {detail}"


def test_gateversion_2_record_with_run_block_passes(tmp_path: Path) -> None:
    """The post-#1438 shape: gateVersion 2 plus a run{} envelope whose blocks
    the schema deliberately leaves open so a new provider needs no schema edit.

    #1445: a gateVersion 2 record must also carry artifactRefs that actually
    resolve, so this fixture commits the two verbose bodies and records their
    true digests. The assertion under test is unchanged -- an unknown run{}
    block is still accepted without a schema edit."""
    issue = 1438
    repo, digests = _make_repo_with_committed_artifacts(tmp_path, issue)
    status_dir = tmp_path / "status"
    _write_record(
        status_dir,
        issue,
        payload={
            "issue": issue,
            "wave": None,
            "review": {
                "status": "PASS",
                "artifactRef": (
                    f"git-history:agent-runtime/artifacts/reviews/review-issue-{issue}.json"
                ),
                "sha256": digests["review"],
            },
            "validation": {
                "status": "PASS",
                "artifactRef": (
                    f"git-history:agent-runtime/artifacts/validation/validation-issue-{issue}.json"
                ),
                "sha256": digests["validation"],
            },
            "run": {
                "artifactBytes": {"reviewBytes": 512, "validationBytes": 256},
                "someFutureWave2Block": {"anything": ["at", "all"]},
            },
            "gateVersion": 2,
        },
    )
    passed, detail = evaluate(issue, status_dir=status_dir, repo_root=repo)
    assert passed is True, detail


def test_unknown_gate_version_fails_closed(tmp_path: Path) -> None:
    """gateVersion is the read-path contract marker. A version this guard was
    never written against must fail, not be read on a guess."""
    _write_record(
        tmp_path,
        1438,
        payload={
            "issue": 1438,
            "review": {"status": "PASS", "artifactRef": "x", "sha256": "a" * 64},
            "validation": {"status": "PASS", "artifactRef": "y", "sha256": "b" * 64},
            "gateVersion": 99,
        },
    )
    passed, detail = evaluate(1438, status_dir=tmp_path)
    assert passed is False
    assert "schema" in detail.lower()


# --- #1445: an artifactRef that does not resolve fails the record ------------
# 240 of 538 artifactRef/sha256 pairs in the committed corpus name a path that
# exists in no commit on any branch -- #670 shipped the sha256 integrity chain
# but never built the store it points into. From gateVersion 2 forward a ref
# that does not resolve, or resolves to content that does not match its
# recorded sha256, fails the record. gateVersion 1 records are MARKED
# unresolvable and still pass: those files exist on no machine and the
# Architect lock forbids rewriting history to invent them.


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _make_repo_with_committed_artifacts(root: Path, issue: int) -> tuple[Path, dict[str, str]]:
    """A real git repo whose history contains the two verbose artifact bodies.

    Returns the repo root and the true sha256 of each committed body, so a test
    can plant either the truth or a lie in the status record and see which one
    the guard catches.
    """
    repo = root / "repo"
    (repo / "agent-runtime" / "artifacts" / "reviews").mkdir(parents=True)
    (repo / "agent-runtime" / "artifacts" / "validation").mkdir(parents=True)
    bodies = {
        "review": (
            f"agent-runtime/artifacts/reviews/review-issue-{issue}.json",
            b'{"id": "review-issue-%d", "status": "PASS"}' % issue,
        ),
        "validation": (
            f"agent-runtime/artifacts/validation/validation-issue-{issue}.json",
            b'{"id": "validation-issue-%d", "status": "PASS"}' % issue,
        ),
    }
    digests: dict[str, str] = {}
    for field, (rel, content) in bodies.items():
        (repo / rel).write_bytes(content)
        digests[field] = hashlib.sha256(content).hexdigest()

    _git(repo.parent, "init", "--initial-branch=main", str(repo))
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--no-verify", "-m", "commit the verbose bodies")
    return repo, digests


def _v2_payload(issue: int, review_ref: str, review_sha: str, val_ref: str, val_sha: str) -> dict:
    return {
        "issue": issue,
        "wave": None,
        "review": {"status": "PASS", "artifactRef": review_ref, "sha256": review_sha},
        "validation": {"status": "PASS", "artifactRef": val_ref, "sha256": val_sha},
        "run": {"artifactBytes": {"reviewBytes": 512, "validationBytes": 256}},
        "gateVersion": 2,
    }


def test_v2_resolving_ref_with_matching_hash_passes(tmp_path: Path) -> None:
    """The honest case: both refs name a path that really is in history and the
    recorded sha256 really is the digest of that content."""
    issue = 1445
    repo, digests = _make_repo_with_committed_artifacts(tmp_path, issue)
    status_dir = tmp_path / "status"
    _write_record(
        status_dir,
        issue,
        payload=_v2_payload(
            issue,
            f"git-history:agent-runtime/artifacts/reviews/review-issue-{issue}.json",
            digests["review"],
            f"git-history:agent-runtime/artifacts/validation/validation-issue-{issue}.json",
            digests["validation"],
        ),
    )
    passed, detail = evaluate(issue, status_dir=status_dir, repo_root=repo)
    assert passed is True, detail
    assert "resolve" in detail.lower()
    assert "match" in detail.lower()

    # Non-vacuous: the pass is earned by the hashes, not by the guard ignoring them.
    lying = json.loads((status_dir / f"issue-{issue}.json").read_text(encoding="utf-8"))
    lying["review"]["sha256"] = "0" * 64
    lying_dir = tmp_path / "status-lying"
    _write_record(lying_dir, issue, payload=lying)
    lying_passed, lying_detail = evaluate(issue, status_dir=lying_dir, repo_root=repo)
    assert lying_passed is False, lying_detail


def test_v2_unresolvable_ref_fails(tmp_path: Path) -> None:
    """The lie: a gateVersion 2 record claims a sha256 for a path that exists in
    no commit on any branch -- exactly the 240 dangling pairs #670 left behind."""
    issue = 1445
    repo, digests = _make_repo_with_committed_artifacts(tmp_path, issue)
    status_dir = tmp_path / "status"
    dangling = "git-history:agent-runtime/artifacts/validation/validation-issue-999999.json"
    _write_record(
        status_dir,
        issue,
        payload=_v2_payload(
            issue,
            f"git-history:agent-runtime/artifacts/reviews/review-issue-{issue}.json",
            digests["review"],
            dangling,
            "c" * 64,
        ),
    )
    passed, detail = evaluate(issue, status_dir=status_dir, repo_root=repo)
    assert passed is False, detail
    assert "validation-issue-999999.json" in detail
    assert "no commit" in detail.lower()


def test_v2_hash_mismatch_fails(tmp_path: Path) -> None:
    """The other lie: the ref resolves, but the recorded sha256 is not the digest
    of the content it resolves to -- an integrity claim that is simply false."""
    issue = 1445
    repo, digests = _make_repo_with_committed_artifacts(tmp_path, issue)
    status_dir = tmp_path / "status"
    _write_record(
        status_dir,
        issue,
        payload=_v2_payload(
            issue,
            f"git-history:agent-runtime/artifacts/reviews/review-issue-{issue}.json",
            "d" * 64,  # the lie: not the digest of the committed body
            f"git-history:agent-runtime/artifacts/validation/validation-issue-{issue}.json",
            digests["validation"],
        ),
    )
    assert digests["review"] != "d" * 64
    passed, detail = evaluate(issue, status_dir=status_dir, repo_root=repo)
    assert passed is False, detail
    assert f"review-issue-{issue}.json" in detail
    assert "d" * 64 in detail
    assert "match" in detail.lower()


def test_v1_dangling_ref_is_marked_not_failed(tmp_path: Path) -> None:
    """Architect lock: no backfill. A pre-#1438 record with the same dangling ref
    that fails a v2 record is MARKED unresolvable and still passes, so nothing
    forces history to be rewritten to invent files that exist on no machine."""
    issue = 621
    repo, _ = _make_repo_with_committed_artifacts(tmp_path, issue)
    status_dir = tmp_path / "status"
    dangling_review = "git-history:agent-runtime/artifacts/reviews/review-issue-999999.json"
    _write_record(
        status_dir,
        issue,
        payload={
            "issue": issue,
            "wave": None,
            "review": {"status": "PASS", "artifactRef": dangling_review, "sha256": "e" * 64},
            "validation": {
                "status": "PASS",
                "artifactRef": (
                    "git-history:agent-runtime/artifacts/validation/validation-issue-999999.json"
                ),
                "sha256": "f" * 64,
            },
            "gateVersion": 1,
        },
    )
    # The same record at gateVersion 2 must fail -- otherwise this test proves nothing.
    v2 = json.loads((status_dir / f"issue-{issue}.json").read_text(encoding="utf-8"))
    v2["gateVersion"] = 2
    v2_dir = tmp_path / "status-v2"
    _write_record(v2_dir, issue, payload=v2)
    v2_passed, v2_detail = evaluate(issue, status_dir=v2_dir, repo_root=repo)
    assert v2_passed is False, v2_detail

    passed, detail = evaluate(issue, status_dir=status_dir, repo_root=repo)
    assert passed is True, detail
    assert "unresolvable" in detail.lower()
    assert "review-issue-999999.json" in detail


def test_shallow_checkout_reports_indeterminate_instead_of_a_wrong_verdict(
    tmp_path: Path,
) -> None:
    """CI checks this repo out shallow for the retention-guard job (pr.yml uses a
    bare actions/checkout there). History before the graft is absent, so 'this
    path is in no commit' is unknowable -- the guard must say so rather than
    emit an unresolvable verdict it cannot support."""
    issue = 1445
    repo, digests = _make_repo_with_committed_artifacts(tmp_path, issue)
    # A second commit so depth-1 genuinely truncates history.
    (repo / "later.txt").write_text("later", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--no-verify", "-m", "later")

    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--depth", "1", repo.as_uri(), str(shallow)],
        capture_output=True,
        text=True,
        check=True,
    )
    # Imported here, not at module scope: a second module-level import after the
    # sys.path insert would need its own E402 suppression, and the repo's debt
    # ratchet counts suppression identities (#1462). One import site is not worth
    # a unit of tracked debt.
    from artifact_ref_resolution import is_shallow_repository

    assert is_shallow_repository(shallow) is True
    assert is_shallow_repository(repo) is False

    status_dir = tmp_path / "status"
    dangling = "git-history:agent-runtime/artifacts/reviews/review-issue-999999.json"
    _write_record(
        status_dir,
        issue,
        payload=_v2_payload(
            issue,
            dangling,
            "a" * 64,
            f"git-history:agent-runtime/artifacts/validation/validation-issue-{issue}.json",
            digests["validation"],
        ),
    )
    # Full clone: the dangling ref is provably absent -> FAIL.
    full_passed, full_detail = evaluate(issue, status_dir=status_dir, repo_root=repo)
    assert full_passed is False, full_detail

    # Shallow clone: absence is not provable -> explicit indeterminate, not a FAIL.
    passed, detail = evaluate(issue, status_dir=status_dir, repo_root=shallow)
    assert passed is True, detail
    assert "shallow" in detail.lower()


def test_unsupported_ref_scheme_fails_a_v2_record(tmp_path: Path) -> None:
    """#670's schema still promises 'a CI run artifact URL fragment'. No such
    store exists, so a ref in that form resolves to nothing and must not be
    read as evidence."""
    issue = 1445
    repo, digests = _make_repo_with_committed_artifacts(tmp_path, issue)
    status_dir = tmp_path / "status"
    _write_record(
        status_dir,
        issue,
        payload=_v2_payload(
            issue,
            "https://github.com/org/repo/actions/runs/1/artifacts/2",
            "a" * 64,
            f"git-history:agent-runtime/artifacts/validation/validation-issue-{issue}.json",
            digests["validation"],
        ),
    )
    passed, detail = evaluate(issue, status_dir=status_dir, repo_root=repo)
    assert passed is False, detail
    assert "scheme" in detail.lower()


# --- #1497: git-history: asserts something .gitignore forbids ----------------
# #1438's generator wrote `git-history:agent-runtime/artifacts/reviews/...` while
# .gitignore:82 makes exactly that path uncommittable BY POLICY (ADR-003: emit is
# not commit). #1445's (correct) strictness then made every gateVersion 2 record
# unpassable. The fix is an honest scheme for policy-local bodies: `local-only:`
# claims the body existed locally and its sha256 was taken there, and does NOT
# claim retrievability. `git-history:` keeps its full #1445 strictness.


def _policy_local_v2_payload(issue: int) -> dict:
    return _v2_payload(
        issue,
        f"local-only:agent-runtime/artifacts/reviews/review-issue-{issue}.json",
        "a" * 64,
        f"local-only:agent-runtime/artifacts/validation/validation-issue-{issue}.json",
        "b" * 64,
    )


def test_policy_local_refs_pass_and_are_named(tmp_path: Path) -> None:
    """A gateVersion 2 record whose bodies live in the five gitignored body
    directories passes, and the detail NAMES both refs as unretrievable by
    policy rather than silently ignoring them."""
    issue = 1497
    repo, _ = _make_repo_with_committed_artifacts(tmp_path, issue)
    status_dir = tmp_path / "status"
    _write_record(status_dir, issue, payload=_policy_local_v2_payload(issue))

    passed, detail = evaluate(issue, status_dir=status_dir, repo_root=repo)
    assert passed is True, detail
    # Named, not swallowed: both refs appear in the detail...
    assert f"review-issue-{issue}.json" in detail
    assert f"validation-issue-{issue}.json" in detail
    # ...and the detail says what the class actually is.
    assert "policy" in detail.lower()

    # Non-vacuous: the pass is earned by the honest scheme, not by the guard
    # having stopped checking refs. The SAME paths under the `git-history:`
    # label still fail, because that label makes a claim history cannot back.
    lying = _v2_payload(
        issue,
        f"git-history:agent-runtime/artifacts/reviews/review-issue-{issue}.json",
        "a" * 64,
        f"git-history:agent-runtime/artifacts/validation/validation-issue-{issue}.json",
        "b" * 64,
    )
    lying_dir = tmp_path / "status-lying"
    _write_record(lying_dir, issue, payload=lying)
    lying_passed, lying_detail = evaluate(issue, status_dir=lying_dir, repo_root=repo)
    assert lying_passed is False, lying_detail


def test_v2_unresolvable_git_history_ref_still_fails(tmp_path: Path) -> None:
    """#1445 is preserved for genuinely committable paths: a `git-history:` ref
    naming a path that is in no commit is still an integrity failure. The new
    scheme must not have loosened the old one."""
    issue = 1497
    repo, digests = _make_repo_with_committed_artifacts(tmp_path, issue)
    status_dir = tmp_path / "status"
    _write_record(
        status_dir,
        issue,
        payload=_v2_payload(
            issue,
            # A committable path (no policy forbids committing backend source)
            # that nevertheless exists in no commit in this repo.
            "git-history:backend/src/juli_backend/never_committed.py",
            "c" * 64,
            f"git-history:agent-runtime/artifacts/validation/validation-issue-{issue}.json",
            digests["validation"],
        ),
    )
    passed, detail = evaluate(issue, status_dir=status_dir, repo_root=repo)
    assert passed is False, detail
    assert "never_committed.py" in detail
    assert "no commit" in detail.lower()


def test_local_only_scheme_cannot_launder_a_committable_path(tmp_path: Path) -> None:
    """The lie the new scheme could enable: relabel any dangling `git-history:`
    ref as `local-only:` and it stops failing. It must not. `local-only:` is
    admissible ONLY for a path inside the five gitignored body directories --
    the paths policy really does forbid committing."""
    issue = 1497
    repo, digests = _make_repo_with_committed_artifacts(tmp_path, issue)
    status_dir = tmp_path / "status"
    _write_record(
        status_dir,
        issue,
        payload=_v2_payload(
            issue,
            "local-only:backend/src/juli_backend/never_committed.py",
            "c" * 64,
            f"git-history:agent-runtime/artifacts/validation/validation-issue-{issue}.json",
            digests["validation"],
        ),
    )
    passed, detail = evaluate(issue, status_dir=status_dir, repo_root=repo)
    assert passed is False, detail
    assert "never_committed.py" in detail


def test_policy_local_refs_resolve_without_git_so_a_shallow_checkout_still_passes(
    tmp_path: Path,
) -> None:
    """CI runs the retention guard on a bare `actions/checkout` (no fetch-depth),
    so history is shallow and every `git-history:` ref there is INDETERMINATE.
    A `local-only:` ref is a statement about policy, not about this checkout's
    history, so it is answerable anyway -- and the answer must not degrade to
    the shallow-checkout wording."""
    issue = 1497
    repo, _ = _make_repo_with_committed_artifacts(tmp_path, issue)
    (repo / "later.txt").write_text("later", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--no-verify", "-m", "later")
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "--depth", "1", repo.as_uri(), str(shallow)],
        capture_output=True,
        text=True,
        check=True,
    )
    from artifact_ref_resolution import is_shallow_repository

    assert is_shallow_repository(shallow) is True

    status_dir = tmp_path / "status"
    _write_record(status_dir, issue, payload=_policy_local_v2_payload(issue))
    passed, detail = evaluate(issue, status_dir=status_dir, repo_root=shallow)
    assert passed is True, detail
    assert "policy" in detail.lower()
    assert "shallow" not in detail.lower()


def test_every_committed_gateversion_2_record_passes_the_guard() -> None:
    """The acceptance test that matters: on the real repo, every committed
    gateVersion 2 status record passes. Before #1497 all of them failed,
    because every one of them carried `git-history:` refs into gitignored
    body directories."""
    from common import STATUS_DIR as REAL_STATUS_DIR

    v2_issues = []
    for path in sorted(REAL_STATUS_DIR.glob("issue-*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict) and record.get("gateVersion") == 2:
            v2_issues.append(int(record["issue"]))

    assert v2_issues, "expected at least one committed gateVersion 2 record"
    failures = []
    for issue in v2_issues:
        passed, detail = evaluate(issue)
        if not passed:
            failures.append(detail)
    assert not failures, "gateVersion 2 records still failing: " + " | ".join(failures)
