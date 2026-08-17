import json
import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from juli_backend.database.exceptions import NotFound
from juli_backend.database.token_crypto import decrypt_token, encrypt_token
from juli_backend.integrations.tiktok import (
    TikTokCapability,
    is_cross_merchant_lookup,
)
from juli_backend.models.models import (
    ActionCard,
    AlertConfig,
    AlertHistory,
    AnalyticsBackfillPartition,
    AnalyticsKpiEnvelope,
    AnalyticsPerformanceInterval,
    BronzeCtorPerformanceRawPayload,
    BronzeLiveHoursRawPayload,
    BronzeOrderRawPayload,
    BronzeReturnRawPayload,
    Campaign,
    Creator,
    GoldKpiEnvelope,
    GraphEdge,
    InventoryItem,
    Livestream,
    Order,
    OrderItem,
    Product,
    Recommendation,
    Return,
    Settlement,
    Shop,
    TikTokCredential,
    TikTokSyncState,
    ToolExecution,
    User,
    WebhookRawEvent,
    WorkflowOutcomeRecord,
    WorkflowWebhookSignal,
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

    async def pause_automation(self, shop_id: uuid.UUID) -> None:
        """Pause automations for one shop after seller deauthorization (#354 #6)."""
        shop = await self._session.get(Shop, shop_id)
        if shop is None:
            return
        shop.is_active = False
        await self._session.flush()


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
        *,
        merchant_authorization_id: str | None = None,
        capability: str | None = None,
        shop_cipher: str | None = None,
    ) -> TikTokCredential:
        if merchant_authorization_id and capability:
            if is_cross_merchant_lookup(merchant_authorization_id, capability):
                raise ValueError("merchant_authorization_id and capability do not match")

        credential = TikTokCredential(
            id=uuid.uuid4(),
            shop_id=shop_id,
            merchant_authorization_id=merchant_authorization_id,
            capability=capability,
            shop_cipher=shop_cipher,
            access_token=encrypt_token(access_token),
            refresh_token=encrypt_token(refresh_token),
            token_expires_at=token_expires_at,
            scopes=scopes,
        )
        self._session.add(credential)
        await self._session.flush()
        _hydrate_decrypted_tokens(credential)
        return credential

    async def get_by_merchant(
        self,
        merchant_authorization_id: str,
        capability: TikTokCapability | str,
    ) -> TikTokCredential:
        """Return credential for a merchant authorization ID + capability pair."""
        capability_value = (
            capability.value if isinstance(capability, TikTokCapability) else capability
        )
        if is_cross_merchant_lookup(merchant_authorization_id, capability_value):
            raise NotFound(
                f"No credentials for merchant {merchant_authorization_id} "
                f"with capability {capability_value}"
            )

        stmt = (
            select(TikTokCredential)
            .where(
                TikTokCredential.merchant_authorization_id == merchant_authorization_id,
                TikTokCredential.capability == capability_value,
            )
            .order_by(TikTokCredential.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        credential = result.scalar_one_or_none()
        if credential is None:
            raise NotFound(
                f"No credentials for merchant {merchant_authorization_id} "
                f"with capability {capability_value}"
            )
        _hydrate_decrypted_tokens(credential)
        return credential

    async def get_by_shop_and_capability(
        self,
        shop_id: uuid.UUID,
        capability: TikTokCapability | str,
    ) -> TikTokCredential:
        """Return the most recent credential for a shop and capability."""
        capability_value = (
            capability.value if isinstance(capability, TikTokCapability) else capability
        )
        stmt = (
            select(TikTokCredential)
            .where(
                TikTokCredential.shop_id == shop_id,
                TikTokCredential.capability == capability_value,
            )
            .order_by(TikTokCredential.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        credential = result.scalar_one_or_none()
        if credential is None:
            raise NotFound(
                f"No credentials found for shop {shop_id} with capability {capability_value}"
            )
        _hydrate_decrypted_tokens(credential)
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
        _hydrate_decrypted_tokens(credential)
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
        credential.access_token = encrypt_token(access_token)
        credential.refresh_token = encrypt_token(refresh_token)
        credential.token_expires_at = token_expires_at
        await self._session.flush()
        _hydrate_decrypted_tokens(credential)
        return credential


_ENDPOINT_STATE_KEYS: dict[str, str] = {
    "orders": "orders_last_update_time",
    "products": "products_last_update_time",
    "returns": "returns_last_update_time",
    "inventory": "inventory_last_sync_at",
    # Analytics wire set (#424) — LIVE A-26–A-29 intentionally omitted.
    "shop_sku_performance": "shop_sku_performance_last_sync_at",
    "shop_product_performance": "shop_product_performance_last_sync_at",
    "shop_performance": "shop_performance_last_sync_at",
    "shop_performance_per_hour": "shop_performance_per_hour_last_sync_at",
    "bestselling_products": "bestselling_products_last_sync_at",
    "bestselling_videos": "bestselling_videos_last_sync_at",
    "promotion_activity": "promotion_activity_last_sync_at",
}

_STATE_KEY_ENDPOINTS = {value: key for key, value in _ENDPOINT_STATE_KEYS.items()}


class TikTokSyncStateRepo:
    """Persist incremental sync cursors per shop and endpoint."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load(self, shop_id: uuid.UUID) -> dict[str, Any]:
        stmt = select(TikTokSyncState).where(TikTokSyncState.shop_id == shop_id)
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        state: dict[str, Any] = {}
        for row in rows:
            state_key = _ENDPOINT_STATE_KEYS.get(row.endpoint)
            if state_key is not None:
                state[state_key] = row.last_update_time
        return state

    async def save(self, shop_id: uuid.UUID, sync_state: dict[str, Any]) -> None:
        endpoints_to_update = {
            _STATE_KEY_ENDPOINTS[state_key]: int(last_update_time)
            for state_key, last_update_time in sync_state.items()
            if state_key in _STATE_KEY_ENDPOINTS and last_update_time is not None
        }
        if not endpoints_to_update:
            return

        stmt = select(TikTokSyncState).where(
            TikTokSyncState.shop_id == shop_id,
            TikTokSyncState.endpoint.in_(endpoints_to_update),
        )
        result = await self._session.execute(stmt)
        existing = {row.endpoint: row for row in result.scalars()}

        for endpoint, last_update_time in endpoints_to_update.items():
            row = existing.get(endpoint)
            if row is None:
                self._session.add(
                    TikTokSyncState(
                        id=uuid.uuid4(),
                        shop_id=shop_id,
                        endpoint=endpoint,
                        last_update_time=last_update_time,
                    )
                )
            else:
                row.last_update_time = last_update_time

        await self._session.flush()


def _hydrate_decrypted_tokens(credential: TikTokCredential) -> None:
    """Expose plaintext tokens to callers without marking DB columns dirty."""
    set_committed_value(credential, "access_token", decrypt_token(credential.access_token))
    set_committed_value(credential, "refresh_token", decrypt_token(credential.refresh_token))


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

        stmt = stmt.order_by(self._model.created_at.desc(), self._model.id.desc()).limit(limit)
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
            raise NotImplementedError(f"{type(self).__name__} does not support upsert")

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
        try:
            async with self._session.begin_nested():
                self._session.add(entity)
                await self._session.flush()
            return entity
        except IntegrityError:
            result = await self._session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing is None:
                raise
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


# ---------------------------------------------------------------------------
# Commerce repos (#28)
# ---------------------------------------------------------------------------


class OrdersRepo(ShopScopedRepo[Order]):
    _model = Order
    _lookup_attr = "tiktok_order_id"

    async def get_by_tiktok_id(
        self,
        shop_id: uuid.UUID,
        tiktok_order_id: str,
    ) -> Order | None:
        stmt = select(self._model).where(
            self._model.shop_id == shop_id,
            self._model.tiktok_order_id == tiktok_order_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

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

        stmt = stmt.order_by(self._model.created_at.desc(), self._model.id.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def confirm_shipment(self, shop_id: uuid.UUID, order_id: uuid.UUID) -> Order:
        """Mark an AWAITING_SHIPMENT order as SHIPPED. Raises NotFound or
        ValueError for invalid transitions."""
        order = await self.get(shop_id, order_id)
        if order.status != "AWAITING_SHIPMENT":
            raise ValueError(f"Cannot ship order in status '{order.status}'")
        order.status = "SHIPPED"
        # Order.update_time is a naive column (no timezone=True). asyncpg
        # rejects an aware datetime here with DataError at flush time on
        # real Postgres — SQLite/psycopg2 silently tolerate it (#1138).
        order.update_time = datetime.now(UTC).replace(tzinfo=None)
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

    async def recompute_revenue_from_order_items(
        self, shop_id: uuid.UUID, tiktok_product_id: str
    ) -> None:
        """Recompute ``revenue``/``units_sold`` from synced ``order_items`` (#943).

        Full recompute (SUM over all matching order_items), not an increment —
        an incremental add would double-count on a redelivered or corrected
        webhook, since ``OrderItemsRepo.upsert`` overwrites the line on update
        rather than diffing it. No-ops (0 rows updated) when the product hasn't
        synced yet; the next order_item recompute for that product id will
        pick it up once it has.
        """
        totals_stmt = select(
            func.coalesce(func.sum(OrderItem.line_total), 0),
            func.coalesce(func.sum(OrderItem.quantity), 0),
        ).where(
            OrderItem.shop_id == shop_id,
            OrderItem.tiktok_product_id == tiktok_product_id,
        )
        revenue, units_sold = (await self._session.execute(totals_stmt)).one()

        await self._session.execute(
            update(Product)
            .where(
                Product.shop_id == shop_id,
                Product.tiktok_product_id == tiktok_product_id,
            )
            .values(revenue=revenue, units_sold=units_sold)
        )
        await self._session.flush()

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

        stmt = stmt.order_by(self._model.revenue.desc(), self._model.id.desc()).limit(limit)
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


class AnalyticsPerformanceRepo(ShopScopedRepo[AnalyticsPerformanceInterval]):
    _model = AnalyticsPerformanceInterval
    _lookup_attr = "snapshot_key"


class GoldKpiEnvelopesRepo:
    """Serving gold.kpi_envelopes — one row per shop (#606)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, shop_id: uuid.UUID) -> GoldKpiEnvelope | None:
        entity = await self._session.get(GoldKpiEnvelope, shop_id)
        if entity is not None:
            await self._session.refresh(entity)
        return entity

    async def upsert(
        self,
        *,
        shop_id: uuid.UUID,
        envelope_version: int,
        payload: dict[str, Any],
        computed_at: datetime,
    ) -> GoldKpiEnvelope:
        existing = await self.get(shop_id)
        if existing is not None:
            existing.envelope_version = envelope_version
            existing.payload = payload
            existing.computed_at = computed_at
            await self._session.flush()
            await self._session.refresh(existing)
            return existing

        entity = GoldKpiEnvelope(
            shop_id=shop_id,
            envelope_version=envelope_version,
            payload=payload,
            computed_at=computed_at,
        )
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity


def _gold_to_legacy_envelope(gold: GoldKpiEnvelope) -> AnalyticsKpiEnvelope:
    """Map gold serving row to legacy envelope shape for Demo/cache compat."""
    return AnalyticsKpiEnvelope(
        id=uuid.uuid5(uuid.NAMESPACE_OID, f"{gold.shop_id}:analytics"),
        shop_id=gold.shop_id,
        kind="analytics",
        envelope_version=gold.envelope_version,
        payload=gold.payload,
        computed_at=gold.computed_at,
        created_at=gold.created_at,
        updated_at=gold.updated_at,
    )


class AnalyticsKpiEnvelopesRepo:
    """Compat adapter — reads/writes gold.kpi_envelopes only (#606 cutover)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._gold = GoldKpiEnvelopesRepo(session)

    async def get_by_kind(self, shop_id: uuid.UUID, kind: str) -> AnalyticsKpiEnvelope | None:
        if kind != "analytics":
            return None
        gold = await self._gold.get(shop_id)
        if gold is None:
            return None
        return _gold_to_legacy_envelope(gold)

    async def upsert(
        self,
        *,
        shop_id: uuid.UUID,
        kind: str,
        envelope_version: int,
        payload: dict[str, Any],
        computed_at: datetime,
    ) -> AnalyticsKpiEnvelope:
        if kind != "analytics":
            raise ValueError(f"unsupported envelope kind after gold cutover: {kind}")
        gold = await self._gold.upsert(
            shop_id=shop_id,
            envelope_version=envelope_version,
            payload=payload,
            computed_at=computed_at,
        )
        envelope = _gold_to_legacy_envelope(gold)
        envelope.computed_at = computed_at
        return envelope

    async def list(self, shop_id: uuid.UUID, *, limit: int = 50) -> list[AnalyticsKpiEnvelope]:
        gold = await self._gold.get(shop_id)
        if gold is None:
            return []
        return [_gold_to_legacy_envelope(gold)][:limit]


class AlertConfigsRepo(ShopScopedRepo[AlertConfig]):
    _model = AlertConfig

    async def create(self, *, shop_id: uuid.UUID, **kwargs) -> AlertConfig:
        entity = AlertConfig(id=uuid.uuid4(), shop_id=shop_id, **kwargs)
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def get_by_type(self, shop_id: uuid.UUID, alert_type: str) -> AlertConfig | None:
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


class ActionCardsRepo(ShopScopedRepo[ActionCard]):
    """Idempotent upsert for persisted Decision rows — ADR-021."""

    _model = ActionCard
    _lookup_attr = "workflow_key"

    async def list_active(self, shop_id: uuid.UUID) -> list[ActionCard]:
        stmt = (
            select(self._model)
            .where(
                self._model.shop_id == shop_id,
                self._model.status == "active",
            )
            .order_by(self._model.priority.asc(), self._model.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


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


from juli_backend.services.etl.persistence.ingest import (  # noqa: E402, F401, I001
    ProcessedEventsRepo,  # MMU-9a legacy shim
)


class WorkflowWebhookSignalsRepo:
    """Durable workflow-intent records for Phase 2 catalog webhooks (#354)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_shop(self, shop_id: uuid.UUID) -> list[WorkflowWebhookSignal]:
        stmt = (
            select(WorkflowWebhookSignal)
            .where(WorkflowWebhookSignal.shop_id == shop_id)
            .order_by(WorkflowWebhookSignal.created_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def record_if_new(
        self,
        *,
        shop_id: uuid.UUID,
        tiktok_shop_id: str,
        catalog_id: int,
        event_type: str,
        workflow_keys: list[str],
        intent: str,
        event_id: str,
        payload_json: str,
    ) -> bool:
        stmt = select(WorkflowWebhookSignal).where(WorkflowWebhookSignal.event_id == event_id)
        result = await self._session.execute(stmt)
        if result.scalar_one_or_none() is not None:
            return False
        self._session.add(
            WorkflowWebhookSignal(
                shop_id=shop_id,
                tiktok_shop_id=tiktok_shop_id,
                catalog_id=catalog_id,
                event_type=event_type,
                workflow_keys=json.dumps(workflow_keys),
                intent=intent,
                event_id=event_id,
                payload=payload_json,
            )
        )
        await self._session.flush()
        return True


class BronzeOrderRawPayloadsRepo:
    """Batched append writer for bronze.order_raw_payloads (#605)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append_batch(
        self,
        records: list[dict[str, Any]],
    ) -> list[BronzeOrderRawPayload]:
        if not records:
            return []
        rows = [
            BronzeOrderRawPayload(
                shop_id=record["shop_id"],
                ingest_source=record["ingest_source"],
                payload=record["payload"],
                received_at=record.get("received_at") or datetime.now(UTC),
                tiktok_order_id=record.get("tiktok_order_id"),
                source_event_id=record.get("source_event_id"),
            )
            for record in records
        ]
        self._session.add_all(rows)
        await self._session.flush()
        return rows


class BronzeReturnRawPayloadsRepo:
    """Batched append writer for bronze.return_raw_payloads (#605)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append_batch(
        self,
        records: list[dict[str, Any]],
    ) -> list[BronzeReturnRawPayload]:
        if not records:
            return []
        rows = [
            BronzeReturnRawPayload(
                shop_id=record["shop_id"],
                ingest_source=record["ingest_source"],
                payload=record["payload"],
                received_at=record.get("received_at") or datetime.now(UTC),
                tiktok_return_id=record.get("tiktok_return_id"),
                tiktok_order_id=record.get("tiktok_order_id"),
                source_event_id=record.get("source_event_id"),
            )
            for record in records
        ]
        self._session.add_all(rows)
        await self._session.flush()
        return rows


class BronzeCtorPerformanceRawPayloadsRepo:
    """Batched append writer for bronze.ctor_performance_raw_payloads (#880)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append_batch(
        self,
        records: list[dict[str, Any]],
    ) -> list[BronzeCtorPerformanceRawPayload]:
        if not records:
            return []
        rows = [
            BronzeCtorPerformanceRawPayload(
                shop_id=record["shop_id"],
                ingest_source=record["ingest_source"],
                payload=record["payload"],
                received_at=record.get("received_at") or datetime.now(UTC),
                tiktok_product_id=record.get("tiktok_product_id"),
                source_event_id=record.get("source_event_id"),
            )
            for record in records
        ]
        self._session.add_all(rows)
        await self._session.flush()
        return rows


class BronzeLiveHoursRawPayloadsRepo:
    """Batched append writer for bronze.live_hours_raw_payloads (#880)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append_batch(
        self,
        records: list[dict[str, Any]],
    ) -> list[BronzeLiveHoursRawPayload]:
        if not records:
            return []
        rows = [
            BronzeLiveHoursRawPayload(
                shop_id=record["shop_id"],
                ingest_source=record["ingest_source"],
                payload=record["payload"],
                received_at=record.get("received_at") or datetime.now(UTC),
                tiktok_live_id=record.get("tiktok_live_id"),
                source_event_id=record.get("source_event_id"),
            )
            for record in records
        ]
        self._session.add_all(rows)
        await self._session.flush()
        return rows


class WebhookRawEventsRepo:
    """Read-only audit shim for redacted TikTok HTTP deliveries (#392).

    Forward domain raw writes use ``BronzeOrderRawPayloadsRepo`` /
    ``BronzeReturnRawPayloadsRepo`` — do not double-write indefinitely.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(
        self,
        *,
        tiktok_shop_id: str | None,
        event_type: str | None,
        event_id: str | None,
        signature_header: str | None,
        headers: str | None,
        raw_body: str | None,
        http_status: int,
        processing_status: str,
        parse_version: int = 1,
    ) -> WebhookRawEvent:
        row = WebhookRawEvent(
            tiktok_shop_id=tiktok_shop_id,
            event_type=event_type,
            event_id=event_id,
            signature_header=signature_header,
            headers=headers,
            raw_body=raw_body,
            http_status=http_status,
            processing_status=processing_status,
            parse_version=parse_version,
        )
        self._session.add(row)
        await self._session.flush()
        return row


class ToolExecutionsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        shop_id: uuid.UUID,
        approval_id: str,
        tool_name: str,
        payload_json: str,
        status: str,
        celery_task_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ToolExecution:
        record = ToolExecution(
            shop_id=shop_id,
            approval_id=approval_id,
            tool_name=tool_name,
            payload_json=payload_json,
            status=status,
            celery_task_id=celery_task_id,
            idempotency_key=idempotency_key,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def get(self, shop_id: uuid.UUID, execution_id: uuid.UUID) -> ToolExecution:
        record = await self._session.get(ToolExecution, execution_id)
        if record is None or record.shop_id != shop_id:
            raise NotFound(f"ToolExecution {execution_id} not found")
        return record

    async def get_by_id(self, execution_id: uuid.UUID) -> ToolExecution:
        record = await self._session.get(ToolExecution, execution_id)
        if record is None:
            raise NotFound(f"ToolExecution {execution_id} not found")
        return record

    async def set_celery_task_id(
        self,
        shop_id: uuid.UUID,
        execution_id: uuid.UUID,
        celery_task_id: str,
    ) -> ToolExecution:
        record = await self.get(shop_id, execution_id)
        record.celery_task_id = celery_task_id
        await self._session.flush()
        return record

    async def update_status(
        self,
        shop_id: uuid.UUID,
        execution_id: uuid.UUID,
        *,
        status: str,
        outcome_json: str | None = None,
        error_message: str | None = None,
        error_category: str | None = None,
    ) -> ToolExecution:
        record = await self.get(shop_id, execution_id)
        record.status = status
        if outcome_json is not None:
            record.outcome_json = outcome_json
        if error_message is not None:
            record.error_message = error_message
        if error_category is not None:
            record.error_category = error_category
        await self._session.flush()
        return record


class WorkflowOutcomeRecordsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        shop_id: uuid.UUID,
        approval_id: str,
        execution_id: uuid.UUID,
        workflow_id: str,
        execution_status: str,
        metrics_json: str,
        executed_at: datetime,
    ) -> WorkflowOutcomeRecord:
        record = WorkflowOutcomeRecord(
            shop_id=shop_id,
            approval_id=approval_id,
            execution_id=execution_id,
            workflow_id=workflow_id,
            execution_status=execution_status,
            metrics_json=metrics_json,
            executed_at=executed_at,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_by_approval_id(
        self,
        shop_id: uuid.UUID,
        approval_id: str,
    ) -> WorkflowOutcomeRecord:
        stmt = select(WorkflowOutcomeRecord).where(
            WorkflowOutcomeRecord.shop_id == shop_id,
            WorkflowOutcomeRecord.approval_id == approval_id,
        )
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            raise NotFound(f"WorkflowOutcomeRecord for approval {approval_id} not found")
        return record

    async def get_by_execution_id(
        self,
        shop_id: uuid.UUID,
        execution_id: uuid.UUID,
    ) -> WorkflowOutcomeRecord | None:
        stmt = select(WorkflowOutcomeRecord).where(
            WorkflowOutcomeRecord.shop_id == shop_id,
            WorkflowOutcomeRecord.execution_id == execution_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


_BACKFILL_BUCKETS = frozenset({"revenue", "product", "live", "catalog"})
_BACKFILL_INCOMPLETE_STATUSES = frozenset({"pending", "failed"})
_TOKEN_REDACT_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[^\s]+"),
    re.compile(r"(?i)(access[_-]?token[=:\s]+)[^\s,;]+"),
    re.compile(r"(?i)(refresh[_-]?token[=:\s]+)[^\s,;]+"),
    re.compile(r"(?i)(authorization[=:\s]+)[^\s,;]+"),
)


def _redact_error_message(message: str) -> str:
    redacted = message
    for pattern in _TOKEN_REDACT_PATTERNS:
        redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted


class AnalyticsBackfillPartitionsRepo:
    """Track resumable analytics backfill progress per (shop_id, bucket, date)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def validate_bucket(bucket: str) -> None:
        if bucket not in _BACKFILL_BUCKETS:
            msg = f"Invalid backfill bucket {bucket!r}; expected one of {sorted(_BACKFILL_BUCKETS)}"
            raise ValueError(msg)

    async def get_partition(
        self,
        shop_id: uuid.UUID,
        bucket: str,
        partition_date: date,
    ) -> AnalyticsBackfillPartition | None:
        """Return the durable partition row for ``(shop_id, bucket, partition_date)``."""
        return await self._get_row(shop_id, bucket, partition_date)

    async def _get_row(
        self,
        shop_id: uuid.UUID,
        bucket: str,
        partition_date: date,
    ) -> AnalyticsBackfillPartition | None:
        self.validate_bucket(bucket)
        stmt = select(AnalyticsBackfillPartition).where(
            AnalyticsBackfillPartition.shop_id == shop_id,
            AnalyticsBackfillPartition.bucket == bucket,
            AnalyticsBackfillPartition.partition_date == partition_date,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_complete(
        self,
        shop_id: uuid.UUID,
        bucket: str,
        partition_date: date,
    ) -> AnalyticsBackfillPartition:
        self.validate_bucket(bucket)
        row = await self._get_row(shop_id, bucket, partition_date)
        if row is None:
            row = AnalyticsBackfillPartition(
                shop_id=shop_id,
                bucket=bucket,
                partition_date=partition_date,
                status="complete",
                retryable=False,
            )
            self._session.add(row)
        else:
            row.status = "complete"
            row.retryable = False
            row.last_error = None
        await self._session.flush()
        return row

    async def mark_failed(
        self,
        shop_id: uuid.UUID,
        bucket: str,
        partition_date: date,
        error: str,
        *,
        retryable: bool = True,
    ) -> AnalyticsBackfillPartition:
        self.validate_bucket(bucket)
        row = await self._get_row(shop_id, bucket, partition_date)
        if row is None:
            row = AnalyticsBackfillPartition(
                shop_id=shop_id,
                bucket=bucket,
                partition_date=partition_date,
                status="failed",
                attempt_count=1,
                last_error=_redact_error_message(error),
                retryable=retryable,
            )
            self._session.add(row)
        else:
            row.status = "failed"
            row.attempt_count += 1
            row.last_error = _redact_error_message(error)
            row.retryable = retryable
        await self._session.flush()
        return row

    async def is_complete(
        self,
        shop_id: uuid.UUID,
        bucket: str,
        partition_date: date,
    ) -> bool:
        row = await self._get_row(shop_id, bucket, partition_date)
        return row is not None and row.status == "complete"

    async def list_incomplete(
        self,
        shop_id: uuid.UUID,
        bucket: str,
        start: date,
        end: date,
    ) -> list[AnalyticsBackfillPartition]:
        self.validate_bucket(bucket)
        if end < start:
            return []
        stmt = (
            select(AnalyticsBackfillPartition)
            .where(
                AnalyticsBackfillPartition.shop_id == shop_id,
                AnalyticsBackfillPartition.bucket == bucket,
                AnalyticsBackfillPartition.partition_date >= start,
                AnalyticsBackfillPartition.partition_date <= end,
                AnalyticsBackfillPartition.status.in_(_BACKFILL_INCOMPLETE_STATUSES),
            )
            .order_by(AnalyticsBackfillPartition.partition_date)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_completed(
        self,
        shop_id: uuid.UUID,
        bucket: str,
        start: date,
        end: date,
    ) -> list[AnalyticsBackfillPartition]:
        """Return all completed partitions for the given shop/bucket/date range.

        Bulk-load completed (bucket, date) pairs for O(1) membership testing,
        replacing the N-query pattern of calling is_complete per partition.
        """
        self.validate_bucket(bucket)
        if end < start:
            return []
        stmt = (
            select(AnalyticsBackfillPartition)
            .where(
                AnalyticsBackfillPartition.shop_id == shop_id,
                AnalyticsBackfillPartition.bucket == bucket,
                AnalyticsBackfillPartition.partition_date >= start,
                AnalyticsBackfillPartition.partition_date <= end,
                AnalyticsBackfillPartition.status == "complete",
            )
            .order_by(AnalyticsBackfillPartition.partition_date)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
