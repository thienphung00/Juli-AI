#!/usr/bin/env python3
"""Rollout cutover inventory for the ADR-052 wave free-merge model (CI-WAVE-4 / #662).

Enumerates every active `feature/*-wave` branch and every open PR that
targets (base) or originates from (head) a wave branch, then classifies each
as using the **refined** ADR-052 workflow (committed wave manifest under
`agent-runtime/artifacts/waves/wave-<id>.json`, three-tier `pr.yml` with
`classify-tier` + `artifact-gate` synced) or the **legacy** pre-#659/#660/#661
workflow (no manifest / stale `pr.yml`).

This is an inventory + reporting tool, not a pass/fail merge gate: finding a
legacy-workflow branch is a real, reportable finding for operator follow-up —
it must never be silently normalized to a clean pass, and this script never
migrates or edits another branch's workflow. Exit code is 0 for a successful
enumeration (including one that finds legacy coverage) and 1 only on a hard
failure to enumerate (e.g. no git available).
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO_ROOT  # noqa: E402

WAVE_BRANCH_GLOB = "feature/*-wave"
WAVE_MANIFEST_DIR_PREFIX = "agent-runtime/artifacts/waves/"


def _run(cmd: list[str], *, cwd: Path | None = None) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd or REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)


def list_active_wave_branches() -> tuple[list[str], bool]:
    """Return (branch names without remote prefix, ok) for remote branches
    matching `feature/*-wave`. `ok` is False only when git itself could not
    be invoked (hard failure), not when there are simply zero matches."""
    code, out, _err = _run(["git", "fetch", "--prune", "origin", "--quiet"])
    code, out, err = _run(["git", "branch", "-r", "--list", f"origin/{WAVE_BRANCH_GLOB}"])
    if code != 0 and not out:
        return [], False
    branches: list[str] = []
    for line in out.splitlines():
        name = line.strip().removeprefix("origin/")
        if name and fnmatch.fnmatch(name, WAVE_BRANCH_GLOB):
            branches.append(name)
    return sorted(set(branches)), True


def list_wave_targeted_prs() -> tuple[list[dict[str, Any]], bool]:
    """Return (PRs, gh_available). PRs are open GitHub PRs whose base or head
    ref matches `feature/*-wave`. When `gh` is unavailable (no auth, no
    binary, offline test context), returns ([], False) so the caller can
    report the inventory as branch-only rather than pretend PR coverage was
    checked."""
    code, out, _err = _run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--json",
            "number,title,baseRefName,headRefName,url,updatedAt",
            "--limit",
            "200",
        ]
    )
    if code != 0 or not out.strip():
        return [], False
    try:
        prs = json.loads(out)
    except json.JSONDecodeError:
        return [], False
    matched = [
        pr
        for pr in prs
        if fnmatch.fnmatch(pr.get("baseRefName", ""), WAVE_BRANCH_GLOB)
        or fnmatch.fnmatch(pr.get("headRefName", ""), WAVE_BRANCH_GLOB)
    ]
    return matched, True


def _remote_ls_tree(branch: str) -> list[str]:
    code, out, _err = _run(["git", "ls-tree", "-r", "--name-only", f"origin/{branch}"])
    if code != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def _remote_file(branch: str, path: str) -> str | None:
    code, out, _err = _run(["git", "show", f"origin/{branch}:{path}"])
    if code != 0:
        return None
    return out


def classify_wave_branch(branch: str) -> dict[str, Any]:
    """Classify one wave branch as refined vs legacy against the ADR-052
    contract: a committed wave manifest (CI-WAVE-1, #659) and a `pr.yml`
    synced with the three-tier `classify-tier` / `artifact-gate` jobs
    (CI-WAVE-2/3, #660/#661)."""
    tree = _remote_ls_tree(branch)
    has_manifest = any(p.startswith(WAVE_MANIFEST_DIR_PREFIX) and p.endswith(".json") for p in tree)
    manifest_files = sorted(p for p in tree if p.startswith(WAVE_MANIFEST_DIR_PREFIX) and p.endswith(".json"))

    workflow = _remote_file(branch, ".github/workflows/pr.yml") or ""
    has_classify_tier = "classify-tier:" in workflow
    has_artifact_gate = "artifact-gate:" in workflow
    has_domain_matched_wave_push = "filter-wave" in workflow and "github.event.before" in workflow

    reasons: list[str] = []
    if not has_manifest:
        reasons.append("no committed wave manifest under agent-runtime/artifacts/waves/")
    if not has_classify_tier:
        reasons.append("pr.yml missing classify-tier job (pre three-tier CI)")
    if not has_artifact_gate:
        reasons.append("pr.yml missing artifact-gate job (still on ai-review or no deferred gate)")
    if not has_domain_matched_wave_push:
        reasons.append("pr.yml missing before->after domain-matched wave-push filtering (pre CI-WAVE-3)")

    refined = has_manifest and has_classify_tier and has_artifact_gate and has_domain_matched_wave_push
    return {
        "branch": branch,
        "workflow": "refined" if refined else "legacy",
        "hasWaveManifest": has_manifest,
        "manifestFiles": manifest_files,
        "hasClassifyTier": has_classify_tier,
        "hasArtifactGate": has_artifact_gate,
        "hasDomainMatchedWavePush": has_domain_matched_wave_push,
        "reasons": [] if refined else reasons,
    }


def classify_pr(pr: dict[str, Any], branch_classifications: dict[str, dict[str, Any]]) -> dict[str, Any]:
    base = pr.get("baseRefName", "")
    head = pr.get("headRefName", "")
    role = "issue-to-wave" if fnmatch.fnmatch(base, WAVE_BRANCH_GLOB) else "wave-to-main"
    wave_branch = base if role == "issue-to-wave" else head
    branch_verdict = branch_classifications.get(wave_branch)
    workflow = branch_verdict["workflow"] if branch_verdict else "unknown"
    return {
        "number": pr.get("number"),
        "title": pr.get("title"),
        "url": pr.get("url"),
        "baseRefName": base,
        "headRefName": head,
        "role": role,
        "waveBranch": wave_branch,
        "workflow": workflow,
    }


def build_report() -> dict[str, Any]:
    branches, branches_ok = list_active_wave_branches()
    prs, gh_available = list_wave_targeted_prs()

    branch_reports = [classify_wave_branch(b) for b in branches]
    branch_classifications = {r["branch"]: r for r in branch_reports}
    pr_reports = [classify_pr(pr, branch_classifications) for pr in prs]

    refined_branches = [r for r in branch_reports if r["workflow"] == "refined"]
    legacy_branches = [r for r in branch_reports if r["workflow"] == "legacy"]
    refined_prs = [r for r in pr_reports if r["workflow"] == "refined"]
    legacy_prs = [r for r in pr_reports if r["workflow"] in ("legacy", "unknown")]

    mixed_coverage = bool(refined_branches) and bool(legacy_branches)
    any_legacy = bool(legacy_branches) or bool(legacy_prs)

    return {
        "planId": "rep-662-ci-wave-4-docs-rollout-verification",
        "generatedBy": "check_wave_rollout_cutover.py",
        "enumeration": {
            "branchesOk": branches_ok,
            "ghAvailable": gh_available,
        },
        "waveBranches": branch_reports,
        "waveTargetedPrs": pr_reports,
        "summary": {
            "totalWaveBranches": len(branch_reports),
            "refinedWaveBranches": len(refined_branches),
            "legacyWaveBranches": len(legacy_branches),
            "totalWaveTargetedPrs": len(pr_reports),
            "refinedPrs": len(refined_prs),
            "legacyOrUnknownPrs": len(legacy_prs),
            "mixedCoverage": mixed_coverage,
            "anyLegacyCoverage": any_legacy,
        },
    }


def print_human_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print("=== ADR-052 wave rollout cutover inventory ===")
    if not report["enumeration"]["branchesOk"]:
        print("WARNING: could not enumerate remote branches (git failure)")
    if not report["enumeration"]["ghAvailable"]:
        print("NOTE: `gh` unavailable in this context — PR inventory is empty (branch-only fallback)")
    print(
        f"Wave branches: {summary['totalWaveBranches']} total "
        f"({summary['refinedWaveBranches']} refined, {summary['legacyWaveBranches']} legacy)"
    )
    for b in report["waveBranches"]:
        marker = "REFINED" if b["workflow"] == "refined" else "LEGACY "
        print(f"  [{marker}] {b['branch']}")
        for reason in b["reasons"]:
            print(f"            - {reason}")
    print(
        f"Wave-targeted open PRs: {summary['totalWaveTargetedPrs']} total "
        f"({summary['refinedPrs']} refined, {summary['legacyOrUnknownPrs']} legacy/unknown)"
    )
    for p in report["waveTargetedPrs"]:
        marker = "REFINED" if p["workflow"] == "refined" else p["workflow"].upper()
        print(f"  [{marker}] #{p['number']} {p['title']} ({p['role']}, wave={p['waveBranch']})")
    if summary["mixedCoverage"]:
        print("RESULT: MIXED coverage — some wave branches/PRs are refined, some are still legacy.")
    elif summary["anyLegacyCoverage"]:
        print("RESULT: ALL enumerated wave branches/PRs are on the LEGACY workflow. Operator follow-up needed.")
    elif summary["totalWaveBranches"] == 0:
        print("RESULT: no active feature/*-wave branches found.")
    else:
        print("RESULT: all enumerated wave branches/PRs are on the refined ADR-052 workflow.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        action="store_true",
        help="print a human-readable report before the JSON payload",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="suppress the human-readable report even if --report is also passed",
    )
    args = parser.parse_args()

    report = build_report()
    if args.report and not args.json_only:
        print_human_report(report)
        print()
    print(json.dumps(report, indent=2))

    if not report["enumeration"]["branchesOk"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
