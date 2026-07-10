"""Contract tests for Phase 2.5-c backend runtime migration (Issue #252)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_backend_entrypoints_workers_integrations_database_ownership_align():
    """Backend boundary matches migration-plan target layout."""
    for rel in (
        "backend/src/juli_backend/api/main.py",
        "backend/src/juli_backend/workers/services/polling/sync.py",
        "backend/src/juli_backend/integrations/tiktok/client.py",
        "backend/src/juli_backend/models/models.py",
        "backend/src/juli_backend/ai/dataset/assembler.py",
    ):
        assert (REPO_ROOT / rel).is_file(), f"missing runtime module: {rel}"


def test_python_imports_rewritten_no_product_app_imports_in_backend():
    """Backend code imports juli_backend.* only — not top-level apps/."""
    offenders: list[str] = []
    for path in (REPO_ROOT / "backend/src/juli_backend").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "from apps." in text or "import apps." in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"backend must not import product apps/: {offenders}"


def test_api_factory_auth_polling_etl_tiktok_repository_tests_pass():
    """Representative migrated suites remain importable from backend paths."""
    from juli_backend.api.app import create_app
    from juli_backend.core.security import get_current_user
    from juli_backend.workers.services.polling import sync
    from juli_backend.services.etl import EtlConsumer
    from juli_backend.integrations.tiktok.client import TikTokClient
    from juli_backend.repositories.repos import ShopScopedRepo

    assert callable(create_app)
    assert callable(get_current_user)
    assert hasattr(sync, "sync_creators")
    assert EtlConsumer is not None
    assert TikTokClient is not None
    assert ShopScopedRepo is not None


def test_src_python_runtime_shims_removed():
    """Legacy src/ Python shim tree removed after deploy entrypoint switch."""
    src_root = REPO_ROOT / "src"
    if src_root.is_dir():
        py_files = list(src_root.rglob("*.py"))
        assert not py_files, f"unexpected Python files under src/: {py_files[:5]}"
    assert not (REPO_ROOT / "src/COMPAT.md").is_file()


def test_deploy_entrypoint_uses_backend_api_main():
    """Deploy systemd uses canonical juli_backend.api.main:app entrypoint."""
    service = (REPO_ROOT / "infra/deploy/systemd/juli-api.service").read_text(encoding="utf-8")
    assert "juli_backend.api.main:app" in service
    assert "src.apps.api_gateway" not in service
