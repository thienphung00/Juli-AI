#!/usr/bin/env python3
"""Lightweight, deterministic measurement support for the #301 A/B benchmark.

Computes only what can be derived from git and pytest output -- never estimates
token usage or wall-clock timing (those must come from platform telemetry or be
recorded as null). Intended to be run once per treatment, against that
treatment's own worktree, after its implementation run completes.

Usage:
    python agent-runtime/scripts/benchmarks/measure_issue_301.py \\
        --start-sha <A_START_SHA or B_START_SHA> \\
        --end-sha HEAD \\
        --hidden-test-path <path resolved from experiment/301-evaluator at grading time> \\
        --out agent-runtime/artifacts/benchmarks/issue-301/measured-<treatment>.json

This script does not read or require knowledge of the other treatment branch. It
does not hardcode the hidden evaluator test path -- that must be supplied at
grading time, out of band from either treatment's own session, so neither
treatment's agent ever sees it in this script's source.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

DOC_PREFIXES = ("docs/", "README.md", "CONTEXT.md", "EXECUTION.md")
RUNTIME_ARTIFACT_PREFIXES = ("agent-runtime/artifacts/",)
TEST_PREFIXES = ("tests/",)
EXCLUDED_PREFIXES = (
    "agent-runtime/artifacts/benchmarks/",
    "agent-runtime/artifacts/grill-cache/",
    "agent-runtime/scripts/benchmarks/",
)


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.stdout


def classify_path(path: str) -> str | None:
    for prefix in EXCLUDED_PREFIXES:
        if path.startswith(prefix):
            return None
    if path.startswith(RUNTIME_ARTIFACT_PREFIXES):
        return "runtimeArtifact"
    if path.startswith(TEST_PREFIXES):
        return "test"
    if path.startswith(DOC_PREFIXES) or path.endswith(".md"):
        return "documentation"
    return "production"


def compute_loc(start_sha: str, end_sha: str) -> dict:
    numstat = run(["git", "diff", "--numstat", start_sha, end_sha])
    totals = {
        "productionAdded": 0,
        "productionDeleted": 0,
        "testAdded": 0,
        "testDeleted": 0,
        "documentationAdded": 0,
        "documentationDeleted": 0,
        "runtimeArtifactAdded": 0,
        "runtimeArtifactDeleted": 0,
    }
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added_raw, deleted_raw, path = parts
        category = classify_path(path)
        if category is None:
            continue
        added = 0 if added_raw == "-" else int(added_raw)
        deleted = 0 if deleted_raw == "-" else int(deleted_raw)
        key = "test" if category == "test" else category
        totals[f"{key}Added"] += added
        totals[f"{key}Deleted"] += deleted
    return totals


PASS_RE = re.compile(r"(\d+) passed")
FAIL_RE = re.compile(r"(\d+) failed")
SKIP_RE = re.compile(r"(\d+) skipped")
ERROR_RE = re.compile(r"(\d+) error")
COLLECTED_RE = re.compile(r"collected (\d+) item")
COVERAGE_TOTAL_RE = re.compile(r"^TOTAL\s+\d+\s+\d+\s+(\d+)%", re.MULTILINE)


def run_pytest(test_path: str, with_coverage: bool) -> dict:
    cmd = ["pytest", test_path, "-v", "--tb=short"]
    if with_coverage:
        cmd += ["--cov=juli_backend", "--cov-report=term-missing"]
    output = subprocess.run(cmd, capture_output=True, text=True, check=False)
    text = output.stdout + "\n" + output.stderr

    def _extract(pattern: re.Pattern) -> int:
        m = pattern.search(text)
        return int(m.group(1)) if m else 0

    collected_m = COLLECTED_RE.search(text)
    passed = _extract(PASS_RE)
    failed = _extract(FAIL_RE) + _extract(ERROR_RE)
    skipped = _extract(SKIP_RE)
    collected = int(collected_m.group(1)) if collected_m else passed + failed + skipped
    pass_rate = None if collected == 0 else round(passed / collected, 4)
    coverage_m = COVERAGE_TOTAL_RE.search(text)
    coverage = float(coverage_m.group(1)) if coverage_m else None
    return {
        "collected": collected,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "passRate": pass_rate,
        "coveragePercentage": coverage,
        "rawOutputTail": "\n".join(text.splitlines()[-40:]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-sha", required=True)
    parser.add_argument("--end-sha", default="HEAD")
    parser.add_argument(
        "--hidden-test-path",
        required=True,
        help="Resolved from experiment/301-evaluator at grading time -- never hardcode.",
    )
    parser.add_argument("--with-coverage", action="store_true")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    loc = compute_loc(args.start_sha, args.end_sha)
    test_results = run_pytest(args.hidden_test_path, args.with_coverage)

    manifest = {
        "schemaVersion": "1.0.0",
        "artifactType": "benchmark_measurement",
        "issueId": 301,
        "startSha": args.start_sha,
        "endSha": args.end_sha,
        "linesOfCode": loc,
        "hiddenSuiteResults": test_results,
        "durationMs": {
            "note": "not measured by this script -- record from platform run telemetry or null",
        },
        "tokenUsage": {
            "note": "not measured by this script -- record only when platform telemetry provides it",
        },
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
