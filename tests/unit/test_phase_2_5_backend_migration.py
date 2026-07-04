"""Contract tests for Phase 2.5-c backend runtime migration (Issue #252)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_backend_entrypoints_workers_integrations_database_ownership_align():
    """Backend boundary matches migration-plan target layout."""
    for rel in (
        "backend/api/api/main.py",
        "backend/workers/services/polling/sync.py",
        "backend/integrations/catalog/domain/integrations/tiktok/client.py",
        "backend/database/models.py",
        "backend/ai/dataset/assembler.py",
    ):
        assert (REPO_ROOT / rel).is_file(), f"missing runtime module: {rel}"


def test_python_imports_rewritten_no_product_app_imports_in_backend():
    """Backend code imports backend.* only — not top-level apps/."""
    offenders: list[str] = []
    for path in (REPO_ROOT / "backend").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "from apps." in text or "import apps." in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, f"backend must not import product apps/: {offenders}"


def test_api_factory_auth_polling_etl_tiktok_repository_tests_pass():
    """Representative migrated suites remain importable from backend paths."""
    from backend.api.api.app import create_app
    from backend.integrations.identity.infrastructure.auth import get_current_user
    from backend.workers.services.polling import sync
    from backend.integrations.ordering.use_cases.etl import EtlConsumer
    from backend.integrations.catalog.domain.integrations.tiktok.client import TikTokClient
    from backend.database.repos import ShopScopedRepo

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
    """Deploy systemd uses canonical backend.api.api.main:app entrypoint."""
    service = (REPO_ROOT / "infra/deploy/systemd/juli-api.service").read_text(encoding="utf-8")
    assert "backend.api.api.main:app" in service
    assert "src.apps.api_gateway" not in service
