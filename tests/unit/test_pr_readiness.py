"""Pre-PR readiness check for issue-tier PRs (#1663).

Tests the pr_readiness script which checks whether a PR is ready to be
opened without knowing it will be red for conditions determinable locally.

Acceptance criteria:
1. --issue <N> --base <ref> exits non-zero when issue has no status record
   or no manifest entry; exits zero when both present and record is PASS.
2. Malformed, unreadable, or non-PASS status record reports specific reason.
3. --scan lists open PRs, marking each as ready or naming what it lacks.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

#: Gitignored artifact body root; a local-only: ref must live under it.
_BODY = "agent-runtime/artifacts"

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"


def _write_json(path: Path, payload: object) -> None:
    """Defer the ci-dir import so the module needs no path shim above imports.

    A module-level `sys.path.insert` followed by a late import is an E402, and
    suppressing it adds a suppression the ratchet then has to carry. Importing
    inside the helper keeps the module's import block clean.
    """
    sys.path.insert(0, str(CI_DIR))
    from common import write_json

    write_json(path, payload)


def _run_pr_readiness(*args: str) -> subprocess.CompletedProcess:
    """Run the pr_readiness script with given arguments."""
    script = CI_DIR / "pr_readiness.py"
    return subprocess.run(
        ["python", str(script), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


class TestIssuePrePrMode:
    """Test the --issue <N> --base <ref> mode."""

    def test_missing_status_record_fails(self, tmp_path: Path) -> None:
        """AC1: Missing status record exits non-zero with specific reason."""
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        manifest_dir = tmp_path / "waves"
        manifest_dir.mkdir()

        issue = 9999
        wave_id = "wave-test"

        # Create wave manifest with issue (so manifest check passes)
        manifest = {
            "waveId": wave_id,
            "branch": "feature/test-wave",
            "issues": [issue],
        }
        _write_json(manifest_dir / f"{wave_id}.json", manifest)

        result = _run_pr_readiness(
            "--issue",
            str(issue),
            "--base",
            "feature/test-wave",
            "--status-dir",
            str(status_dir),
            "--waves-dir",
            str(manifest_dir),
        )
        assert result.returncode != 0, f"Expected non-zero exit, got: {result.stdout}"
        assert "status record" in result.stdout.lower(), (
            f"Expected 'status record' in output, got: {result.stdout}"
        )

    def test_pass_status_record_succeeds(self, tmp_path: Path) -> None:
        """AC1: PASS status record exits zero."""
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        manifest_dir = tmp_path / "waves"
        manifest_dir.mkdir()

        issue = 9999
        wave_id = "wave-test"

        # Create PASS status record with required artifactRef and sha256 fields
        record = {
            "issue": issue,
            "review": {
                "status": "PASS",
                "artifactRef": "local-only:reviews/review-issue-9999.json",
                "sha256": "0" * 64,
            },
            "validation": {
                "status": "PASS",
                "artifactRef": "local-only:validation/validation-issue-9999.json",
                "sha256": "0" * 64,
            },
            "gateVersion": 1,
        }
        _write_json(status_dir / f"issue-{issue}.json", record)

        # Create wave manifest with issue
        manifest = {
            "waveId": wave_id,
            "branch": "feature/test-wave",
            "issues": [issue],
        }
        _write_json(manifest_dir / f"{wave_id}.json", manifest)

        result = _run_pr_readiness(
            "--issue",
            str(issue),
            "--base",
            "feature/test-wave",
            "--status-dir",
            str(status_dir),
            "--waves-dir",
            str(manifest_dir),
        )
        assert result.returncode == 0, f"Expected zero exit for PASS record, got: {result.stdout}"

    def test_non_pass_status_fails(self, tmp_path: Path) -> None:
        """AC2: Non-PASS status (FAIL) reports specific reason."""
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        manifest_dir = tmp_path / "waves"
        manifest_dir.mkdir()

        issue = 9998
        wave_id = "wave-test"

        # Create non-PASS status record with required fields
        record = {
            "issue": issue,
            "review": {
                "status": "FAIL",
                "artifactRef": "local-only:reviews/review-issue-9998.json",
                "sha256": "0" * 64,
            },
            "validation": {
                "status": "PASS",
                "artifactRef": "local-only:validation/validation-issue-9998.json",
                "sha256": "0" * 64,
            },
            "gateVersion": 1,
        }
        _write_json(status_dir / f"issue-{issue}.json", record)

        # Create wave manifest with issue
        manifest = {
            "waveId": wave_id,
            "branch": "feature/test-wave",
            "issues": [issue],
        }
        _write_json(manifest_dir / f"{wave_id}.json", manifest)

        result = _run_pr_readiness(
            "--issue",
            str(issue),
            "--base",
            "feature/test-wave",
            "--status-dir",
            str(status_dir),
            "--waves-dir",
            str(manifest_dir),
        )
        assert result.returncode != 0, (
            f"Expected non-zero for non-PASS record, got: {result.stdout}"
        )
        assert "review" in result.stdout.lower() or "status" in result.stdout.lower(), (
            f"Expected reason in output, got: {result.stdout}"
        )

    def test_malformed_status_record_fails(self, tmp_path: Path) -> None:
        """AC2: Malformed status record reports specific reason."""
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        manifest_dir = tmp_path / "waves"
        manifest_dir.mkdir()

        issue = 9997
        wave_id = "wave-test"

        # Create malformed (not a dict) status record
        malformed_path = status_dir / f"issue-{issue}.json"
        malformed_path.write_text("[1, 2, 3]", encoding="utf-8")

        # Create wave manifest with issue
        manifest = {
            "waveId": wave_id,
            "branch": "feature/test-wave",
            "issues": [issue],
        }
        _write_json(manifest_dir / f"{wave_id}.json", manifest)

        result = _run_pr_readiness(
            "--issue",
            str(issue),
            "--base",
            "feature/test-wave",
            "--status-dir",
            str(status_dir),
            "--waves-dir",
            str(manifest_dir),
        )
        assert result.returncode != 0, (
            f"Expected non-zero for malformed record, got: {result.stdout}"
        )
        assert "malformed" in result.stdout.lower() or "not" in result.stdout.lower(), (
            f"Expected 'malformed' in output, got: {result.stdout}"
        )

    def test_issue_not_in_manifest_fails(self, tmp_path: Path) -> None:
        """AC1: Issue not in manifest exits non-zero."""
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        manifest_dir = tmp_path / "waves"
        manifest_dir.mkdir()

        issue = 9996
        wave_id = "wave-test"

        # Create PASS status record with required fields
        record = {
            "issue": issue,
            "review": {
                "status": "PASS",
                "artifactRef": "local-only:reviews/review-issue-9996.json",
                "sha256": "0" * 64,
            },
            "validation": {
                "status": "PASS",
                "artifactRef": "local-only:validation/validation-issue-9996.json",
                "sha256": "0" * 64,
            },
            "gateVersion": 1,
        }
        _write_json(status_dir / f"issue-{issue}.json", record)

        # Create wave manifest WITHOUT this issue
        manifest = {
            "waveId": wave_id,
            "branch": "feature/test-wave",
            "issues": [9999, 10000],
        }
        _write_json(manifest_dir / f"{wave_id}.json", manifest)

        result = _run_pr_readiness(
            "--issue",
            str(issue),
            "--base",
            "feature/test-wave",
            "--status-dir",
            str(status_dir),
            "--waves-dir",
            str(manifest_dir),
        )
        assert result.returncode != 0, (
            f"Expected non-zero when issue not in manifest, got: {result.stdout}"
        )
        assert "manifest" in result.stdout.lower() or "missing" in result.stdout.lower(), (
            f"Expected 'manifest' or 'missing' in output, got: {result.stdout}"
        )

    def test_all_unmet_conditions_reported(self, tmp_path: Path) -> None:
        """AC1: When multiple conditions unmet, all are reported."""
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        manifest_dir = tmp_path / "waves"
        manifest_dir.mkdir()

        issue = 9995
        wave_id = "wave-test"

        # No status record
        # Create wave manifest WITHOUT this issue
        manifest = {
            "waveId": wave_id,
            "branch": "feature/test-wave",
            "issues": [9999, 10000],
        }
        _write_json(manifest_dir / f"{wave_id}.json", manifest)

        result = _run_pr_readiness(
            "--issue",
            str(issue),
            "--base",
            "feature/test-wave",
            "--status-dir",
            str(status_dir),
            "--waves-dir",
            str(manifest_dir),
        )
        assert result.returncode != 0, f"Expected non-zero when both unmet, got: {result.stdout}"
        # Should mention both missing status and missing manifest entry
        output = result.stdout.lower()
        assert output.count("missing") >= 2 or ("status" in output and "manifest" in output), (
            f"Expected multiple failures reported, got: {result.stdout}"
        )

    def test_artifactref_integrity_failure_caught(self, tmp_path: Path) -> None:
        """AC2: artifactRef integrity failure (gateVersion 2) is caught.

        This test would have failed with the old reimplemented logic, which
        lacked the artifactRef check. With the real evaluate() function,
        it correctly reports the integrity failure.
        """
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        manifest_dir = tmp_path / "waves"
        manifest_dir.mkdir()

        issue = 9994
        wave_id = "wave-test"

        # Create a gateVersion 2 record with an artifactRef that has a
        # mismatched sha256. This will fail integrity check in evaluate().
        # Using git-history: ref that points to a non-existent commit with wrong sha256.
        record = {
            "issue": issue,
            "review": {
                "status": "PASS",
                "artifactRef": "git-history:agent-runtime/artifacts/reviews/review-issue-9994.json",
                "sha256": "0" * 64,  # Intentionally wrong hash to trigger integrity failure
            },
            "validation": {
                "status": "PASS",
                "artifactRef": "local-only:validation/validation-issue-9994.json",
                "sha256": "0" * 64,
            },
            "gateVersion": 2,
        }
        _write_json(status_dir / f"issue-{issue}.json", record)

        # Create wave manifest with issue
        manifest = {
            "waveId": wave_id,
            "branch": "feature/test-wave",
            "issues": [issue],
        }
        _write_json(manifest_dir / f"{wave_id}.json", manifest)

        result = _run_pr_readiness(
            "--issue",
            str(issue),
            "--base",
            "feature/test-wave",
            "--status-dir",
            str(status_dir),
            "--waves-dir",
            str(manifest_dir),
        )
        # Should fail because artifactRef integrity check will fail
        assert result.returncode != 0, (
            f"Expected non-zero for artifactRef integrity failure, got: {result.stdout}"
        )
        # Should mention artifactRef or integrity issue
        assert "artifact" in result.stdout.lower() or "integrity" in result.stdout.lower(), (
            f"Expected artifactRef mention in output, got: {result.stdout}"
        )


class TestScanMode:
    """Test the --scan mode for listing open PRs."""

    def test_scan_marks_a_ready_pr_and_names_what_an_unready_one_lacks(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """AC3: --scan lists open PRs, marking each as ready or naming what it lacks."""
        import sys

        sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts" / "ci"))
        try:
            import pr_readiness
            from pr_readiness import scan_open_prs

            # Set up two issue-tier PRs: one fully ready, one missing its status record
            ready_issue = 4242
            unready_issue = 4243
            wave_id = "wave-test"

            # Mock _get_open_pr_branches to return our test PRs
            monkeypatch.setattr(
                pr_readiness,
                "_get_open_pr_branches",
                lambda: [
                    ("feature/issue-4242-ready", 900),
                    ("feature/issue-4243-unready", 901),
                ],
            )

            # Set up directories
            status_dir = tmp_path / "status"
            status_dir.mkdir()
            waves_dir = tmp_path / "waves"
            waves_dir.mkdir()

            # Create wave manifest with both issues
            _write_json(
                waves_dir / f"{wave_id}.json",
                {
                    "waveId": wave_id,
                    "branch": "feature/test-wave",
                    "issues": [ready_issue, unready_issue],
                },
            )

            # Create PASS status record for ready PR (same structure as real implementation)
            _write_json(
                status_dir / f"issue-{ready_issue}.json",
                {
                    "issue": ready_issue,
                    "review": {
                        "status": "PASS",
                        "artifactRef": f"local-only:{_BODY}/reviews/review-issue-4242.json",
                        "sha256": "0" * 64,
                    },
                    "validation": {
                        "status": "PASS",
                        "artifactRef": f"local-only:{_BODY}/validation/validation-issue-4242.json",
                        "sha256": "0" * 64,
                    },
                    "gateVersion": 2,
                },
            )
            # DO NOT create status record for unready PR (it's missing)

            # Mock _extract_base_ref_from_pr to return our test wave
            monkeypatch.setattr(
                pr_readiness,
                "_extract_base_ref_from_pr",
                lambda pr: "feature/test-wave",
            )

            # Call scan_open_prs and capture output
            scan_open_prs(status_dir=status_dir, waves_dir=waves_dir)
            out = capsys.readouterr().out

            # Assert per PR line, not against the whole buffer. "READY" is a
            # substring of "NOT READY", so a whole-buffer check is satisfied by
            # two unready PRs and never verifies the ready path at all.
            lines: dict[str, str] = {}
            for line in out.splitlines():
                if str(ready_issue) in line:
                    lines["ready"] = line
                if str(unready_issue) in line:
                    lines["unready"] = line

            assert "ready" in lines, f"no line named issue {ready_issue}: {out}"
            assert "unready" in lines, f"no line named issue {unready_issue}: {out}"

            # Load-bearing: this is the assertion that fails if the ready PR
            # stops being ready.
            assert "NOT READY" not in lines["ready"], lines["ready"]
            assert "READY" in lines["ready"], lines["ready"]

            # Verify unready PR is named and specific reason is given
            assert "NOT READY" in lines["unready"], lines["unready"]
            # The specific missing thing, not a generic "not ready".
            assert "status record" in lines["unready"].lower(), lines["unready"]

        finally:
            # Clean up the path
            if str(REPO_ROOT / "agent-runtime" / "scripts" / "ci") in sys.path:
                sys.path.remove(str(REPO_ROOT / "agent-runtime" / "scripts" / "ci"))
