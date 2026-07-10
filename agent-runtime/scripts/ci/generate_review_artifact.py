#!/usr/bin/env python3
"""Generate or refresh a review artifact for an issue."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    build_review_artifact,
    load_json,
    load_review_artifact,
    resolve_issue_number,
    review_artifact_path,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", type=int, required=False)
    parser.add_argument(
        "--input-json",
        type=Path,
        help="Optional JSON file to merge into the artifact (deep merge)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore existing artifact on disk; start from template + --input-json only",
    )
    args = parser.parse_args()
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: could not resolve issue number (use --issue or feat/issue-N branch)", file=sys.stderr)
        return 1

    existing = None if args.fresh else load_review_artifact(issue)
    overrides = load_json(args.input_json) if args.input_json and args.input_json.exists() else None

    artifact = build_review_artifact(issue, existing=existing, overrides=overrides, fresh=args.fresh)

    out = review_artifact_path(issue)
    write_json(out, artifact)
    print(f"wrote {out} status={artifact.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
