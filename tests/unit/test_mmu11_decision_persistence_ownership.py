"""MMU-11 (#559): Action Cards / Scoring sole write owner for decision tables."""

from __future__ import annotations

import ast
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RECOMMENDATIONS_ROUTE = REPO_ROOT / "backend/src/juli_backend/api/routes/recommendations.py"
ACTION_CARDS_INIT = REPO_ROOT / "backend/src/juli_backend/services/action_cards/__init__.py"
REGISTRY_PATH = REPO_ROOT / "docs/architecture/ownership-registry.yml"


def _collect_import_modules(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _source_references_recommendations_repo_create(py_file: Path) -> bool:
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                node.func.attr == "create"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "repo"
            ):
                return True
    return False


def test_mmu11_recommendations_route_does_not_import_recommendations_repo():
    """AC: API route must not import RecommendationsRepo (non-owner write helper)."""
    modules = _collect_import_modules(RECOMMENDATIONS_ROUTE)
    offenders = {
        m
        for m in modules
        if m.endswith("RecommendationsRepo")
        or m.endswith("repositories.repos")
        or "RecommendationsRepo" in m
    }
    assert not offenders, f"recommendations route imports repo write helper: {offenders}"


def test_mmu11_recommendations_route_delegates_to_action_cards_owner():
    """AC: API route delegates persistence to action_cards public owner service."""
    modules = _collect_import_modules(RECOMMENDATIONS_ROUTE)
    assert any(m.startswith("juli_backend.services.action_cards") for m in modules), (
        "recommendations route must import action_cards owner facade"
    )


def test_mmu11_recommendations_route_has_no_direct_repo_create_calls():
    """AC: route source must not call repo.create for recommendations."""
    assert not _source_references_recommendations_repo_create(RECOMMENDATIONS_ROUTE)


def test_mmu11_action_cards_public_api_exports_legacy_persist():
    """AC: owner module exposes legacy recommendations write on public __all__."""
    import juli_backend.services.action_cards as action_cards

    assert "persist_legacy_recommendations" in action_cards.__all__
    assert callable(action_cards.persist_legacy_recommendations)


def test_mmu11_registry_marks_decision_tables_action_cards_scoring_owner():
    """AC: registry documents Action Cards / Scoring as decision-table write owner."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts" / "ci"))
    from check_ownership_registry import load_ownership_registry

    registry = load_ownership_registry()
    for table in ("action_cards", "recommendations"):
        entry = registry["databaseTables"][table]
        assert entry["owner"] == "Intelligence"
        assert entry["access"] == "write"
        notes = entry.get("notes", "").lower()
        assert "action cards" in notes or "action_cards" in notes
        assert "scoring" in notes


@pytest.mark.asyncio
async def test_mmu11_get_recommendations_delegates_persist_when_empty(
    monkeypatch,
    engine,
    session,
):
    """AC: empty shop triggers owner persist helper, not inline repo.create."""
    from httpx import ASGITransport, AsyncClient

    from juli_backend.api.app import create_app
    from juli_backend.database import get_session
    from juli_backend.models.models import Shop, User

    user = User(id=uuid.uuid4(), phone="+849559000559")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="MMU-11 Delegation Shop",
        tiktok_shop_id="tiktok_mmu11",
    )
    session.add_all([user, shop])
    await session.flush()

    persist_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "juli_backend.api.routes.recommendations.persist_legacy_recommendations",
        persist_mock,
    )

    app = create_app()

    async def _test_session():
        yield session

    from juli_backend.api.dependencies import get_active_shop
    from juli_backend.core.security import get_current_user

    app.dependency_overrides[get_session] = _test_session
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_active_shop] = lambda: shop

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/recommendations",
            headers={"X-Shop-Id": str(shop.id)},
        )

    assert response.status_code == 200
    persist_mock.assert_awaited_once_with(session, shop.id)


@pytest.mark.asyncio
async def test_mmu11_action_card_refresh_persist_still_works(
    session,
    user_id,
    monkeypatch,
):
    """AC: existing refresh → persist flow remains on owning module."""
    from juli_backend.models.models import Shop, User
    from juli_backend.services.action_cards.refresh import run_action_card_refresh

    user = User(id=user_id, phone="+849559000559b")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="MMU-11 Refresh Shop",
        tiktok_shop_id="tiktok_mmu11_refresh",
    )
    session.add_all([user, shop])
    await session.flush()

    persist_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "juli_backend.services.action_cards.refresh.persist_scoring_result",
        persist_mock,
    )
    monkeypatch.setattr(
        "juli_backend.services.action_cards.refresh.run_daily_scoring_for_shop",
        AsyncMock(return_value=object()),
    )

    await run_action_card_refresh(session, shop.id, poll=False)

    persist_mock.assert_awaited_once()
