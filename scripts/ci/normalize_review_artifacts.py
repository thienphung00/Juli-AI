#!/usr/bin/env python3
"""Normalize review artifacts: migrate legacy warnings[] and align status."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    REVIEWS_DIR,
    build_review_artifact,
    load_json,
    review_status_issues,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--issue",
        type=int,
        action="append",
        help="Issue number(s) to normalize; default all review-issue-*.json",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report issues only; do not write files",
    )
    args = parser.parse_args()

    if args.issue:
        paths = [REVIEWS_DIR / f"review-issue-{n}.json" for n in args.issue]
    else:
        paths = sorted(REVIEWS_DIR.glob("review-issue-*.json"))

    changed = 0
    failed = 0
    for path in paths:
        if not path.exists():
            print(f"skip missing {path}", file=sys.stderr)
            failed += 1
            continue
        existing = load_json(path)
        issues = review_status_issues(existing)
        if not issues:
            continue
        changed += 1
        print(f"{path.name}: {'; '.join(issues)}")
        if args.check:
            continue
        issue = existing.get("issue")
        if not isinstance(issue, int):
            print(f"skip {path.name}: missing integer issue field", file=sys.stderr)
            failed += 1
            continue
        artifact = build_review_artifact(issue, existing=existing, update_timestamp=False)
        write_json(path, artifact)
        print(f"  -> wrote {path.name} status={artifact.get('status')}")

    if args.check:
        print(f"{changed} artifact(s) need normalization")
        return 1 if changed else 0

    print(f"normalized {changed} artifact(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
