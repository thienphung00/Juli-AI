import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.exceptions import NotFound
from src.data.models import (
    Shop,
    TikTokCredential,
    User,
)


class UsersRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: uuid.UUID) -> User:
        result = await self._session.get(User, user_id)
        if result is None:
            raise NotFound(f"User {user_id} not found")
        return result


class ShopsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self, user_id: uuid.UUID) -> list[Shop]:
        stmt = select(Shop).where(Shop.user_id == user_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_tiktok_id(self, tiktok_shop_id: str) -> Shop | None:
        """Find a shop by its TikTok shop ID. Returns None if not found."""
        stmt = select(Shop).where(Shop.tiktok_shop_id == tiktok_shop_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        user_id: uuid.UUID,
        shop_name: str,
        tiktok_shop_id: str | None = None,
    ) -> Shop:
        shop = Shop(
            id=uuid.uuid4(),
            user_id=user_id,
            shop_name=shop_name,
            tiktok_shop_id=tiktok_shop_id,
        )
        self._session.add(shop)
        await self._session.flush()
        return shop


class TikTokCredentialRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        shop_id: uuid.UUID,
        access_token: str,
        refresh_token: str,
        token_expires_at: datetime,
        scopes: str | None = None,
    ) -> TikTokCredential:
        credential = TikTokCredential(
            id=uuid.uuid4(),
            shop_id=shop_id,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=token_expires_at,
            scopes=scopes,
        )
        self._session.add(credential)
        await self._session.flush()
        return credential

    async def get_by_shop(self, shop_id: uuid.UUID) -> TikTokCredential:
        """Return the most recent credential for a shop. Raises NotFound if none."""
        stmt = (
            select(TikTokCredential)
            .where(TikTokCredential.shop_id == shop_id)
            .order_by(TikTokCredential.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        credential = result.scalar_one_or_none()
        if credential is None:
            raise NotFound(f"No credentials found for shop {shop_id}")
        return credential

    async def update_tokens(
        self,
        credential_id: uuid.UUID,
        access_token: str,
        refresh_token: str,
        token_expires_at: datetime,
    ) -> TikTokCredential:
        credential = await self._session.get(TikTokCredential, credential_id)
        if credential is None:
            raise NotFound(f"Credential {credential_id} not found")
        credential.access_token = access_token
        credential.refresh_token = refresh_token
        credential.token_expires_at = token_expires_at
        await self._session.flush()
        return credential
