import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Generic, TypeVar

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.exceptions import NotFound
from backend.database.models import (
    AlertConfig,
    AlertHistory,
    Campaign,
    Creator,
    GraphEdge,
    InventoryItem,
    Livestream,
    Order,
    OrderItem,
    ProcessedEvent,
    Product,
    Recommendation,
    Return,
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

    async def get_or_create(self, user_id: uuid.UUID, phone: str) -> User:
        """Return user by id, creating it when missing."""
        existing = await self._session.get(User, user_id)
        if existing is not None:
            return existing
        user = User(id=user_id, phone=phone)
        self._session.add(user)
        await self._session.flush()
        return user


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

    async def get_latest(self) -> TikTokCredential:
        """Return the most recently created credential. Raises NotFound if none."""
        stmt = (
            select(TikTokCredential)
            .order_by(TikTokCredential.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        credential = result.scalar_one_or_none()
        if credential is None:
            raise NotFound("No TikTok credentials found")
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

    _model: Any
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

    async def list_filtered(
        self,
        shop_id: uuid.UUID,
        *,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 50,
        after: uuid.UUID | None = None,
    ) -> list[Order]:
        """List orders with optional filters and cursor pagination."""
        stmt = select(self._model).where(self._model.shop_id == shop_id)

        if status is not None:
            stmt = stmt.where(self._model.status == status)
        if date_from is not None:
            stmt = stmt.where(self._model.update_time >= date_from)
        if date_to is not None:
            stmt = stmt.where(self._model.update_time <= date_to)

        if after is not None:
            cursor_stmt = select(self._model).where(self._model.id == after)
            cursor_result = await self._session.execute(cursor_stmt)
            cursor = cursor_result.scalar_one_or_none()
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

    async def confirm_shipment(
        self, shop_id: uuid.UUID, order_id: uuid.UUID
    ) -> Order:
        """Mark an AWAITING_SHIPMENT order as SHIPPED. Raises NotFound or
        ValueError for invalid transitions."""
        order = await self.get(shop_id, order_id)
        if order.status != "AWAITING_SHIPMENT":
            raise ValueError(
                f"Cannot ship order in status '{order.status}'"
            )
        order.status = "SHIPPED"
        order.update_time = datetime.now(timezone.utc)
        await self._session.flush()
        return order


class OrderItemsRepo(ShopScopedRepo[OrderItem]):
    _model = OrderItem
    _lookup_attr = "tiktok_sku_id"

    async def upsert(self, *, shop_id: uuid.UUID, **kwargs) -> OrderItem:
        tiktok_order_id = kwargs.get("tiktok_order_id")
        tiktok_sku_id = kwargs.get("tiktok_sku_id")
        if not tiktok_order_id or not tiktok_sku_id:
            raise ValueError("tiktok_order_id and tiktok_sku_id required")

        stmt = select(self._model).where(
            self._model.shop_id == shop_id,
            self._model.tiktok_order_id == tiktok_order_id,
            self._model.tiktok_sku_id == tiktok_sku_id,
        )
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            incoming_ut = kwargs.get("update_time")
            if (
                incoming_ut is not None
                and existing.update_time is not None
                and incoming_ut <= existing.update_time
            ):
                return existing
            for key, value in kwargs.items():
                setattr(existing, key, value)
            await self._session.flush()
            return existing

        entity = OrderItem(id=uuid.uuid4(), shop_id=shop_id, **kwargs)
        self._session.add(entity)
        await self._session.flush()
        return entity


class ReturnsRepo(ShopScopedRepo[Return]):
    _model = Return
    _lookup_attr = "tiktok_return_id"


class ProductsRepo(ShopScopedRepo[Product]):
    _model = Product
    _lookup_attr = "tiktok_product_id"

    async def list_by_revenue(
        self,
        shop_id: uuid.UUID,
        *,
        limit: int = 50,
        after: uuid.UUID | None = None,
    ) -> list[Product]:
        """List products ordered by revenue descending."""
        stmt = select(self._model).where(self._model.shop_id == shop_id)

        if after is not None:
            cursor_stmt = select(self._model).where(self._model.id == after)
            cursor_result = await self._session.execute(cursor_stmt)
            cursor = cursor_result.scalar_one_or_none()
            if cursor is not None:
                stmt = stmt.where(
                    or_(
                        self._model.revenue < cursor.revenue,
                        and_(
                            self._model.revenue == cursor.revenue,
                            self._model.id < cursor.id,
                        ),
                    )
                )

        stmt = stmt.order_by(
            self._model.revenue.desc(), self._model.id.desc()
        ).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


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

    async def get_by_type(
        self, shop_id: uuid.UUID, alert_type: str
    ) -> AlertConfig | None:
        stmt = select(AlertConfig).where(
            AlertConfig.shop_id == shop_id,
            AlertConfig.alert_type == alert_type,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(self, shop_id: uuid.UUID) -> list[AlertConfig]:
        stmt = select(AlertConfig).where(
            AlertConfig.shop_id == shop_id,
            AlertConfig.is_active.is_(True),
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class AlertHistoryRepo(ShopScopedRepo[AlertHistory]):
    _model = AlertHistory

    async def create(self, *, shop_id: uuid.UUID, **kwargs) -> AlertHistory:
        entity = AlertHistory(id=uuid.uuid4(), shop_id=shop_id, **kwargs)
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def has_recent_for_type(
        self,
        shop_id: uuid.UUID,
        alert_type: str,
        *,
        since: datetime,
    ) -> bool:
        stmt = (
            select(AlertHistory.id)
            .join(AlertConfig, AlertHistory.alert_config_id == AlertConfig.id)
            .where(
                AlertHistory.shop_id == shop_id,
                AlertConfig.alert_type == alert_type,
                AlertHistory.triggered_at >= since,
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None


class RecommendationsRepo(ShopScopedRepo[Recommendation]):
    _model = Recommendation

    async def create(self, *, shop_id: uuid.UUID, **kwargs) -> Recommendation:
        entity = Recommendation(id=uuid.uuid4(), shop_id=shop_id, **kwargs)
        self._session.add(entity)
        await self._session.flush()
        return entity


class GraphRepo:
    """Shop-scoped commerce graph: Campaign nodes and relationship edges."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_edge(
        self,
        shop_id: uuid.UUID,
        *,
        edge_type: str,
        source_node_type: str,
        source_node_id: uuid.UUID,
        target_node_type: str,
        target_node_id: uuid.UUID,
        weight: Decimal | None = None,
        metadata_json: str | None = None,
        computed_at: datetime | None = None,
    ) -> GraphEdge:
        stmt = select(GraphEdge).where(
            GraphEdge.shop_id == shop_id,
            GraphEdge.edge_type == edge_type,
            GraphEdge.source_node_type == source_node_type,
            GraphEdge.source_node_id == source_node_id,
            GraphEdge.target_node_type == target_node_type,
            GraphEdge.target_node_id == target_node_id,
        )
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            if weight is not None:
                existing.weight = weight
            if metadata_json is not None:
                existing.metadata_json = metadata_json
            if computed_at is not None:
                existing.computed_at = computed_at
            await self._session.flush()
            return existing

        edge = GraphEdge(
            id=uuid.uuid4(),
            shop_id=shop_id,
            edge_type=edge_type,
            source_node_type=source_node_type,
            source_node_id=source_node_id,
            target_node_type=target_node_type,
            target_node_id=target_node_id,
            weight=weight,
            metadata_json=metadata_json,
            computed_at=computed_at,
        )
        self._session.add(edge)
        await self._session.flush()
        return edge

    async def list_edges(
        self,
        shop_id: uuid.UUID,
        *,
        edge_type: str | None = None,
        node_type: str | None = None,
        node_id: uuid.UUID | None = None,
    ) -> list[GraphEdge]:
        stmt = select(GraphEdge).where(GraphEdge.shop_id == shop_id)
        if edge_type is not None:
            stmt = stmt.where(GraphEdge.edge_type == edge_type)
        if node_type is not None and node_id is not None:
            stmt = stmt.where(
                or_(
                    and_(
                        GraphEdge.source_node_type == node_type,
                        GraphEdge.source_node_id == node_id,
                    ),
                    and_(
                        GraphEdge.target_node_type == node_type,
                        GraphEdge.target_node_id == node_id,
                    ),
                )
            )
        stmt = stmt.order_by(GraphEdge.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def find_campaign_by_idempotency(
        self,
        shop_id: uuid.UUID,
        idempotency_key: str,
    ) -> Campaign | None:
        stmt = select(Campaign).where(
            Campaign.shop_id == shop_id,
            Campaign.idempotency_key == idempotency_key,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_campaign(
        self,
        shop_id: uuid.UUID,
        campaign_id: uuid.UUID,
    ) -> Campaign | None:
        stmt = select(Campaign).where(
            Campaign.shop_id == shop_id,
            Campaign.id == campaign_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_campaign(
        self,
        shop_id: uuid.UUID,
        *,
        creator_id: uuid.UUID,
        product_ids: list[str],
        status: str = "draft",
        predicted_gmv: Decimal | None = None,
        realized_gmv: Decimal | None = None,
        predicted_conversion: Decimal | None = None,
        realized_conversion: Decimal | None = None,
        idempotency_key: str | None = None,
    ) -> Campaign:
        campaign = Campaign(
            id=uuid.uuid4(),
            shop_id=shop_id,
            creator_id=creator_id,
            status=status,
            product_ids_json=json.dumps(product_ids),
            predicted_gmv=predicted_gmv,
            realized_gmv=realized_gmv,
            predicted_conversion=predicted_conversion,
            realized_conversion=realized_conversion,
            idempotency_key=idempotency_key,
        )
        self._session.add(campaign)
        await self._session.flush()
        return campaign


class ProcessedEventsRepo:
    """Tracks consumed ingest event IDs for idempotent ETL (#32)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(self, *, event_id: str, shop_id: uuid.UUID) -> bool:
        """Insert *event_id* if unseen. Returns False when already processed."""
        stmt = select(ProcessedEvent).where(ProcessedEvent.event_id == event_id)
        result = await self._session.execute(stmt)
        if result.scalar_one_or_none() is not None:
            return False
        self._session.add(ProcessedEvent(event_id=event_id, shop_id=shop_id))
        await self._session.flush()
        return True
