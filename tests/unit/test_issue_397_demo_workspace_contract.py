"""Contract tests for the Phase 2.6 Demo workspace foundation."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_PACKAGES = (
    ROOT / "apps" / "demo",
    ROOT / "packages" / "theme",
    ROOT / "packages" / "ui",
    ROOT / "packages" / "utils",
)
SOURCE_EXTENSIONS = {".js", ".jsx", ".mjs", ".ts", ".tsx"}


def _package_json(path: Path) -> dict[str, object]:
    return json.loads((path / "package.json").read_text(encoding="utf-8"))


def _source_files(path: Path) -> list[Path]:
    return [
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file()
        and candidate.suffix in SOURCE_EXTENSIONS
        and "node_modules" not in candidate.parts
        and ".next" not in candidate.parts
        and "e2e" not in candidate.parts
        and candidate.name != "playwright.config.ts"
    ]


def _declared_dependencies(package: dict[str, object]) -> set[str]:
    dependencies: set[str] = set()
    for field in ("dependencies", "devDependencies", "peerDependencies"):
        values = package.get(field)
        if isinstance(values, dict):
            dependencies.update(str(name) for name in values)
    return dependencies


def _contains_cycle(graph: dict[str, set[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(neighbor) for neighbor in graph[node]):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def test_root_declares_real_pnpm_turbo_workspace() -> None:
    root_package = _package_json(ROOT)

    assert str(root_package["packageManager"]).startswith("pnpm@10.")
    assert (ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8") == (
        "packages:\n  - \"apps/*\"\n  - \"packages/*\"\n"
    )
    assert (ROOT / "turbo.json").is_file()
    assert {"lint", "type-check", "test", "build"} <= set(
        root_package["scripts"]  # type: ignore[arg-type]
    )


def test_demo_and_shared_packages_expose_documented_public_surfaces() -> None:
    for package_path in WORKSPACE_PACKAGES:
        package = _package_json(package_path)
        assert package["private"] is True
        assert (package_path / "MODULE.md").is_file()

    demo = _package_json(ROOT / "apps" / "demo")
    assert {"lint", "type-check", "test", "build"} <= set(
        demo["scripts"]  # type: ignore[arg-type]
    )


def test_demo_is_private_app_router_typescript_tailwind_app() -> None:
    demo_root = ROOT / "apps" / "demo"
    demo = _package_json(demo_root)
    globals_css = (demo_root / "src/app/globals.css").read_text(encoding="utf-8")

    assert demo["private"] is True
    assert "next" in demo["dependencies"]  # type: ignore[operator]
    assert (demo_root / "src/app/layout.tsx").is_file()
    assert (demo_root / "src/app/page.tsx").is_file()
    assert (demo_root / "tsconfig.json").is_file()
    assert '@import "tailwindcss";' in globals_css


def test_four_destinations_and_exactly_two_safe_home_launchers() -> None:
    demo_root = ROOT / "apps" / "demo" / "src"
    fixtures = (demo_root / "lib/mock-data.ts").read_text(encoding="utf-8")
    home = (demo_root / "app/page.tsx").read_text(encoding="utf-8")

    for route in ('"/"', '"/decisions"', '"/analytics"', '"/settings"'):
        assert route in fixtures
    assert fixtures.count("...decisionsDestination") == 1
    assert fixtures.count("...analyticsDestination") == 1
    assert "homeDestinations.map" in home
    assert not re.search(r"Phê duyệt|Từ chối|Mẫu quy trình|Ngưỡng|ROAS|CSAT", home)


def test_theme_and_shared_home_primitives_are_consumed_by_demo() -> None:
    demo_root = ROOT / "apps" / "demo" / "src"
    globals_css = (demo_root / "app/globals.css").read_text(encoding="utf-8")
    home = (demo_root / "app/page.tsx").read_text(encoding="utf-8")

    assert '@import "@juli/theme/tokens.css";' in globals_css
    assert '@import "@juli/ui/styles.css";' in globals_css
    assert 'from "@juli/ui"' in home
    assert 'from "@juli/utils"' in home


def test_shared_formatters_and_mock_fixtures_run_without_network() -> None:
    root_scripts = _package_json(ROOT)["scripts"]
    home_test = (
        ROOT / "apps/demo/src/__tests__/home.test.tsx"
    ).read_text(encoding="utf-8")

    assert "pnpm --filter @juli/utils test" in root_scripts["check:demo"]  # type: ignore[index]
    assert (ROOT / "packages/utils/src/index.test.ts").is_file()
    assert "expect(fetchSpy).not.toHaveBeenCalled()" in home_test


def test_demo_ci_independently_installs_lints_typechecks_tests_and_builds() -> None:
    workflow = (ROOT / ".github/workflows/pr.yml").read_text(encoding="utf-8")
    root_scripts = _package_json(ROOT)["scripts"]

    assert "pnpm install --frozen-lockfile --filter @juli/demo..." in workflow
    assert "pnpm check:demo" in workflow
    check_demo = root_scripts["check:demo"]  # type: ignore[index]
    for task in ("lint:demo", "type-check:demo", "test:demo", "build:demo"):
        assert task in check_demo


def test_home_responsive_focus_touch_vietnamese_and_reduced_motion_contract() -> None:
    globals_css = (ROOT / "apps/demo/src/app/globals.css").read_text(encoding="utf-8")
    ui_css = (ROOT / "packages/ui/styles.css").read_text(encoding="utf-8")
    tokens_css = (ROOT / "packages/theme/tokens.css").read_text(encoding="utf-8")
    home = (ROOT / "apps/demo/src/app/page.tsx").read_text(encoding="utf-8")
    fixtures = (ROOT / "apps/demo/src/lib/mock-data.ts").read_text(encoding="utf-8")

    assert "@media (min-width: 42rem)" in globals_css
    assert "@media (min-width: 56rem)" in globals_css
    assert ":focus-visible" in globals_css
    assert ":focus-visible" in ui_css
    assert "--juli-touch-target: 44px" in tokens_css
    assert "@media (prefers-reduced-motion: reduce)" in globals_css
    assert "Bạn muốn làm gì tiếp theo?" in home
    assert "Quyết định" in fixtures and "Phân tích" in fixtures


def test_workspace_import_boundaries_are_acyclic_and_app_isolated() -> None:
    import_pattern = re.compile(
        r"""(?:from\s+|import\s*\(|require\s*\()\s*["'](?P<path>[^"']+)"""
    )
    app_paths = {
        str(_package_json(path)["name"]): path.resolve()
        for path in ROOT.glob("apps/*")
        if (path / "package.json").is_file()
    }
    package_paths = {
        str(_package_json(path)["name"]): path.resolve()
        for path in ROOT.glob("packages/*")
        if (path / "package.json").is_file()
    }

    package_graph: dict[str, set[str]] = {}
    for package_name, package_path in package_paths.items():
        dependencies = _declared_dependencies(_package_json(package_path))
        assert dependencies.isdisjoint(app_paths), (
            f"{package_path.relative_to(ROOT)}/package.json depends on an app"
        )
        package_graph[package_name] = dependencies.intersection(package_paths)
        for source_file in _source_files(package_path):
            imports = import_pattern.findall(source_file.read_text(encoding="utf-8"))
            for value in imports:
                relative_target = (
                    (source_file.parent / value).resolve()
                    if value.startswith(".")
                    else None
                )
                assert value not in app_paths and not any(
                    relative_target is not None
                    and relative_target.is_relative_to(app_path)
                    for app_path in app_paths.values()
                ), f"{source_file.relative_to(ROOT)} imports an app"

    assert not _contains_cycle(package_graph), "shared package dependency cycle detected"

    for app_name, app_path in app_paths.items():
        sibling_paths = {
            name: path for name, path in app_paths.items() if name != app_name
        }
        for source_file in _source_files(app_path):
            imports = import_pattern.findall(source_file.read_text(encoding="utf-8"))
            for value in imports:
                relative_target = (
                    (source_file.parent / value).resolve()
                    if value.startswith(".")
                    else None
                )
                assert value not in sibling_paths and not any(
                    relative_target is not None
                    and relative_target.is_relative_to(sibling_path)
                    for sibling_path in sibling_paths.values()
                ), f"{source_file.relative_to(ROOT)} imports a sibling app"


def test_demo_source_has_no_backend_or_secret_environment_dependency() -> None:
    forbidden = re.compile(
        r"(NEXT_PUBLIC_API_URL|DATABASE_URL|TIKTOK_|SUPABASE_|process\.env)"
    )
    sources = _source_files(ROOT / "apps" / "demo")

    assert sources
    for source_file in sources:
        content = source_file.read_text(encoding="utf-8")
        assert not forbidden.search(content), source_file.relative_to(ROOT)
