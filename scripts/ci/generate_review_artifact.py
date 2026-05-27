#!/usr/bin/env python3
"""Generate a review artifact template for an issue."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REVIEWS_DIR, load_json, resolve_issue_number, utc_now_iso, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", type=int, required=False)
    parser.add_argument(
        "--input-json",
        type=Path,
        help="Optional JSON file to merge into the generated artifact",
    )
    args = parser.parse_args()
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: could not resolve issue number (use --issue or feat/issue-N branch)", file=sys.stderr)
        return 1

    artifact = {
        "id": f"review-issue-{issue}",
        "issue": issue,
        "timestamp": utc_now_iso(),
        "reviewedBy": "review skill",
        "status": "PASS",
        "summary": "",
        "criticalFindings": [],
        "modulesTouched": [],
        "interfaceChanges": [],
        "moduleDrift": False,
        "driftDetails": [],
        "testCoverage": {
            "acceptance": {
                "total": 0,
                "mapped": 0,
                "unmapped": [],
                "mappings": [],
            },
            "unit": {"passed": 0, "failed": 0},
        },
        "recommendations": [],
        "approvalReady": True,
    }

    if args.input_json and args.input_json.exists():
        artifact.update(load_json(args.input_json))

    out = REVIEWS_DIR / f"review-issue-{issue}.json"
    write_json(out, artifact)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
