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

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

from common import write_json  # noqa: E402


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
        write_json(manifest_dir / f"{wave_id}.json", manifest)

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

        # Create PASS status record
        record = {
            "issue": issue,
            "review": {"status": "PASS"},
            "validation": {"status": "PASS"},
            "gateVersion": 1,
        }
        write_json(status_dir / f"issue-{issue}.json", record)

        # Create wave manifest with issue
        manifest = {
            "waveId": wave_id,
            "branch": "feature/test-wave",
            "issues": [issue],
        }
        write_json(manifest_dir / f"{wave_id}.json", manifest)

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

        # Create non-PASS status record
        record = {
            "issue": issue,
            "review": {"status": "FAIL"},
            "validation": {"status": "PASS"},
            "gateVersion": 1,
        }
        write_json(status_dir / f"issue-{issue}.json", record)

        # Create wave manifest with issue
        manifest = {
            "waveId": wave_id,
            "branch": "feature/test-wave",
            "issues": [issue],
        }
        write_json(manifest_dir / f"{wave_id}.json", manifest)

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
        write_json(manifest_dir / f"{wave_id}.json", manifest)

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

        # Create PASS status record
        record = {
            "issue": issue,
            "review": {"status": "PASS"},
            "validation": {"status": "PASS"},
            "gateVersion": 1,
        }
        write_json(status_dir / f"issue-{issue}.json", record)

        # Create wave manifest WITHOUT this issue
        manifest = {
            "waveId": wave_id,
            "branch": "feature/test-wave",
            "issues": [9999, 10000],
        }
        write_json(manifest_dir / f"{wave_id}.json", manifest)

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
        write_json(manifest_dir / f"{wave_id}.json", manifest)

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
