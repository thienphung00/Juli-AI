#!/usr/bin/env python3
"""Gate: reject hardcoded release smoke/health success without step evidence."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    load_json,
    parse_args,
    print_check_result,
    resolve_issue_number,
)
import common  # noqa: E402
from release_metadata_honesty import (  # noqa: E402
    release_artifact_covers_issue,
    release_metadata_problems,
)


def _find_release_artifacts_for_issue(issue: int) -> list[tuple[str, dict[str, Any]]]:
    releases_dir = common.RELEASES_DIR
    if not releases_dir.exists():
        return []
    matches: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(releases_dir.glob("release-*.json")):
        artifact = load_json(path)
        if release_artifact_covers_issue(artifact, issue):
            matches.append((path.name, artifact))
    return matches


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:
    matches = _find_release_artifacts_for_issue(issue)
    details: dict[str, Any] = {
        "issueId": issue,
        "releaseArtifacts": [name for name, _ in matches],
    }

    if not matches:
        details["skipped"] = True
        return True, "No release artifact for issue — honesty check skipped", details

    all_problems: list[str] = []
    for name, artifact in matches:
        metadata = artifact.get("deploymentMetadata") or {}
        problems = release_metadata_problems(metadata)
        if problems:
            all_problems.extend(f"{name}: {problem}" for problem in problems)

    if all_problems:
        details["problems"] = all_problems
        return False, "; ".join(all_problems), details

    return True, "Release metadata includes step evidence for asserted checks", details


def main() -> int:
    args = parse_args("Validate release metadata honesty")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, _ = run_check(issue)
    return print_check_result(
        "release_metadata_honesty", passed, description if not passed else ""
    )


if __name__ == "__main__":
    raise SystemExit(main())
