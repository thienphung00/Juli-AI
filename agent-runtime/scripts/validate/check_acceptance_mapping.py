#!/usr/bin/env python3
"""Gate: acceptance criteria mapped to real pytest nodes."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    criterion_matches_test,
    load_review_artifact,
    parse_args,
    print_check_result,
    pytest_node_exists,
    resolve_issue_number,
)

#: Injectable-fact seam (#1761), the same shape as ``_ref_scheme_seam()`` in
#: ``generate_status_records.py``: production resolves for real, a
#: test/harness substitutes. This env var carries the ONLY substitution path —
#: never a Python-level monkeypatch of the resolver — because the mutation
#: harness (``eval/gate_scoring.py``) always runs this gate as a subprocess, so
#: a substitution that does not cross a process boundary would never reach the
#: real sweep that produces ``eval/results/gate_operator_scores.json``.
#:
#: Scoped to one exact issue number (JSON ``{"issue": N, "count": M}``) so a
#: stale override left in an environment can never answer for a different
#: issue — the override is ignored, not fallen back on blindly, when the
#: issue does not match.
CRITERIA_COUNT_OVERRIDE_ENV = "JULI_HARNESS_CRITERIA_COUNT_OVERRIDE"


def criteria_count_override_env(issue: int, count: int) -> dict[str, str]:
    """Build the env-var injection a harness registers as its provider.

    ``eval/gate_scoring.py`` merges this into the subprocess environment it
    runs every gate under, for the exact synthetic issue number the mutation
    fixture is installed for — the harness's substitute for a real ``gh``
    lookup, which can never resolve a synthetic issue.
    """
    return {CRITERIA_COUNT_OVERRIDE_ENV: json.dumps({"issue": issue, "count": count})}


def _criteria_count_from_override(issue: int) -> int | None:
    """The harness's provider, if one is registered for this exact issue."""
    raw = os.environ.get(CRITERIA_COUNT_OVERRIDE_ENV)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        override_issue = int(payload["issue"])
        override_count = int(payload["count"])
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None
    if override_issue != issue:
        return None
    return override_count


#: The two, and only two, criterion shapes the repo's issues actually carry
#: (#1879). Numbered lists are the hand-authored corpus; GIVEN/WHEN/THEN
#: bullets are what ``to-issues`` writes and what every architect-authored
#: issue uses. Matched at the *start* of the line only, on purpose: a
#: continuation line such as ``  Observable at: ...`` or ``  Verified by:
#: ...`` is indented prose describing the previous criterion, not a new
#: bullet, and must never inflate the count — that would make the
#: artifact-vs-issue comparison in ``run_check`` meaningless in the other
#: direction.
_NUMBERED_CRITERION_RE = re.compile(r"^\d+\.\s")
_GIVEN_WHEN_THEN_CRITERION_RE = re.compile(r"^-\s+GIVEN\b")

#: ADR-093: a query that cannot answer must not return a value that means
#: something else. These two reasons are kept textually distinct so
#: ``run_check``'s message never conflates "the section was never there"
#: with "the section is there and nothing under it parsed" — the second is
#: what silently misled a prior session into hunting for a missing heading.
_NO_SECTION_REASON = "no 'Acceptance criteria' section found"
_UNPARSEABLE_SECTION_REASON = (
    "Acceptance criteria section found but no criteria recognised, expected "
    "`- GIVEN ... WHEN ... THEN` or `1.`"
)
_GH_UNAVAILABLE_REASON = "gh unavailable, unauthenticated, timed out, or the issue body is empty"


def _parse_acceptance_section(body: str) -> tuple[int | None, str | None]:
    """Count acceptance criteria in an issue body's "Acceptance criteria" section.

    Recognises both shapes side by side: a numbered list (``1.``, ``2.``, ...)
    and a GIVEN/WHEN/THEN bullet (``- GIVEN ...``). Returns ``(count, None)``
    when at least one criterion parses. Returns ``(None, reason)`` when it
    cannot answer, with ``reason`` distinguishing "the section was never
    found" from "the section was found but nothing under it matched" —
    conflating the two into one message is exactly the defect this exists to
    fix (#1879).
    """
    lines = body.split("\n")
    in_acceptance = False
    section_found = False
    criteria_count = 0

    for line in lines:
        # Check for "Acceptance criteria" header
        if "acceptance criteria" in line.lower():
            in_acceptance = True
            section_found = True
            continue

        # If we hit another section header, stop
        if in_acceptance and line.strip() and line.startswith("#"):
            break

        if not in_acceptance:
            continue

        # Count numbered list items (1., 2., etc.) and GIVEN/WHEN/THEN
        # bullets side by side. A plain "- " bullet that is not GIVEN/.../
        # or a continuation line like "Observable at:" never matches either
        # pattern, so it never counts.
        if _NUMBERED_CRITERION_RE.match(line) or _GIVEN_WHEN_THEN_CRITERION_RE.match(line):
            criteria_count += 1

    if not section_found:
        return None, _NO_SECTION_REASON
    if criteria_count == 0:
        return None, _UNPARSEABLE_SECTION_REASON
    return criteria_count, None


