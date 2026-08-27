#!/usr/bin/env python3
"""Gate: red→green is measured, not attested.

Replaces the trust boundary in ``check_implementation_tdd_evidence``, which
passes on a self-reported ``exitCode: 0`` that nothing re-runs. This gate runs
the change's own tests against base source and head source and reads the real
exit codes.

Fail-closed by construction: every path that cannot *prove* red→green returns
False. A probe that already passes at base is reported as non-discriminating
rather than counted as evidence — that is the ``assert True`` hole.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    implementation_artifact_path,
    load_json,
    parse_args,
    print_check_result,
    resolve_issue_number,
)
from differential_tdd import (  # noqa: E402
    VERDICT_INCONCLUSIVE,
    VERDICT_RED_GREEN,
    classify_probe,
    materialize_base_tree,
    overlay_probes,
    resolve_base_sha,
    run_python_probes,
    select_probe_tests,
)
from implementation_tdd import files_trigger_tdd_evidence  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


def run_check(issue: int, repo_root: Path | None = None) -> tuple[bool, str, dict[str, Any]]:
    root = repo_root or REPO_ROOT
    path = implementation_artifact_path(issue)
    details: dict[str, Any] = {"issueId": issue}

    if not path.exists():
        details["path"] = (
            f"agent-runtime/artifacts/implementations/implementation-issue-{issue}.json"
        )
        return False, "Implementation artifact missing", details

    artifact = load_json(path)
    requires_tdd, matched_paths = files_trigger_tdd_evidence(artifact.get("filesModified"))
    details["requiresTddEvidence"] = requires_tdd
    details["matchedPaths"] = matched_paths

    if not requires_tdd:
        details["skipped"] = True
        return True, "No in-scope code changes — differential TDD not required", details

    probes = select_probe_tests(artifact)
    details["probes"] = probes
    if not probes:
        return False, "No test files in testsAdded/testsUpdated to probe", details

    python_probes = [p for p in probes if p.endswith(".py")]
    if not python_probes:
        # Honest skip: the JS runner is not implemented yet. Do not claim a pass
        # for a property this gate did not measure.
        details["skipped"] = True
        details["reason"] = "only non-python probes; JS differential runner not implemented"
        return True, "No python probes — differential TDD not evaluated", details

    base_sha = resolve_base_sha(root)
    details["baseSha"] = base_sha
    if base_sha is None:
        return False, "Could not resolve merge-base against origin/main", details

    with tempfile.TemporaryDirectory(prefix=f"difftdd-{issue}-") as tmp:
        base_tree = Path(tmp) / "base"
        if not materialize_base_tree(root, base_sha, base_tree):
            return False, f"Could not materialise base tree at {base_sha}", details

        overlaid = overlay_probes(root, base_tree, python_probes)
        details["probesOverlaid"] = overlaid
        if not overlaid:
            return False, "No probe files exist at head to overlay onto base", details

        base_exit, base_output = run_python_probes(base_tree, overlaid, sys.executable)
        head_exit, head_output = run_python_probes(root, overlaid, sys.executable)

    verdict, reason = classify_probe(base_exit, head_exit)
    details["baseExit"] = base_exit
    details["headExit"] = head_exit
    details["verdict"] = verdict
    # Real captured output — the evidence the Executor previously authored by hand.
    details["baseEvidence"] = base_output[-1200:] if base_output else ""
    details["headEvidence"] = head_output[-1200:] if head_output else ""

    if verdict == VERDICT_RED_GREEN:
        return True, reason, details
    if verdict == VERDICT_INCONCLUSIVE:
        return False, f"Red→green unproven: {reason}", details
    return False, reason, details


def main() -> int:
    args = parse_args("Verify red→green by executing the change's own tests")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, _ = run_check(issue)
    return print_check_result("differential_tdd", passed, description if not passed else "")


if __name__ == "__main__":
    raise SystemExit(main())
