#!/usr/bin/env python3
"""Report review vs validation artifact coverage and status semantics gaps."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    REVIEWS_DIR,
    VALIDATION_DIR,
    review_status_issues,
    utc_now_iso,
    write_json,
)


def collect_coverage() -> dict:
    review_files = sorted(REVIEWS_DIR.glob("review-issue-*.json"))
    validation_issues = {
        p.stem.replace("validation-issue-", "")
        for p in VALIDATION_DIR.glob("validation-issue-*.json")
    }

    status_counts: dict[str, int] = {}
    semantic_issues: list[dict[str, str]] = []
    missing_validation: list[str] = []

    for path in review_files:
        issue = path.stem.replace("review-issue-", "")
        data = json.loads(path.read_text(encoding="utf-8"))
        status = data.get("status") or "MISSING"
        status_counts[status] = status_counts.get(status, 0) + 1

        issues = review_status_issues(data)
        if issues:
            semantic_issues.append({"issue": issue, "detail": issues[0]})

        if issue not in validation_issues:
            missing_validation.append(issue)

    total_reviews = len(review_files)
    validated = total_reviews - len(missing_validation)
    coverage_pct = round((validated / total_reviews * 100) if total_reviews else 0.0, 1)

    return {
        "totalReviews": total_reviews,
        "totalValidations": validated,
        "coveragePercent": coverage_pct,
        "ungatedCount": len(missing_validation),
        "ungatedIssues": missing_validation,
        "statusCounts": status_counts,
        "semanticIssueCount": len(semantic_issues),
        "semanticIssues": semantic_issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--json", action="store_true", help="Write audit JSON artifact")
    args = parser.parse_args()

    report = collect_coverage()

    print("=== Pipeline Coverage ===")
    print(f"Reviews: {report['totalReviews']}")
    print(f"Validations: {report['totalValidations']} ({report['coveragePercent']}% coverage)")
    print(f"Ungated (review only): {report['ungatedCount']}")
    print()
    print("Review status distribution:")
    for status, count in sorted(report["statusCounts"].items()):
        print(f"  {status}: {count}")
    print()
    print(f"Status semantics issues: {report['semanticIssueCount']}")
    for item in report["semanticIssues"][:20]:
        print(f"  #{item['issue']}: {item['detail']}")
    if report["semanticIssueCount"] > 20:
        print(f"  ... and {report['semanticIssueCount'] - 20} more")
    if report["ungatedIssues"]:
        print()
        print("Issues without validation artifact:")
        print("  " + ", ".join(f"#{n}" for n in report["ungatedIssues"][:30]))
        if len(report["ungatedIssues"]) > 30:
            print(f"  ... and {len(report['ungatedIssues']) - 30} more")

    if args.json:
        payload = {
            "id": f"audit-pipeline-coverage-{args.date}",
            "timestamp": utc_now_iso(),
            "severity": "CRITICAL" if report["semanticIssueCount"] else "WARNING" if report["ungatedCount"] else "OK",
            **report,
        }
        out = VALIDATION_DIR / f"audit-pipeline-coverage-{args.date}.json"
        write_json(out, payload)
        print(f"\nwrote {out}")

    if report["semanticIssueCount"] or report["ungatedCount"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
