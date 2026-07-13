"""P2-B1 Action Card persistence contract tests — Issue #303 (reopened).

AC1 → action_cards table + ActionCardsRepo idempotent upsert
AC2 → POST /v1/action-cards/refresh returns 202 and enqueues Celery (never blocks)
AC3 → GET /v1/action-cards returns persisted rows only (no on-the-fly regeneration)
AC4 → two consecutive refreshes update rows in place (same count, bumped updated_at)
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from juli_backend.models.models import Order, Product, Return, Shop, User


@pytest_asyncio.fixture
async def app(engine, session):
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    application = create_app()

    async def _test_session():
        yield session

    application.dependency_overrides[get_session] = _test_session
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def authenticated_user(session, user_id):
    user = User(id=user_id, phone="+849305000303")
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def shop(session, authenticated_user):
    s = Shop(
        id=uuid.uuid4(),
        user_id=authenticated_user.id,
        shop_name="Action Cards Shop 303",
        tiktok_shop_id="tiktok_shop_303",
    )
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def auth_client(app, authenticated_user, shop):
    from juli_backend.api.dependencies import get_active_shop
    from juli_backend.core.security import get_current_user

    app.dependency_overrides[get_current_user] = lambda: authenticated_user
    app.dependency_overrides[get_active_shop] = lambda: shop

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.fixture
def mock_refresh_dispatcher(monkeypatch):
    dispatcher = MagicMock()
    dispatcher.enqueue.return_value = "celery-task-id-303"
    monkeypatch.setattr(
        "juli_backend.services.action_cards.dispatch.get_refresh_dispatcher",
        lambda: dispatcher,
    )
    return dispatcher


@pytest.mark.asyncio
async def test_action_cards_repo_upsert_inserts_new_card(session, shop):
    """AC1: first upsert inserts a row keyed by (shop_id, workflow_key)."""
    from juli_backend.repositories.repos import ActionCardsRepo

    repo = ActionCardsRepo(session)
    card = await repo.upsert(
        shop_id=shop.id,
        workflow_key="create_hero_product_1",
        priority=1,
        severity="warning",
        title="Create Hero Product",
        description="Revenue opportunity on top SKU.",
        recommendation_payload=json.dumps({"workflow_key": "create_hero_product_1"}),
        status="active",
    )
    await session.flush()

    assert card.id is not None
    assert card.shop_id == shop.id
    assert card.workflow_key == "create_hero_product_1"
    assert card.status == "active"


@pytest.mark.asyncio
async def test_action_cards_repo_second_upsert_updates_not_duplicates(session, shop):
    """AC1: second upsert for same workflow_key updates row — no duplicate."""
    from juli_backend.repositories.repos import ActionCardsRepo

    repo = ActionCardsRepo(session)
    first = await repo.upsert(
        shop_id=shop.id,
        workflow_key="optimize_product_2",
        priority=2,
        severity="warning",
        title="Optimize Product",
        description="First copy.",
        recommendation_payload=json.dumps({"priority": 2}),
        status="active",
    )
    await session.flush()
    first_updated_at = first.updated_at

    second = await repo.upsert(
        shop_id=shop.id,
        workflow_key="optimize_product_2",
        priority=1,
        severity="critical",
        title="Optimize Product",
        description="Updated copy.",
        recommendation_payload=json.dumps({"priority": 1}),
        status="active",
    )
    await session.flush()

    listed = await repo.list_active(shop.id)
    assert len(listed) == 1
    assert second.id == first.id
    assert second.priority == 1
    assert second.severity == "critical"
    assert second.description == "Updated copy."
    assert second.updated_at >= first_updated_at


@pytest.mark.asyncio
async def test_ac2_post_refresh_returns_202_and_enqueues_without_inline_run(
    auth_client,
    mock_refresh_dispatcher,
    monkeypatch,
):
    """AC2: HTTP handler returns 202 after enqueue; refresh worker not called inline."""
    worker_calls: list[str] = []
    monkeypatch.setattr(
        "juli_backend.workers.tasks.action_card_refresh.refresh_action_cards_sync",
        lambda shop_id: worker_calls.append(shop_id),
    )

    response = await auth_client.post("/v1/action-cards/refresh")
    assert response.status_code == 202
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "queued"
    assert body["data"]["celery_task_id"] == "celery-task-id-303"
    assert worker_calls == []
    mock_refresh_dispatcher.enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_ac3_get_action_cards_returns_persisted_only(
    auth_client,
    session,
    shop,
):
    """AC3: GET returns persisted cards; empty when nothing stored."""
    from juli_backend.repositories.repos import ActionCardsRepo

    empty = await auth_client.get("/v1/action-cards")
    assert empty.status_code == 200
    assert empty.json()["data"] == []

    repo = ActionCardsRepo(session)
    await repo.upsert(
        shop_id=shop.id,
        workflow_key="process_order_5",
        priority=3,
        severity="healthy",
        title="Process Orders",
        description="Fulfill pending orders.",
        recommendation_payload=json.dumps({"workflow_key": "process_order_5"}),
        status="active",
    )
    await session.commit()

    listed = await auth_client.get("/v1/action-cards")
    assert listed.status_code == 200
    data = listed.json()["data"]
    assert len(data) == 1
    assert data[0]["workflow_key"] == "process_order_5"
    assert data[0]["title"] == "Process Orders"


@pytest.mark.asyncio
async def test_integration_two_consecutive_refreshes_same_row_count(
    session,
    user_id,
    monkeypatch,
):
    """AC4: two refresh runs upsert in place — same row count, bumped updated_at."""
    from juli_backend.repositories.repos import ActionCardsRepo
    from juli_backend.services.action_cards.refresh import run_action_card_refresh

    user = User(id=user_id, phone="+84930300303")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="Refresh Integration Shop",
        tiktok_shop_id="tiktok_refresh_303",
        created_at=datetime.now(UTC) - timedelta(days=120),
    )
    session.add_all([user, shop])
    now = datetime.now(UTC)
    session.add_all(
        [
            Product(
                id=uuid.uuid4(),
                shop_id=shop.id,
                tiktok_product_id="prod-303",
                name="Widget 303",
                status="ACTIVE",
                revenue=Decimal("800000"),
                units_sold=40,
                update_time=now,
            ),
            Order(
                id=uuid.uuid4(),
                shop_id=shop.id,
                tiktok_order_id="ord-303",
                status="COMPLETED",
                total_amount=Decimal("150000"),
                currency="VND",
                update_time=now,
            ),
            Return(
                id=uuid.uuid4(),
                shop_id=shop.id,
                tiktok_return_id="ret-303",
                tiktok_order_id="ord-303",
                return_type="refund",
                refund_amount=Decimal("10000"),
                status="COMPLETED",
                update_time=now,
            ),
        ]
    )
    await session.flush()

    monkeypatch.setattr(
        "juli_backend.services.action_cards.refresh.maybe_poll_tiktok_data",
        AsyncMock(),
    )

    first_run = await run_action_card_refresh(session, shop.id, poll=False)
    await session.flush()
    first_count = len(first_run)
    assert first_count >= 1

    repo = ActionCardsRepo(session)
    cards_after_first = await repo.list_active(shop.id)
    first_updated = {card.workflow_key: card.updated_at for card in cards_after_first}

    await session.commit()

    second_run = await run_action_card_refresh(session, shop.id, poll=False)
    await session.flush()
    cards_after_second = await repo.list_active(shop.id)

    assert len(cards_after_second) == len(cards_after_first)
    assert len(second_run) == first_count
    for card in cards_after_second:
        assert card.updated_at >= first_updated[card.workflow_key]


def test_no_redis_dependency_postgres_only_store():
    """Reopened AC: Action Card persistence uses Postgres only — not Redis as store."""
    import ast
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    persistence_modules = (
        repo_root / "backend/src/juli_backend/services/action_cards/persist.py",
        repo_root / "backend/src/juli_backend/services/action_cards/dispatch.py",
        repo_root / "backend/src/juli_backend/api/routes/action_cards.py",
    )
    forbidden = {"redis", "aioredis"}

    for py_file in persistence_modules:
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        assert not imports & forbidden, f"{py_file.name} imports Redis: {imports & forbidden}"


def test_execution_p2_b1_checkbox_marked_complete():
    """Reopened AC: EXECUTION.md P2-B1 slice marked complete after persistence ships."""
    execution_md = Path(__file__).resolve().parents[2] / "EXECUTION.md"
    text = execution_md.read_text(encoding="utf-8")
    assert "- [x] **P2-B1**" in text
