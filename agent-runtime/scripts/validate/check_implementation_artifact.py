#!/usr/bin/env python3
"""Gate: implementation artifact exists and has required runtime fields."""

from __future__ import annotations

import sys
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

REQUIRED_FIELDS = (
    "issueId",
    "executorDomain",
    "phaseRunId",
    "contextFilesLoaded",
    "skillsLoaded",
    "rulesLoaded",
    "mcpsUsed",
)

#: executionDurationMs and toolInvocationCount are required but can be unavailable;
#: they are validated separately below rather than by simple presence check.
REQUIRED_UNAVAILABLE_FIELDS = (
    "executionDurationMs",
    "toolInvocationCount",
)

#: #1441. ``tokenUsage`` used to sit in ``REQUIRED_FIELDS`` above and be
#: hard-required to carry ``total``, while the schema admitted only the measured
#: shape. The two were jointly unsatisfiable for an unmeasured run, and the
#: escape an agent actually took was an annotated ``{0, 0, 0}`` sentinel written
#: into the corpus this epic exists to measure. It is optional here now, and
#: ``{"available": false, "reason": ...}`` says "unmeasured" out loud.
TOKEN_USAGE_GUIDANCE = (
    'record {"available": false, "reason": "..."} (no "value" key) when the run '
    "was not measured, or {input, output, total} when it was"
)


def check_token_usage(token_usage: Any) -> tuple[bool, str]:
    """Validate the two admissible shapes, and only those.

    Returns ``(ok, detail)``. A third shape fails closed rather than being read
    on a guess, and a zero total is rejected outright: it is exactly as
    unsourceable as any other invented number and now has an honest
    alternative, so there is no longer a reason to write one.
    """
    if not isinstance(token_usage, dict):
        return False, f"tokenUsage must be an object; {TOKEN_USAGE_GUIDANCE}"

    if "available" in token_usage:
        if token_usage["available"] is not False:
            return False, f"tokenUsage.available may only be false; {TOKEN_USAGE_GUIDANCE}"
        if "value" in token_usage:
            return False, (
                'tokenUsage carries "value" alongside available:false — the unavailable '
                "shape omits the key so a consumer that skips the check raises rather "
                "than reading a plausible number"
            )
        reason = token_usage.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return False, f"tokenUsage.reason required when unavailable; {TOKEN_USAGE_GUIDANCE}"
        extra = set(token_usage) - {"available", "reason"}
        if extra:
            return False, f"unexpected tokenUsage keys {sorted(extra)}; {TOKEN_USAGE_GUIDANCE}"
        return True, ""

    total = token_usage.get("total")
    if not isinstance(total, int) or isinstance(total, bool):
        return False, f"tokenUsage.total must be an integer; {TOKEN_USAGE_GUIDANCE}"
    if total <= 0:
        return False, (
            "tokenUsage.total is 0, which reads as a measurement and is not one — "
            f"{TOKEN_USAGE_GUIDANCE}"
        )
    return True, ""


def check_unavailable_field(field_value: Any, field_name: str) -> tuple[bool, str]:
    """Validate two-shape fields (measured integer or unavailable).

    #1732: executionDurationMs and toolInvocationCount follow the same pattern
    as tokenUsage: either a positive integer measurement, or
    {available: false, reason} when unmeasured. A zero is rejected because it
    looks like a measurement and is not one.
    """
    if isinstance(field_value, int) and not isinstance(field_value, bool):
        if field_value <= 0:
            return False, (
                f"{field_name} is {field_value}, which reads as a measurement and is not one — "
                f"record 1+ for a measurement, or {{'available': false, 'reason': '...'}} when unavailable"
            )
        return True, ""

    if isinstance(field_value, dict):
        if "available" in field_value:
            if field_value["available"] is not False:
                return False, f"{field_name}.available may only be false"
            reason = field_value.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                return False, f"{field_name}.reason required when unavailable"
            extra = set(field_value) - {"available", "reason"}
            if extra:
                return False, f"unexpected {field_name} keys {sorted(extra)}"
            return True, ""
        return False, f"{field_name} as dict must carry {{'available': false, 'reason': '...'}}"

    return (
        False,
        f"{field_name} must be a positive integer or {{'available': false, 'reason': '...'}}",
    )


