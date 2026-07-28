"""MMU-10 (#562): OAuth dual-writer facade contract tests — RED stage.

Enforces a single Auth & Security write owner for ``shops`` and
``tiktok_credentials`` during OAuth connect + token refresh. Tests fail until
competing writers (``persist_oauth_tokens``, callback infrastructure) route
through ``TikTokOAuthService`` or the designated OAuth facade module.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend/src/juli_backend"

OAUTH_FACADE_REL = "core/security/tiktok_oauth.py"
OAUTH_FACADE_MODULE = "juli_backend.core.security.tiktok_oauth"

OAUTH_CONNECT_REFRESH_PATH = (
    "services/tiktok/app_review_store.py",
    "services/tiktok/oauth.py",
    "core/security/tiktok_oauth.py",
    "api/routes/auth_tiktok.py",
)

REPO_WRITE_METHODS = frozenset({"create", "update_tokens"})
REPO_CLASS_NAMES = frozenset({"ShopsRepo", "TikTokCredentialRepo"})
REPO_WRITE_VAR_NAMES = frozenset({"shops_repo", "cred_repo"})

REPO_WRITE_GREP_PATTERNS = (
    re.compile(r"\bShopsRepo\s*\([^)]*\)\.create\s*\("),
    re.compile(r"\bshops_repo\.create\s*\("),
    re.compile(r"\bTikTokCredentialRepo\s*\([^)]*\)\.(?:create|update_tokens)\s*\("),
    re.compile(r"\bcred_repo\.(?:create|update_tokens)\s*\("),
)


def _collect_import_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _repo_class_from_value(value: ast.AST) -> str | None:
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        if value.func.id in REPO_CLASS_NAMES:
            return value.func.id
    return None


def _find_repo_write_calls(py_file: Path) -> list[tuple[int, str]]:
    source = py_file.read_text(encoding="utf-8")
    tree = ast.parse(source)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        method = node.func.attr
        if method not in REPO_WRITE_METHODS:
            continue

        repo_class = _repo_class_from_value(node.func.value)
        if repo_class:
            hits.append((node.lineno, f"{repo_class}.{method}"))
            continue

        if isinstance(node.func.value, ast.Name) and node.func.value.id in REPO_WRITE_VAR_NAMES:
            hits.append((node.lineno, f"{node.func.value.id}.{method}"))
    return hits


def _grep_repo_write_hits(py_file: Path) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), start=1):
        for pattern in REPO_WRITE_GREP_PATTERNS:
            if pattern.search(line):
                hits.append((lineno, line.strip()))
                break
    return hits


def _find_function_calls(source: str, callee_name: str) -> list[int]:
    tree = ast.parse(source)
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == callee_name:
            lines.append(node.lineno)
        elif isinstance(func, ast.Attribute) and func.attr == callee_name:
            lines.append(node.lineno)
    return lines


def test_mmu10_only_oauth_facade_may_call_repo_writes_for_connect_refresh() -> None:
    """AC: only TikTokOAuthService facade may write shops/credentials on OAuth paths."""
    offenders: list[str] = []
    for rel_path in OAUTH_CONNECT_REFRESH_PATH:
        if rel_path == OAUTH_FACADE_REL:
            continue
        py_file = BACKEND_SRC / rel_path
        ast_hits = _find_repo_write_calls(py_file)
        grep_hits = _grep_repo_write_hits(py_file)
        if ast_hits or grep_hits:
            offenders.append(f"{rel_path} ast={ast_hits} grep={grep_hits}")

    assert offenders == [], (
        "competing OAuth connect/refresh writers outside Auth facade: " + "; ".join(offenders)
    )


def test_mmu10_persist_oauth_tokens_is_not_competing_writer() -> None:
    """AC: app_review_store.persist_oauth_tokens must delegate to facade, not write repos."""
    app_review_store = BACKEND_SRC / "services/tiktok/app_review_store.py"
    source = app_review_store.read_text(encoding="utf-8")
    assert "async def persist_oauth_tokens" in source

    ast_hits = _find_repo_write_calls(app_review_store)
    grep_hits = _grep_repo_write_hits(app_review_store)
    assert ast_hits == [], f"persist_oauth_tokens still writes repos (ast): {ast_hits}"
    assert grep_hits == [], f"persist_oauth_tokens still writes repos (grep): {grep_hits}"


def test_mmu10_oauth_callback_module_does_not_import_app_review_store() -> None:
    """AC: callback infrastructure must not import competing persist_oauth_tokens writer."""
    oauth_module = BACKEND_SRC / "services/tiktok/oauth.py"
    modules = _collect_import_modules(oauth_module.read_text(encoding="utf-8"))
    forbidden = {
        module
        for module in modules
        if module.endswith("app_review_store") or module.endswith("persist_oauth_tokens")
    }
    assert not forbidden, f"oauth callback module imports competing writer: {forbidden}"


def test_mmu10_callback_infrastructure_source_uses_facade_not_persist_helper() -> None:
    """AC: oauth.py must delegate to TikTokOAuthService, not persist_oauth_tokens."""
    oauth_module = BACKEND_SRC / "services/tiktok/oauth.py"
    source = oauth_module.read_text(encoding="utf-8")

    assert "TikTokOAuthService" in source or OAUTH_FACADE_MODULE in source, (
        "OAuth callback infrastructure must import Auth & Security facade"
    )
    assert "persist_oauth_tokens" not in source, (
        "OAuth callback must not call competing app_review_store writer"
    )


def test_mmu10_complete_callback_delegates_to_oauth_facade() -> None:
    """AC: complete_tiktok_oauth_callback routes shop+credential writes through OAuth facade."""
    oauth_module = BACKEND_SRC / "services/tiktok/oauth.py"
    source = oauth_module.read_text(encoding="utf-8")
    modules = _collect_import_modules(source)

    assert OAUTH_FACADE_MODULE in modules, (
        "oauth callback module must import designated TikTokOAuthService facade"
    )

    persist_calls = _find_function_calls(source, "persist_oauth_tokens")
    assert persist_calls == [], (
        "complete_tiktok_oauth_callback must not call persist_oauth_tokens; "
        f"found calls at lines {persist_calls}"
    )


def test_mmu10_auth_tiktok_callback_route_avoids_competing_writer_imports() -> None:
    """AC: public callback route stays thin and avoids app_review_store wiring."""
    route = BACKEND_SRC / "api/routes/auth_tiktok.py"
    modules = _collect_import_modules(route.read_text(encoding="utf-8"))

    forbidden = {m for m in modules if "app_review_store" in m}
    assert not forbidden, f"auth_tiktok route imports competing writer module: {forbidden}"
    assert any(m.startswith("juli_backend.services.tiktok.oauth") for m in modules), (
        "auth_tiktok route must import OAuth facade entrypoint module"
    )


def test_mmu10_registry_documents_single_auth_security_write_owner() -> None:
    """AC: ownership registry names Auth & Security as sole shops/credentials writer."""
    sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts" / "ci"))
    from check_ownership_registry import load_ownership_registry

    registry = load_ownership_registry()
    for table in ("shops", "tiktok_credentials"):
        entry = registry["databaseTables"][table]
        assert entry["owner"] == "Auth & Security"
        assert entry["access"] == "write"
        notes = entry.get("notes", "").lower()
        assert "dual-writer" not in notes, (
            f"{table} registry notes must not document dual-writer debt after MMU-10"
        )


@pytest.mark.parametrize("rel_path", OAUTH_CONNECT_REFRESH_PATH)
def test_mmu10_grep_ast_repo_write_scan_consistent(rel_path: str) -> None:
    """Grep and AST scans agree on OAuth-path repo write detection."""
    if rel_path == OAUTH_FACADE_REL:
        pytest.skip("facade module is the allowed writer")
    py_file = BACKEND_SRC / rel_path
    ast_hits = _find_repo_write_calls(py_file)
    grep_hits = _grep_repo_write_hits(py_file)
    assert bool(ast_hits) == bool(grep_hits), (
        f"{rel_path}: AST hits {ast_hits} vs grep hits {grep_hits}"
    )
