"""AC1 — User, Shop, and TikTokCredential models defined with proper
relationships, indexes on user_id/shop_id, and async SQLAlchemy mappings."""

import uuid

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database import User, Shop, TikTokCredential


class TestAuthCoreModelsDefined:
    """AC1: Models exist with correct schema, relationships, and indexes."""

    def test_user_table_columns(self):
        mapper = sa_inspect(User)
        column_names = {c.key for c in mapper.columns}
        assert {"id", "phone", "display_name", "created_at", "updated_at"} <= column_names

    def test_shop_table_columns(self):
        mapper = sa_inspect(Shop)
        column_names = {c.key for c in mapper.columns}
        assert {"id", "user_id", "shop_name", "tiktok_shop_id", "is_active", "created_at", "updated_at"} <= column_names

    def test_tiktok_credential_table_columns(self):
        mapper = sa_inspect(TikTokCredential)
        column_names = {c.key for c in mapper.columns}
        assert {"id", "shop_id", "merchant_authorization_id", "capability", "access_token", "refresh_token", "token_expires_at", "created_at", "updated_at"} <= column_names

    def test_user_id_is_uuid_primary_key(self):
        mapper = sa_inspect(User)
        pk_cols = [c.key for c in mapper.columns if c.primary_key]
        assert pk_cols == ["id"]
        col_type = User.__table__.c.id.type
        assert col_type.__class__.__name__ == "Uuid"

    def test_shop_has_user_id_index(self):
        indexed_cols = set()
        for idx in Shop.__table__.indexes:
            for col in idx.columns:
                indexed_cols.add(col.name)
        assert "user_id" in indexed_cols

    def test_credential_has_shop_id_index(self):
        indexed_cols = set()
        for idx in TikTokCredential.__table__.indexes:
            for col in idx.columns:
                indexed_cols.add(col.name)
        assert "shop_id" in indexed_cols

    def test_user_shops_relationship(self):
        mapper = sa_inspect(User)
        rel_names = {r.key for r in mapper.relationships}
        assert "shops" in rel_names

    def test_shop_credentials_relationship(self):
        mapper = sa_inspect(Shop)
        rel_names = {r.key for r in mapper.relationships}
        assert "credentials" in rel_names
        assert "owner" in rel_names


@pytest.mark.asyncio
class TestAuthCoreModelsAsync:
    """AC1 (async): Models work with async SQLAlchemy sessions."""

    async def test_models_work_with_async_session(self, session: AsyncSession, user_id):
        user = User(id=user_id, phone="+84901234567", display_name="Test Seller")
        session.add(user)
        await session.flush()

        fetched = await session.get(User, user_id)
        assert fetched is not None
        assert fetched.phone == "+84901234567"

    async def test_shop_foreign_key_to_user(self, session: AsyncSession, user_id):
        user = User(id=user_id, phone="+84900000001")
        shop = Shop(id=uuid.uuid4(), user_id=user_id, shop_name="My TikTok Shop")
        session.add_all([user, shop])
        await session.flush()

        fetched_shop = await session.get(Shop, shop.id)
        assert fetched_shop is not None
        assert fetched_shop.user_id == user_id
