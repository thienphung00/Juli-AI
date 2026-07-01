"""Doc and config contract tests for Phase 2.5-b workspace tooling (Issue #251)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PHASE_25_PATH = REPO_ROOT / "docs/phases/phase-2.5-deployment.md"
MIGRATION_PLAN_PATH = REPO_ROOT / "docs/architecture/migration-plan.md"
PNPM_WORKSPACE_PATH = REPO_ROOT / "pnpm-workspace.yaml"
TURBO_PATH = REPO_ROOT / "turbo.json"
ROOT_PACKAGE_PATH = REPO_ROOT / "package.json"

APP_SCOPES = ("landing", "demo", "dashboard", "mobile")
PACKAGE_SCOPES = (
    "ui",
    "theme",
    "icons",
    "illustrations",
    "api-client",
    "types",
    "utils",
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture
def phase_25_text() -> str:
    return PHASE_25_PATH.read_text(encoding="utf-8")


@pytest.fixture
def migration_plan_text() -> str:
    return MIGRATION_PLAN_PATH.read_text(encoding="utf-8")


def test_pnpm_workspace_recognizes_apps_and_packages():
    """Workspace config includes top-level apps/* and packages/* globs."""
    assert PNPM_WORKSPACE_PATH.is_file(), "pnpm-workspace.yaml is required"
    workspace = _read_yaml(PNPM_WORKSPACE_PATH)
    packages = workspace.get("packages") or []
    assert "apps/*" in packages
    assert "packages/*" in packages


def test_pnpm_workspace_includes_legacy_web():
    """Legacy web/ remains a workspace member without moving runtime code."""
    workspace = _read_yaml(PNPM_WORKSPACE_PATH)
    packages = workspace.get("packages") or []
    assert "web" in packages


def test_turbo_json_defines_baseline_tasks():
    """Turborepo skeleton exposes lint, type-check, test, and build tasks."""
    assert TURBO_PATH.is_file(), "turbo.json is required"
    turbo = _read_json(TURBO_PATH)
    tasks = turbo.get("tasks") or {}
    for task in ("lint", "type-check", "test", "build"):
        assert task in tasks, f"missing turbo task: {task}"


def test_scaffold_workspace_members_are_private_placeholders():
    """README-only apps/packages register as private workspace members without publish surface."""
    problems: list[str] = []
    for app in APP_SCOPES:
        pkg_path = REPO_ROOT / "apps" / app / "package.json"
        if not pkg_path.is_file():
            problems.append(f"missing apps/{app}/package.json")
            continue
        manifest = _read_json(pkg_path)
        if manifest.get("private") is not True:
            problems.append(f"apps/{app}/package.json must set private: true")
        if manifest.get("publishConfig"):
            problems.append(f"apps/{app}/package.json must not define publishConfig")
        for field in ("main", "module", "exports", "types"):
            if field in manifest:
                problems.append(f"apps/{app}/package.json must not define {field}")

    for pkg in PACKAGE_SCOPES:
        pkg_path = REPO_ROOT / "packages" / pkg / "package.json"
        if not pkg_path.is_file():
            problems.append(f"missing packages/{pkg}/package.json")
            continue
        manifest = _read_json(pkg_path)
        if manifest.get("private") is not True:
            problems.append(f"packages/{pkg}/package.json must set private: true")
        if manifest.get("publishConfig"):
            problems.append(f"packages/{pkg}/package.json must not define publishConfig")
        for field in ("main", "module", "exports", "types"):
            if field in manifest:
                problems.append(f"packages/{pkg}/package.json must not define {field}")

    assert not problems, "; ".join(problems)


def test_legacy_web_npm_workflow_documented(phase_25_text: str):
    """Existing web/ build/test workflow still passes from its current location."""
    web_pkg = REPO_ROOT / "web" / "package.json"
    assert web_pkg.is_file()
    scripts = _read_json(web_pkg).get("scripts") or {}
    assert "build" in scripts
    assert "test" in scripts
    assert "npm ci" in phase_25_text
    assert "web/" in phase_25_text


def test_no_landing_demo_implementation_in_workspace_slice():
    """No shared package extraction or landing/demo implementation is included."""
    forbidden_suffixes = (".tsx", ".ts", ".jsx", ".js", ".vue", ".svelte")
    for app in APP_SCOPES:
        app_dir = REPO_ROOT / "apps" / app
        runtime_files = [
            path
            for path in app_dir.rglob("*")
            if path.is_file()
            and path.name != "package.json"
            and path.suffix in forbidden_suffixes
        ]
        assert not runtime_files, f"unexpected runtime files in apps/{app}: {runtime_files}"


def test_scaffold_readme_only_members_do_not_publish():
    """README-only product/package folders do not publish packages."""
    problems: list[str] = []
    for rel in [*(f"apps/{a}/package.json" for a in APP_SCOPES), *(f"packages/{p}/package.json" for p in PACKAGE_SCOPES)]:
        manifest = _read_json(REPO_ROOT / rel)
        if manifest.get("private") is not True:
            problems.append(f"{rel} must be private")
        if manifest.get("publishConfig"):
            problems.append(f"{rel} must not publish")
    assert not problems, "; ".join(problems)


def test_scaffold_packages_have_no_workspace_dependencies():
    """Scaffold members do not declare fake imports to sibling apps or packages."""
    problems: list[str] = []
    for rel in [*(f"apps/{a}/package.json" for a in APP_SCOPES), *(f"packages/{p}/package.json" for p in PACKAGE_SCOPES)]:
        manifest = _read_json(REPO_ROOT / rel)
        deps = manifest.get("dependencies") or {}
        dev_deps = manifest.get("devDependencies") or {}
        for dep in {**deps, **dev_deps}:
            if dep.startswith("@juli/"):
                problems.append(f"{rel} must not depend on {dep}")
    assert not problems, "; ".join(problems)


def test_workspace_baseline_command_documented(phase_25_text: str):
    """Developers can find the command that validates the workspace baseline."""
    assert "workspace:baseline" in phase_25_text
    assert "pnpm" in phase_25_text


def test_migration_plan_records_2_5_b_workspace_gate(migration_plan_text: str):
    """Migration plan names the 2.5-b workspace tooling slice."""
    assert "2.5-b" in migration_plan_text
    assert "pnpm" in migration_plan_text.lower() or "workspace" in migration_plan_text.lower()


def test_root_package_exposes_workspace_baseline_script():
    """Root package.json wires the documented workspace baseline script."""
    root = _read_json(ROOT_PACKAGE_PATH)
    scripts = root.get("scripts") or {}
    assert "workspace:baseline" in scripts
    assert "turbo" in scripts["workspace:baseline"]
