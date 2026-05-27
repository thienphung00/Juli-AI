"""AC2 — ShopsRepo.list(user_id) returns only shops belonging to that user;
UsersRepo.get(user_id) returns user or raises NotFound."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.data import User, Shop, UsersRepo, ShopsRepo, NotFound


pytestmark = pytest.mark.asyncio


class TestShopsRepoScopedByUser:
    """AC2: Repository queries enforce user-scoped data isolation."""

    async def test_shops_repo_list_returns_only_user_shops(
        self, session: AsyncSession, user_id, other_user_id
    ):
        user_a = User(id=user_id, phone="+84901111111")
        user_b = User(id=other_user_id, phone="+84902222222")
        shop_a = Shop(id=uuid.uuid4(), user_id=user_id, shop_name="Shop A")
        shop_b = Shop(id=uuid.uuid4(), user_id=other_user_id, shop_name="Shop B")
        session.add_all([user_a, user_b, shop_a, shop_b])
        await session.flush()

        repo = ShopsRepo(session)
        result = await repo.list(user_id)

        assert len(result) == 1
        assert result[0].shop_name == "Shop A"
        assert result[0].user_id == user_id

    async def test_shops_repo_list_returns_empty_when_no_shops(
        self, session: AsyncSession
    ):
        lonely_user_id = uuid.uuid4()
        user = User(id=lonely_user_id, phone="+84903333333")
        session.add(user)
        await session.flush()

        repo = ShopsRepo(session)
        result = await repo.list(lonely_user_id)
        assert result == []

    async def test_users_repo_get_returns_user(
        self, session: AsyncSession, user_id
    ):
        user = User(id=user_id, phone="+84904444444", display_name="Seller X")
        session.add(user)
        await session.flush()

        repo = UsersRepo(session)
        result = await repo.get(user_id)

        assert result.id == user_id
        assert result.display_name == "Seller X"

    async def test_users_repo_get_raises_not_found(self, session: AsyncSession):
        repo = UsersRepo(session)
        with pytest.raises(NotFound):
            await repo.get(uuid.uuid4())

    async def test_shops_repo_create(
        self, session: AsyncSession, user_id
    ):
        user = User(id=user_id, phone="+84905555555")
        session.add(user)
        await session.flush()

        repo = ShopsRepo(session)
        shop = await repo.create(
            user_id=user_id,
            shop_name="New Shop",
            tiktok_shop_id="tts_123456",
        )

        assert shop.user_id == user_id
        assert shop.shop_name == "New Shop"
        assert shop.tiktok_shop_id == "tts_123456"
        assert shop.id is not None
