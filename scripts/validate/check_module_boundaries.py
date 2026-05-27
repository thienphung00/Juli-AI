#!/usr/bin/env python3
"""Gate: no illegal cross-module imports or dependency cycles."""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ci"))
from common import (  # noqa: E402
    REPO_ROOT,
    collect_import_graph,
    git_changed_files,
    module_for_file,
    parse_architecture_map,
    parse_args,
    parse_module_md_public_symbols,
    print_check_result,
    resolve_import_to_module,
    resolve_issue_number,
    tarjan_scc,
)


def violations_in_files(py_files: list[Path], modules: dict) -> list[dict]:
    violations: list[dict] = []
    for py_file in py_files:
        rel = py_file.relative_to(REPO_ROOT).as_posix()
        owner = module_for_file(rel, modules)
        if not owner:
            continue
        allowed = parse_module_md_public_symbols(REPO_ROOT / owner / "MODULE.md")
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith("src."):
                continue
            target = resolve_import_to_module(node.module, modules)
            if not target or target == owner:
                continue
            importee_allowed = parse_module_md_public_symbols(REPO_ROOT / target / "MODULE.md")
            for alias in node.names:
                name = alias.name
                if name == "*":
                    violations.append(
                        {"file": rel, "from": owner, "imports": target, "symbol": "*"}
                    )
                elif name not in importee_allowed and name not in allowed:
                    violations.append(
                        {"file": rel, "from": owner, "imports": target, "symbol": name}
                    )
    return violations


def run_check(issue: int) -> tuple[bool, str, dict[str, Any]]:  # noqa: ARG001
    modules = parse_architecture_map()
    graph = collect_import_graph(modules)
    cycles = [c for c in tarjan_scc(graph) if len(c) > 1]

    changed = git_changed_files()
    py_files = [
        REPO_ROOT / path
        for path in changed
        if path.endswith(".py") and path.startswith("src/")
    ]
    touched_modules = {module_for_file(p.relative_to(REPO_ROOT).as_posix(), modules) for p in py_files}
    touched_modules.discard(None)

    violations = violations_in_files(py_files, modules)
    warn_many_modules = len(touched_modules) > 3

    details: dict[str, Any] = {
        "violations": violations,
        "cycles": cycles,
        "modulesTouched": len(touched_modules),
        "warning": "More than 3 modules touched" if warn_many_modules else None,
    }

    if cycles:
        return False, "Module dependency cycle detected", details
    if violations:
        return False, "Cross-module import outside public surface", details
    return True, "Module boundaries respected", details


def main() -> int:
    args = parse_args("Validate module boundaries")
    issue = resolve_issue_number(args.issue)
    if issue is None:
        print("error: issue number required", file=sys.stderr)
        return 1
    passed, _, details = run_check(issue)
    detail = ""
    if details.get("violations"):
        detail = f"{len(details['violations'])} import violations"
    elif details.get("cycles"):
        detail = f"{len(details['cycles'])} cycles"
    return print_check_result("module_boundaries", passed, detail)


if __name__ == "__main__":
    raise SystemExit(main())