def run_check(issue: int, *, path: Path | None = None) -> tuple[bool, str, dict[str, Any]]:
    path = path if path is not None else implementation_artifact_path(issue)
    if not path.exists():
        return (
            False,
            "Implementation artifact missing",
            {"path": f"agent-runtime/artifacts/implementations/implementation-issue-{issue}.json"},
        )

    artifact = load_json(path)
    missing = [field for field in REQUIRED_FIELDS if field not in artifact]
    if missing:
        return False, f"Missing fields: {', '.join(missing)}", {"missing": missing}

    # Check unavailable fields separately (they can be integers or unavailable shapes)
    missing_unavailable = [field for field in REQUIRED_UNAVAILABLE_FIELDS if field not in artifact]
    if missing_unavailable:
        return (
            False,
            f"Missing fields: {', '.join(missing_unavailable)}",
            {"missing": missing_unavailable},
        )

    if artifact.get("issueId") != issue:
        return False, f"issueId mismatch: expected {issue}", {"issueId": artifact.get("issueId")}

    domain = artifact.get("executorDomain")
    if domain not in {
        "ui-ux",
        "backend",
        "data-platform",
        "machine-learning",
        "integrations",
    }:
        return False, f"Invalid executorDomain: {domain}", {}

    context_files = artifact.get("contextFilesLoaded")
    if not isinstance(context_files, list) or len(context_files) < 1:
        return (
            False,
            "contextFilesLoaded must be a non-empty list (context telemetry)",
            {
                "contextFilesLoaded": context_files,
            },
        )

    rules_loaded = artifact.get("rulesLoaded")
    if not isinstance(rules_loaded, list):
        return (
            False,
            "rulesLoaded must be a list (Tier-2 rule telemetry)",
            {
                "rulesLoaded": rules_loaded,
            },
        )

    mcps_used = artifact.get("mcpsUsed")
    if not isinstance(mcps_used, list):
        return (
            False,
            "mcpsUsed must be a list (MCP telemetry)",
            {
                "mcpsUsed": mcps_used,
            },
        )

    # Validate executionDurationMs (#1732)
    duration = artifact.get("executionDurationMs")
    ok, detail = check_unavailable_field(duration, "executionDurationMs")
    if not ok:
        return False, detail, {"executionDurationMs": duration}

    # Validate toolInvocationCount (#1732)
    invocation_count = artifact.get("toolInvocationCount")
    ok, detail = check_unavailable_field(invocation_count, "toolInvocationCount")
    if not ok:
        return False, detail, {"toolInvocationCount": invocation_count}

    details: dict[str, Any] = {
        "executorDomain": domain,
        "phaseRunId": artifact.get("phaseRunId"),
        "contextFileCount": len(context_files),
        "rulesLoadedCount": len(rules_loaded),
        "mcpsUsedCount": len(mcps_used),
    }

    # Report duration availability
    if isinstance(duration, int) and duration > 0:
        details["executionDurationMs"] = duration
        details["executionDurationAvailable"] = True
    elif isinstance(duration, dict):
        details["executionDurationAvailable"] = False
        details["executionDurationReason"] = duration.get("reason", "unknown")

    # Report invocation count availability
    if isinstance(invocation_count, int) and invocation_count > 0:
        details["toolInvocationCount"] = invocation_count
        details["toolInvocationCountAvailable"] = True
    elif isinstance(invocation_count, dict):
        details["toolInvocationCountAvailable"] = False
        details["toolInvocationCountReason"] = invocation_count.get("reason", "unknown")

    # Absent is allowed: the schema makes the field optional, and a run with no
    # persisted transcript has nothing honest to put here (#1441).
    if "tokenUsage" not in artifact:
        details["tokenUsageAvailable"] = False
        return True, f"Implementation artifact present; domain {domain}", details

    token_usage = artifact["tokenUsage"]
    ok, detail = check_token_usage(token_usage)
    if not ok:
        return False, detail, {"tokenUsage": token_usage}

    available = "available" not in token_usage
    details["tokenUsageAvailable"] = available
    if available:
        # Only a measured reading gets a number reported. Emitting 0 for an
        # unmeasured one would be the same lie one layer down.
        details["tokenUsageTotal"] = token_usage["total"]
    else:
        details["tokenUsageUnavailableReason"] = token_usage["reason"]

    return True, f"Implementation artifact present; domain {domain}", details


def main() -> int:
    args = parse_args("Validate implementation artifact")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, details = run_check(issue)
    detail = description if not passed else ""
    return print_check_result("implementation_artifact_present", passed, detail)


if __name__ == "__main__":
    raise SystemExit(main())
