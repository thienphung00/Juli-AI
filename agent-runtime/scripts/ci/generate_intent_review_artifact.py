#!/usr/bin/env python3
"""Generate or refresh an intent-review artifact for an issue."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    SchemaValidationError,
    build_intent_review_artifact,
    intent_review_artifact_path,
    load_intent_review_artifact,
    load_json,
    resolve_issue_number,
    write_json_with_schema_validation,
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
    parser.add_argument(
        "--phase-run-id",
        help="Correlates this intent-review with its implementation/validation artifacts; "
        "derived from issue + git HEAD sha when omitted (#1881)",
    )
    args = parser.parse_args()
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print(
            "error: could not resolve issue number (use --issue or feat/issue-N branch)",
            file=sys.stderr,
        )
        return 1

    existing = None if args.fresh else load_intent_review_artifact(issue)
    overrides = load_json(args.input_json) if args.input_json and args.input_json.exists() else None

    artifact = build_intent_review_artifact(
        issue,
        existing=existing,
        overrides=overrides,
        fresh=args.fresh,
        phase_run_id=args.phase_run_id,
    )

    out = intent_review_artifact_path(issue)
    try:
        write_json_with_schema_validation(out, artifact, "intent_review")
    except SchemaValidationError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(
        f"wrote {out} spec_fidelity={artifact.get('spec_fidelity')} "
        f"smells={len(artifact.get('smells') or [])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
