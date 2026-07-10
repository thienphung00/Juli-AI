"""Doc and config contract tests for Phase 3 frontend consolidation.

Phase 3 moves the legacy ``web/`` Next.js app to ``apps/dashboard/`` and
decommissions the unused pnpm/Turborepo workspace scaffolding from Phase 2.5-b.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_PKG = REPO_ROOT / "apps/dashboard/package.json"
ROOT_PACKAGE_PATH = REPO_ROOT / "package.json"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_pnpm_workspace_removed():
    """pnpm workspace config is decommissioned in favor of npm in apps/dashboard."""
    assert not (REPO_ROOT / "pnpm-workspace.yaml").is_file()
    assert not (REPO_ROOT / "pnpm-lock.yaml").is_file()


def test_turbo_json_removed():
    """Turborepo skeleton is removed — no turbo.json at repo root."""
    assert not (REPO_ROOT / "turbo.json").is_file()


def test_dashboard_app_has_runtime_package():
    """The real Next.js dashboard lives at apps/dashboard with build/test scripts."""
    assert DASHBOARD_PKG.is_file(), "apps/dashboard/package.json is required"
    scripts = _read_json(DASHBOARD_PKG).get("scripts") or {}
    for task in ("build", "test", "lint", "type-check"):
        assert task in scripts, f"missing npm script: {task}"


def test_removed_scaffold_apps_have_no_package_manifests():
    """demo, landing, and mobile scaffolds are removed."""
    for app in ("demo", "landing", "mobile"):
        assert not (REPO_ROOT / "apps" / app).exists(), f"apps/{app} should be removed"


def test_removed_package_scaffolds_have_no_manifests():
    """Empty packages/* workspace members are removed."""
    packages_dir = REPO_ROOT / "packages"
    if packages_dir.exists():
        manifests = list(packages_dir.rglob("package.json"))
        assert not manifests, f"unexpected package scaffolds: {manifests}"


def test_root_package_uses_npm_for_tooling_only():
    """Root package.json keeps playwright/screenshots scripts without pnpm or turbo."""
    root = _read_json(ROOT_PACKAGE_PATH)
    assert "packageManager" not in root
    scripts = root.get("scripts") or {}
    assert "workspace:baseline" not in scripts
    assert "screenshots" in scripts
    dev_deps = root.get("devDependencies") or {}
    assert "turbo" not in dev_deps
