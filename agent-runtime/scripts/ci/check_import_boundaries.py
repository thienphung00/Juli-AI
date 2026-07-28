#!/usr/bin/env python3
"""AST import boundary checker for modular monolith packages (#552 / MMU-2)."""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO_ROOT, print_check_result  # noqa: E402
from import_boundary_config import ImportBoundaryConfig, load_import_boundary_config  # noqa: E402


@dataclass(frozen=True)
class ImportViolation:
    kind: str
    importer_file: str
    importer_package: str
    target_module: str
    target_package: str
    message: str


def _module_prefix(config: ImportBoundaryConfig) -> str:
    return f"{config.root_package}."


def top_level_package(module_name: str, config: ImportBoundaryConfig) -> str | None:
    prefix = _module_prefix(config)
    if not module_name.startswith(prefix):
        return None
    rest = module_name.removeprefix(prefix)
    if not rest:
        return None
    return rest.split(".")[0]


def package_depth(module_name: str, config: ImportBoundaryConfig) -> int:
    prefix = _module_prefix(config)
    if not module_name.startswith(prefix):
        return 0
    rest = module_name.removeprefix(prefix)
    return len([segment for segment in rest.split(".") if segment])


def top_level_from_file(py_file: Path, scan_root: Path, config: ImportBoundaryConfig) -> str | None:
    try:
        rel = py_file.relative_to(scan_root)
    except ValueError:
        return None
    parts = rel.parts
    if not parts or parts[-1] == "__init__.py":
        if len(parts) < 2:
            return parts[0] if parts else None
        return parts[0]
    return parts[0]


def iter_python_files(scan_root: Path) -> list[Path]:
    if not scan_root.exists():
        return []
    return sorted(path for path in scan_root.rglob("*.py") if path.is_file())


def imported_modules(tree: ast.AST, config: ImportBoundaryConfig) -> list[str]:
    prefix = _module_prefix(config)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(prefix):
                    modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(prefix):
                modules.append(node.module)
    return modules


def check_import(
    *,
    importer_file: str,
    importer_package: str,
    target_module: str,
    config: ImportBoundaryConfig,
) -> ImportViolation | None:
    target_package = top_level_package(target_module, config)
    if target_package is None:
        return None
    if importer_package not in config.top_level_packages:
        return None
    if target_package not in config.top_level_packages:
        return None
    if importer_package == target_package:
        return None

    allowed_targets = config.allowed_edges.get(importer_package, frozenset())
    if target_package not in allowed_targets:
        return ImportViolation(
            kind="forbidden_edge",
            importer_file=importer_file,
            importer_package=importer_package,
            target_module=target_module,
            target_package=target_package,
            message=(
                f"{importer_file}: package '{importer_package}' must not import "
                f"'{target_module}' (forbidden edge to '{target_package}')"
            ),
        )

    depth = package_depth(target_module, config)
    if depth > config.max_cross_package_depth:
        return ImportViolation(
            kind="deep_import",
            importer_file=importer_file,
            importer_package=importer_package,
            target_module=target_module,
            target_package=target_package,
            message=(
                f"{importer_file}: package '{importer_package}' must not deep-import "
                f"'{target_module}' (cross-package depth {depth} > "
                f"{config.max_cross_package_depth}; use public package root)"
            ),
        )
    return None


def collect_violations(
    scan_root: Path,
    config: ImportBoundaryConfig,
    *,
    repo_root: Path = REPO_ROOT,
) -> list[ImportViolation]:
    violations: list[ImportViolation] = []
    resolved_root = scan_root.resolve()
    resolved_repo = repo_root.resolve()
    for py_file in iter_python_files(resolved_root):
        rel_file = py_file.resolve().relative_to(resolved_repo).as_posix()
        importer_package = top_level_from_file(py_file.resolve(), resolved_root, config)
        if not importer_package:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except SyntaxError:
            continue
        for target_module in imported_modules(tree, config):
            violation = check_import(
                importer_file=rel_file,
                importer_package=importer_package,
                target_module=target_module,
                config=config,
            )
            if violation:
                violations.append(violation)
    return violations


def run_check(
    *,
    config_path: Path | None = None,
    scan_root: Path | None = None,
    strict: bool = False,
) -> tuple[bool, str, list[ImportViolation]]:
    config = load_import_boundary_config(config_path)
    root = (scan_root or config.scan_root).resolve()
    violations = collect_violations(root, config)
    if not violations:
        return True, "Import boundaries respected", violations
    detail = f"{len(violations)} violation(s); first: {violations[0].message}"
    if strict:
        return False, detail, violations
    return True, f"WARN — {detail}", violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / ".importlinter.toml",
        help="Path to import boundary contract TOML",
    )
    parser.add_argument(
        "--scan-root",
        type=Path,
        default=None,
        help="Directory root to scan (defaults to contract scan_root)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when violations are found (PR gate mode)",
    )
    args = parser.parse_args()

    passed, detail, violations = run_check(
        config_path=args.config,
        scan_root=args.scan_root,
        strict=args.strict,
    )
    if violations and not args.strict:
        for violation in violations[:10]:
            print(f"import_boundaries: WARN — {violation.message}", file=sys.stderr)
        if len(violations) > 10:
            print(
                f"import_boundaries: WARN — … and {len(violations) - 10} more",
                file=sys.stderr,
            )
    return print_check_result("import_boundaries", passed, detail)


if __name__ == "__main__":
    raise SystemExit(main())
