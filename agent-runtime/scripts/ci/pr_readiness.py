#!/usr/bin/env python3
"""Pre-PR readiness check for issue-tier PRs (#1663).

Checks whether a PR would be red for conditions knowable locally before opening:
- wave manifest membership
- status record present and PASS

Two modes:

``--issue <N> --base <ref>`` — answer "would this PR be red", before gh pr create.
Exit non-zero and name every unmet condition. Exits zero only when all are met.

``--scan`` — for PRs already open, report which lack a PASS status record.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any  # Used in wave manifest type annotations

from check_artifact_retention_guard import evaluate as evaluate_status_record
from check_merge_status import evaluate as evaluate_merge_verdict
from common import AGENT_RUNTIME_ROOT, REPO_ROOT, STATUS_DIR
from wave_manifest import check_issue_membership

WAVES_DIR = AGENT_RUNTIME_ROOT / "artifacts" / "waves"


def status_record_path(issue: int, status_dir: Path = STATUS_DIR) -> Path:
    return status_dir / f"issue-{issue}.json"


def evaluate_issue_ready(
    issue: int,
    base_ref: str,
    *,
    status_dir: Path = STATUS_DIR,
    waves_dir: Path = WAVES_DIR,
) -> tuple[bool, list[str]]:
    """Check if an issue PR is ready to open.

    Returns (ready, reasons). When not ready, reasons lists every unmet condition.
    Fail closed: any condition that cannot be evaluated reports that reason.
    """
    reasons: list[str] = []

    # Load wave manifest by resolving base_ref
    wave_id_from_base = _extract_wave_id(base_ref)
    if not wave_id_from_base:
        reasons.append(f"base_ref {base_ref!r} does not match wave branch pattern")
        return False, reasons

    manifest_path = waves_dir / f"{wave_id_from_base}.json"
    if not manifest_path.is_file():
        reasons.append(
            f"wave manifest not found at {manifest_path.name} "
            f"(base_ref resolves to {wave_id_from_base!r})"
        )
        return False, reasons

    manifest: Any = None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        reasons.append(f"wave manifest unreadable: {exc}")
        return False, reasons

    if not isinstance(manifest, dict):
        reasons.append("wave manifest is not a JSON object")
        return False, reasons

    # Check manifest membership
    membership = check_issue_membership(manifest, issue)
    if not membership["valid"]:
        reasons.extend(membership["errors"])

    # Check status record using the real gate logic (including artifactRef checks).
    passed, detail = evaluate_status_record(issue, status_dir=status_dir, repo_root=REPO_ROOT)
    if not passed:
        reasons.append(detail)

    # #1569 split the record's two questions apart: the retention guard now answers
    # "is there evidence" and accepts a recorded FAIL as evidence, while the merge
    # verdict lives in check_merge_status. Asking only the first would report a
    # failed review as ready to open a PR that CI will then block -- which is the
    # opposite of what this script exists to tell you.
    merge_ok, merge_detail = evaluate_merge_verdict(issue, status_dir=status_dir)
    if not merge_ok:
        reasons.append(merge_detail)

    return len(reasons) == 0, reasons


def _extract_wave_id(base_ref: str) -> str | None:
    """Extract wave ID from a feature branch name.

    Expects ``feature/<id>-wave`` or ``feature/harness-<id>-wave`` format.
    Returns the wave id (e.g. 'wave-w5' or 'wave-harness-e-w5'),
    or None if the ref doesn't match.
    """
    if not base_ref.startswith("feature/"):
        return None
    branch_part = base_ref.removeprefix("feature/")
    if branch_part.endswith("-wave"):
        wave_part = branch_part.removesuffix("-wave")
        return f"wave-{wave_part}"
    return None


def _resolve_issue_from_branch(branch: str) -> int | None:
    """Extract issue number from a branch name.

    Expects ``feature/issue-<N>-*`` or ``fix/issue-<N>-*`` format.
    Returns the issue number or None.
    """
    import re

    match = re.search(r"issue-(\d+)", branch)
    if match:
        return int(match.group(1))
    return None


def _get_open_pr_branches() -> list[tuple[str, str]]:
    """Get list of open PRs with (head_branch, pr_number).

    Returns empty list if gh CLI is unavailable or no PRs open.
    """
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--json", "headRefName,number"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout)
        return [(item["headRefName"], str(item["number"])) for item in data]
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError, KeyError):
        return []


def scan_open_prs(
    *,
    status_dir: Path = STATUS_DIR,
    waves_dir: Path = WAVES_DIR,
) -> None:
    """List open PRs and their readiness status.

    Prints one line per PR with branch, issue, and readiness status.
    """
    prs = _get_open_pr_branches()
    if not prs:
        print("No open PRs found (or gh CLI unavailable)")
        return

    for branch, pr_number in prs:
        issue = _resolve_issue_from_branch(branch)
        if issue is None:
            print(
                f"PR #{pr_number} ({branch}): "
                "not an issue-tier PR (branch does not resolve to issue)"
            )
            continue

        base_ref = _extract_base_ref_from_pr(pr_number)
        if not base_ref:
            ready, reasons = (
                False,
                ["could not determine base ref from PR"],
            )
        else:
            ready, reasons = evaluate_issue_ready(
                issue, base_ref, status_dir=status_dir, waves_dir=waves_dir
            )

        status = "READY" if ready else "NOT READY"
        line = f"PR #{pr_number} ({branch}, issue #{issue}): {status}"
        if reasons:
            line += f" — {reasons[0]}"
        print(line)


def _extract_base_ref_from_pr(pr_number: str) -> str | None:
    """Get the base ref (target branch) of a PR.

    Returns the base branch name or None if unavailable.
    """
    try:
        result = subprocess.run(
            ["gh", "pr", "view", pr_number, "--json", "baseRefName"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        return data.get("baseRefName")
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError, KeyError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--issue",
        type=int,
        help="Issue number to check (with --base)",
    )
    parser.add_argument(
        "--base",
        help="Base branch (e.g. feature/harness-e-w5-wave) for manifest lookup",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Scan open PRs for readiness (gh CLI required)",
    )
    parser.add_argument(
        "--status-dir",
        type=Path,
        default=STATUS_DIR,
        help="Status record directory (default: %(default)s)",
    )
    parser.add_argument(
        "--waves-dir",
        type=Path,
        default=WAVES_DIR,
        help="Wave manifests directory (default: %(default)s)",
    )

    args = parser.parse_args()

    if args.scan:
        scan_open_prs(status_dir=args.status_dir, waves_dir=args.waves_dir)
        return 0

    if args.issue is None or args.base is None:
        parser.error("--issue and --base are required (or use --scan)")

    ready, reasons = evaluate_issue_ready(
        args.issue,
        args.base,
        status_dir=args.status_dir,
        waves_dir=args.waves_dir,
    )

    if ready:
        print(f"issue {args.issue}: READY to open PR (all checks passed)")
        return 0

    print(f"issue {args.issue}: NOT READY to open PR")
    for reason in reasons:
        print(f"  - {reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
