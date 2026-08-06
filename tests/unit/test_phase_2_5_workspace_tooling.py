"""Workspace transition contracts across Phase 2.5 and Phase 2.6.

Phase 2.5 left ``apps/dashboard`` independently npm-buildable. Phase 2.6
reintroduces the root pnpm/Turborepo workspace for the new Demo and shared
packages without changing that dashboard build contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.phase_scaffold


REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_PKG = REPO_ROOT / "apps/dashboard/package.json"
ROOT_PACKAGE_PATH = REPO_ROOT / "package.json"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_phase_2_6_restores_root_workspace_without_removing_dashboard_npm_lock():
    """New workspace tooling coexists with the independently built dashboard."""
    assert (REPO_ROOT / "pnpm-workspace.yaml").is_file()
    assert (REPO_ROOT / "pnpm-lock.yaml").is_file()
    assert (REPO_ROOT / "turbo.json").is_file()
    assert not (REPO_ROOT / "package-lock.json").exists()
    assert (REPO_ROOT / "apps/dashboard/package-lock.json").is_file()


def test_dashboard_app_has_runtime_package():
    """The real Next.js dashboard lives at apps/dashboard with build/test scripts."""
    assert DASHBOARD_PKG.is_file(), "apps/dashboard/package.json is required"
    scripts = _read_json(DASHBOARD_PKG).get("scripts") or {}
    for task in ("build", "test", "lint", "type-check"):
        assert task in scripts, f"missing npm script: {task}"


def test_only_phase_gated_apps_are_added():
    """Demo (2.6) and Landing (2.7 PRD) exist; mobile retains its later phase gate."""
    assert (REPO_ROOT / "apps/demo/package.json").is_file()
    assert (REPO_ROOT / "apps/landing/package.json").is_file()
    for deferred_app in ("mobile",):
        assert not (REPO_ROOT / "apps" / deferred_app).exists(), (
            f"apps/{deferred_app} is gated to a later phase"
        )


def test_apps_with_workspace_deps_are_workspace_members():
    """An app depending on ``workspace:*`` must be listed in pnpm-workspace.yaml.

    apps/landing shipped in Phase 2.7 declaring ``@juli/brand``/``@juli/theme``/
    ``@juli/ui`` as ``workspace:*`` but was never added to the workspace globs,
    so ``pnpm install`` skipped it, its dev server could not start from a clean
    checkout, and turbo/CI never ran its tests. apps/dashboard is deliberately
    npm-owned and excluded (see the pnpm-workspace.yaml comment), so it is only
    exempt for as long as it declares no workspace dependency.
    """
    workspace_globs = yaml.safe_load((REPO_ROOT / "pnpm-workspace.yaml").read_text())["packages"]

    for pkg_path in sorted((REPO_ROOT / "apps").glob("*/package.json")):
        pkg = _read_json(pkg_path)
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        if not any(spec.startswith("workspace:") for spec in deps.values()):
            continue
        app_dir = pkg_path.parent.name
        assert f"apps/{app_dir}" in workspace_globs, (
            f"apps/{app_dir} declares workspace:* dependencies but is not a "
            f"pnpm workspace member; pnpm install will skip it"
        )


def test_workspace_packages_are_real_consumed_members():
    """Shared packages are populated and consumed, not empty scaffold directories.

    ``@juli/brand`` joined in Phase 2.7 as the canonical brand asset owner
    (ADR-056).
    """
    package_names = {
        _read_json(path)["name"] for path in (REPO_ROOT / "packages").glob("*/package.json")
    }
    assert package_names == {
        "@juli/brand",
        "@juli/contracts",
        "@juli/theme",
        "@juli/ui",
        "@juli/utils",
    }


def test_root_package_uses_pinned_pnpm_and_turbo_without_losing_screenshots():
    """Root owns workspace orchestration and retains existing screenshot tooling."""
    root = _read_json(ROOT_PACKAGE_PATH)
    assert root["packageManager"].startswith("pnpm@10.")
    scripts = root.get("scripts") or {}
    assert "screenshots" in scripts
    assert "check:demo" in scripts
    dev_deps = root.get("devDependencies") or {}
    assert "turbo" in dev_deps
