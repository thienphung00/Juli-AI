import uuid
from datetime import datetime
from typing import Generic, TypeVar

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.exceptions import NotFound
from src.data.models import (
    AlertConfig,
    AlertHistory,
    Creator,
    InventoryItem,
    Livestream,
    Order,
    Product,
    Recommendation,
    Settlement,
    Shop,
    TikTokCredential,
    User,
)

T = TypeVar("T")


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


# ---------------------------------------------------------------------------
# Shop-scoped base repository (#28)
# ---------------------------------------------------------------------------


class ShopScopedRepo(Generic[T]):
    """Base repository with mandatory shop_id scoping and cursor pagination.

    Subclasses set ``_model`` and optionally ``_lookup_attr`` (the column
    name used to match entities during upsert from external sources).
    """

    _model: type[T]
    _lookup_attr: str = ""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(
        self,
        shop_id: uuid.UUID,
        *,
        limit: int = 50,
        after: uuid.UUID | None = None,
    ) -> list[T]:
        """Return entities for *shop_id* with keyset (cursor) pagination."""
        stmt = select(self._model).where(self._model.shop_id == shop_id)

        if after is not None:
            cursor = await self._session.get(self._model, after)
            if cursor is not None:
                stmt = stmt.where(
                    or_(
                        self._model.created_at < cursor.created_at,
                        and_(
                            self._model.created_at == cursor.created_at,
                            self._model.id < cursor.id,
                        ),
                    )
                )

        stmt = stmt.order_by(
            self._model.created_at.desc(), self._model.id.desc()
        ).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, shop_id: uuid.UUID, entity_id: uuid.UUID) -> T:
        """Return entity or raise ``NotFound`` if missing / wrong shop."""
        entity = await self._session.get(self._model, entity_id)
        if entity is None or entity.shop_id != shop_id:
            raise NotFound(f"{self._model.__name__} {entity_id} not found")
        return entity

    async def upsert(self, *, shop_id: uuid.UUID, **kwargs) -> T:
        """Insert or update by ``_lookup_attr``, rejecting stale data via
        ``update_time`` when present."""
        if not self._lookup_attr:
            raise NotImplementedError(
                f"{type(self).__name__} does not support upsert"
            )

        lookup_value = kwargs[self._lookup_attr]
        lookup_col = getattr(self._model, self._lookup_attr)

        stmt = select(self._model).where(
            self._model.shop_id == shop_id,
            lookup_col == lookup_value,
        )
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            incoming_ut = kwargs.get("update_time")
            if (
                incoming_ut is not None
                and getattr(existing, "update_time", None) is not None
                and incoming_ut <= existing.update_time
            ):
                return existing
            for key, value in kwargs.items():
                setattr(existing, key, value)
            await self._session.flush()
            return existing

        entity = self._model(id=uuid.uuid4(), shop_id=shop_id, **kwargs)
        self._session.add(entity)
        await self._session.flush()
        return entity


# ---------------------------------------------------------------------------
# Commerce repos (#28)
# ---------------------------------------------------------------------------


class OrdersRepo(ShopScopedRepo[Order]):
    _model = Order
    _lookup_attr = "tiktok_order_id"


class ProductsRepo(ShopScopedRepo[Product]):
    _model = Product
    _lookup_attr = "tiktok_product_id"


class InventoryRepo(ShopScopedRepo[InventoryItem]):
    _model = InventoryItem
    _lookup_attr = "tiktok_sku_id"


class SettlementsRepo(ShopScopedRepo[Settlement]):
    _model = Settlement
    _lookup_attr = "tiktok_settlement_id"


# ---------------------------------------------------------------------------
# Analytics repos (#28)
# ---------------------------------------------------------------------------


class CreatorsRepo(ShopScopedRepo[Creator]):
    _model = Creator
    _lookup_attr = "tiktok_creator_id"


class LivestreamsRepo(ShopScopedRepo[Livestream]):
    _model = Livestream
    _lookup_attr = "tiktok_livestream_id"


class AlertConfigsRepo(ShopScopedRepo[AlertConfig]):
    _model = AlertConfig

    async def create(self, *, shop_id: uuid.UUID, **kwargs) -> AlertConfig:
        entity = AlertConfig(id=uuid.uuid4(), shop_id=shop_id, **kwargs)
        self._session.add(entity)
        await self._session.flush()
        return entity


class AlertHistoryRepo(ShopScopedRepo[AlertHistory]):
    _model = AlertHistory

    async def create(self, *, shop_id: uuid.UUID, **kwargs) -> AlertHistory:
        entity = AlertHistory(id=uuid.uuid4(), shop_id=shop_id, **kwargs)
        self._session.add(entity)
        await self._session.flush()
        return entity


class RecommendationsRepo(ShopScopedRepo[Recommendation]):
    _model = Recommendation

    async def create(self, *, shop_id: uuid.UUID, **kwargs) -> Recommendation:
        entity = Recommendation(id=uuid.uuid4(), shop_id=shop_id, **kwargs)
        self._session.add(entity)
        await self._session.flush()
        return entity