def _fetch_issue_body(issue: int) -> str | None:
    """The one subprocess boundary: fetch an issue's raw body via ``gh``.

    Returns ``None`` on any failure to fetch (missing binary, non-zero exit,
    timeout, empty body) — never raises.
    """
    try:
        result = subprocess.run(
            ["gh", "issue", "view", str(issue), "--json", "body", "-q", ".body"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        return result.stdout or None
    except Exception:
        return None


def _criteria_count_from_gh(issue: int) -> int | None:
    """Production's only source: parse the issue body via ``gh``.

    Parses the "Acceptance criteria" section, matching numbered list items
    and GIVEN/WHEN/THEN bullets side by side. Returns the count, or ``None``
    if the body cannot be fetched or nothing recognisable parses.
    """
    body = _fetch_issue_body(issue)
    if body is None:
        return None
    count, _reason = _parse_acceptance_section(body)
    return count


def _criteria_count_unavailable_reason(issue: int) -> str:
    """Best-effort detail for *why* the count could not be read.

    Used only to make ``run_check``'s failure message name the real cause
    (ADR-093) — never consulted for the pass/fail decision itself, which
    rests solely on ``extract_criteria_count_from_issue_body``'s return
    value (the "never a third outcome" lock). Re-fetches the body — a second
    ``gh`` call, on the failure path only — because ``run_check`` must keep
    calling ``extract_criteria_count_from_issue_body`` as the single source
    of truth for the count, so the existing override/test seam on that
    function stays exactly what it was.
    """
    if _criteria_count_from_override(issue) is not None:
        # Unreachable in practice: an override means a count existed, so
        # extract_criteria_count_from_issue_body would not have returned
        # None in the first place. Kept for exhaustiveness, not tested.
        return _GH_UNAVAILABLE_REASON
    body = _fetch_issue_body(issue)
    if body is None:
        return _GH_UNAVAILABLE_REASON
    _, reason = _parse_acceptance_section(body)
    return reason or _GH_UNAVAILABLE_REASON


def extract_criteria_count_from_issue_body(issue: int) -> int | None:
    """Resolve the acceptance-criteria-count fact this gate needs.

    Checks the harness's injected provider first (scoped to the exact issue),
    then falls back to the real ``gh`` lookup — the only source in
    production. Never a third outcome: this either returns a real count or
    ``None``, and ``run_check`` fails closed on ``None`` (Architect lock 2).
    The seam must never become a way to make the gate green by withholding
    the fact — the override supplies a *count*, not a bypass, so a caller
    that registers no provider gets exactly the ``gh``-unavailable behaviour
    it always had.
    """
    override = _criteria_count_from_override(issue)
    if override is not None:
        return override
    return _criteria_count_from_gh(issue)


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:
    review = load_review_artifact(issue)
    if review is None:
        return False, "Review artifact missing", {}

    acceptance = review.get("testCoverage", {}).get("acceptance", {})
    total = acceptance.get("total", 0)
    mapped = acceptance.get("mapped", 0)
    mappings = acceptance.get("mappings", [])
    unmapped = acceptance.get("unmapped", [])

    problems: list[str] = []

    # AC3: Compare artifact total against issue body criteria count (#1732)
    issue_criteria_count = extract_criteria_count_from_issue_body(issue)
    if issue_criteria_count is None:
        # Architect lock 2: a check must never pass because it could not
        # determine an answer. The whole point of reading the issue is that the
        # count comes from somewhere the graded agent cannot write; if that
        # source is unreachable, the artifact's own number is the only one left,
        # which is the self-referential comparison this check exists to replace.
        reason = _criteria_count_unavailable_reason(issue)
        problems.append(
            f"cannot read the acceptance-criteria count for issue {issue} from its body "
            f"({reason}), so the artifact's total cannot be checked against a source "
            "the agent does not control; failing closed rather than accepting it"
        )
    elif total != issue_criteria_count:
        problems.append(
            f"acceptance total ({total}) != criteria count from issue ({issue_criteria_count})"
        )

    if total != mapped:
        problems.append(f"total ({total}) != mapped ({mapped})")
    if unmapped:
        problems.append(f"unmapped: {unmapped}")
    if len(mappings) != total:
        problems.append(f"mappings length ({len(mappings)}) != total ({total})")

    for entry in mappings:
        node = entry.get("test", "")
        criterion = entry.get("criterion", "")
        if not pytest_node_exists(node):
            problems.append(f"test not found: {node}")
            continue
        test_name = node.rsplit("::", 1)[-1]
        if not criterion_matches_test(criterion, test_name):
            problems.append(f"criterion/test name mismatch: {criterion!r} -> {test_name}")

    details: dict[str, Any] = {
        "total": total,
        "mapped": mapped,
        "unmapped": unmapped,
        "problems": problems,
    }
    if issue_criteria_count is not None:
        details["issue_criteria_count"] = issue_criteria_count

    if problems:
        return False, "Acceptance criteria mapping invalid", details
    return True, "All acceptance criteria mapped to tests", details


def main() -> int:
    args = parse_args("Validate acceptance criteria mapping")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, description, details = run_check(issue)
    detail = ""
    if not passed and details.get("problems"):
        detail = "; ".join(details["problems"][:3])
    return print_check_result("acceptance_criteria_mapped", passed, detail)


if __name__ == "__main__":
    raise SystemExit(main())
