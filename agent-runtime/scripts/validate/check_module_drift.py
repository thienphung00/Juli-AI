#!/usr/bin/env python3
"""Gate: MODULE.md public symbols match code for touched Tier 1/2 modules."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    REPO_ROOT,
    git_changed_files,
    module_for_file,
    module_public_symbols_from_code,
    parse_architecture_map,
    parse_args,
    parse_module_md_public_symbols,
    print_check_result,
    resolve_issue_number,
)


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:  # noqa: ARG001
    modules = parse_architecture_map()
    changed = git_changed_files()
    touched: set[str] = set()
    for path in changed:
        mod = module_for_file(path, modules)
        if mod:
            touched.add(mod)
    drift: list[dict] = []
    for module_path in sorted(touched):
        info = modules.get(module_path)
        if not info or info.tier >= 3:
            continue
        module_md = REPO_ROOT / module_path / "MODULE.md"
        if not module_md.exists():
            drift.append({"module": module_path, "error": "MODULE.md missing"})
            continue
        documented = parse_module_md_public_symbols(module_md)
        actual = module_public_symbols_from_code(module_path)
        missing = sorted(actual - documented)
        orphans = sorted(documented - actual)
        if missing or orphans:
            drift.append(
                {
                    "module": module_path,
                    "missingInModuleMd": missing,
                    "orphanInModuleMd": orphans,
                }
            )

    details = {"drift": drift, "missingInterfaces": [d.get("missingInModuleMd", []) for d in drift]}
    if drift:
        return False, "MODULE.md drift detected", details
    return True, "MODULE.md in sync for touched modules", details


def main() -> int:
    args = parse_args("Validate MODULE.md drift")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, _, details = run_check(issue)
    detail = ""
    if details.get("drift"):
        detail = f"{len(details['drift'])} module(s) out of sync"
    return print_check_result("module_md_sync", passed, detail)


if __name__ == "__main__":
    raise SystemExit(main())
