"""The reviewer's live sandbox shop: pin check, write resources, listing write + read-back.

Fast track P64, owner decision D73 (grill 2026-10-21). Shopee's ISV review needs a REAL
working TikTok Shop integration, so the reviewer may be pinned (``REVIEWER_SHOP_ID``) to
Juli's own TikTok Shop SANDBOX shop and really write its listings there. Three layers, each
failing closed (D73 Q6):

1. **Pin** (:func:`classify_pin`). The pinned shop is ``sandbox`` only when it IS the shop of
   the sandbox credential ``resolve_sandbox_write_credential`` uses (not refused), and holds
   no ``production_read`` credential and no ``production_write_shops`` row. A pin that holds
   either is a production shop: writes off and a loud ``reviewer_pin_production_shop`` error.
   Any non-sandbox pin keeps the P32 behaviour (identity mask on, read-only).
2. **Credential** (:func:`load_reviewer_write_resources`). Only ``SandboxWriteClientFactory``,
   only for the sandbox credential, only when its row belongs to the pinned shop, inside the
   reviewer scope (``integrations.tiktok.reviewer_session``), where every production write
   path refuses.
3. **Tests**: ``tests/unit/test_reviewer_sandbox_live.py``.

The write itself (:func:`write_listing`) is the production-seller write set and nothing else
(D13): the listing edit (title / description through the agent's own
``update_product_listing`` body) and the cover image (screened, uploaded, then the listing
edit). No price, no inventory. After the write the product is read back from TikTok and the
confirmed fields are returned with the time of the read (``production_write.diff_listing_write``,
the same before/after rule as a seller's production write).
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import (
    SandboxCredentialRefused,
    resolve_sandbox_write_credential,
    sandbox_write_owners,
)
from juli_backend.database.exceptions import NotFound
from juli_backend.integrations.tiktok import (
    ClientFactoryConfig,
    SandboxWriteClientFactory,
    SandboxWriteResources,
    TikTokAPIError,
    TikTokCapability,
    reviewer_session_active,
)
from juli_backend.models.models import ProductionWriteShop, TikTokCredential

logger = logging.getLogger(__name__)

MODE_SANDBOX = "sandbox"
MODE_MASKED = "masked"

#: Why reviewer writes are off for a pin (``PinMode.writes_disabled_reason``).
REASON_NOT_SANDBOX = "not_sandbox_shop"
REASON_PRODUCTION_READ = "pin_holds_production_read"
REASON_PRODUCTION_WRITE = "pin_has_production_write_row"
REASON_SANDBOX_REFUSED = "sandbox_credential_refused"

#: TikTok: the product does not belong to the seller the token is for (#1290).
TIKTOK_PRODUCT_NOT_OWNED = 12052048


@dataclass(frozen=True)
class PinMode:
    """What the pinned shop is, for the reviewer (decided per request, never cached)."""

    mode: str
    writes_enabled: bool
    writes_disabled_reason: str | None = None

    @property
    def sandbox(self) -> bool:
        return self.mode == MODE_SANDBOX

    @property
    def mask(self) -> bool:
        """D73 Q1/Q2: the identity mask is off only for Juli's own sandbox shop."""
        return not self.sandbox


class ReviewerWriteRefused(PermissionError):
    """A reviewer write that layer 1 or 2 refuses (pin, credential, scope)."""


class ProductNotOwnedBySandboxSeller(RuntimeError):
    """TikTok 12052048: the product is not the sandbox seller's (#1290)."""


async def classify_pin(session: AsyncSession, shop_id: uuid.UUID) -> PinMode:
    """The pinned shop's mode. The caller holds the shop's read scope (``enter_reviewer_shop``)."""
    owners = await sandbox_write_owners(session)
    owner = owners[0] if owners else None
    capabilities = {
        row
        for row in (
            await session.execute(
                select(TikTokCredential.capability).where(TikTokCredential.shop_id == shop_id)
            )
        ).scalars()
    }
    production_write_row = (
        await session.execute(
            select(ProductionWriteShop.shop_id).where(ProductionWriteShop.shop_id == shop_id)
        )
    ).scalar_one_or_none() is not None
    reason: str | None = None
    if TikTokCapability.PRODUCTION_READ.value in capabilities:
        reason = REASON_PRODUCTION_READ
    elif production_write_row:
        reason = REASON_PRODUCTION_WRITE
    if reason is not None:
        # Fail closed and loud (D73 Q6 layer 1): a reviewer must never sit on a seller's shop
        # with writes on. Logged on every request while the pin is wrong.
        logger.error(
            "reviewer_pin_production_shop",
            extra={"shop_id": str(shop_id), "reason": reason},
        )
        return PinMode(MODE_MASKED, writes_enabled=False, writes_disabled_reason=reason)
    if owner is None or owner.shop_id != shop_id:
        return PinMode(MODE_MASKED, writes_enabled=False, writes_disabled_reason=REASON_NOT_SANDBOX)
    if owner.collides or not owner.merchant_authorization_id:
        logger.error("reviewer_pin_sandbox_refused", extra={"shop_id": str(shop_id)})
        return PinMode(
            MODE_MASKED, writes_enabled=False, writes_disabled_reason=REASON_SANDBOX_REFUSED
        )
    return PinMode(MODE_SANDBOX, writes_enabled=True)


async def load_reviewer_write_resources(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    app_key: str,
    app_secret: str,
    factory: SandboxWriteClientFactory | None = None,
) -> SandboxWriteResources:
    """The sandbox write resources for the pinned sandbox shop (D73 Q6 layer 2).

    Refuses (:class:`ReviewerWriteRefused`) outside a reviewer request, when no usable
    sandbox credential exists, and when the sandbox credential's row is not ``shop_id``'s
    own. Only ever ``SandboxWriteClientFactory``.
    """
    if not reviewer_session_active():
        raise ReviewerWriteRefused("reviewer write resources outside a reviewer request")
    try:
        credential = await resolve_sandbox_write_credential(session)
    except (NotFound, SandboxCredentialRefused) as exc:
        raise ReviewerWriteRefused(f"no usable sandbox credential: {exc}") from None
    if credential.shop_id != shop_id:
        logger.error(
            "reviewer_write_credential_not_pinned_shop",
            extra={"shop_id": str(shop_id), "credential_shop_id": str(credential.shop_id)},
        )
        raise ReviewerWriteRefused("the sandbox credential does not belong to the pinned shop")
    config = ClientFactoryConfig(
        app_key=app_key,
        app_secret=app_secret,
        access_token=credential.access_token,
        merchant_auth_id=credential.merchant_authorization_id or "",
        shop_cipher=credential.shop_cipher,
        credential_capability=credential.capability,
    )
    return (factory or SandboxWriteClientFactory()).create_resources(config)


@dataclass
class ListingWriteResult:
    """One reviewer write, as TikTok confirmed it on the read-back."""

    tiktok_product_id: str
    operations: list[str]
    #: ``{"field", "before", "after", "after_source"}`` per changed field (``read_back`` when
    #: the read-back shows the new value, ``intended`` while TikTok still shows the old one).
    fields: list[dict[str, Any]]
    #: The read-back's current listing values (title, description, main_images).
    confirmed: dict[str, Any]
    confirmed_at: datetime
    image_uri: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _raise_if_not_owned(exc: TikTokAPIError) -> None:
    if exc.code == TIKTOK_PRODUCT_NOT_OWNED:
        raise ProductNotOwnedBySandboxSeller(exc.message) from exc


def write_listing(
    resources: SandboxWriteResources,
    *,
    tiktok_product_id: str,
    title: str | None,
    description: str | None,
    image_bytes: bytes | None,
) -> ListingWriteResult:
    """Read, write (cover upload, then listing edit), read back. Blocking: run off the loop.

    Raises :class:`ProductNotOwnedBySandboxSeller` on TikTok 12052048 (never a pretended
    success); any other ``TikTokAPIError`` propagates.
    """
    # Imported here: the agent's tool module pulls the whole agent package.
    from juli_backend.services.agent.tools.product import ProductToolContext
    from juli_backend.services.agent.tools.product_write import (
        UpdateProductListingInput,
        UploadProductImageInput,
        handle_update_product_listing,
        handle_upload_product_image,
    )
    from juli_backend.services.execution.production_write import (
        diff_listing_write,
        listing_field_values,
    )

    try:
        before: Mapping[str, Any] = resources.products.get_details(tiktok_product_id)
        operations: list[str] = []
        staged: list[str] = []
        if image_bytes is not None:
            handle_upload_product_image(
                resources,
                ProductToolContext(
                    product_id=tiktok_product_id,
                    pending_image_bytes=image_bytes,
                    on_image_staged=staged.append,
                ),
                UploadProductImageInput(),
            )
            operations.append("upload_product_image")
        handle_update_product_listing(
            resources,
            ProductToolContext(
                product_id=tiktok_product_id,
                product_detail=before,
                staged_image_uri=staged[0] if staged else None,
            ),
            UpdateProductListingInput(
                title=title, description=description, attach_staged_image=bool(staged)
            ),
        )
        operations.append("update_product_listing")
        after: Mapping[str, Any] = resources.products.get_details(tiktok_product_id)
    except TikTokAPIError as exc:
        _raise_if_not_owned(exc)
        raise
    confirmed_at = datetime.now(UTC)
    intended: dict[str, Any] = {}
    if title is not None:
        intended["title"] = title
    if description is not None:
        intended["description"] = description
    if staged:
        intended["main_images"] = [{"uri": staged[0]}]
    fields = [
        {"field": name, "before": old, "after": new, "after_source": source}
        for name, old, new, source in diff_listing_write(
            before=before, after=after, intended=intended
        )
    ]
    return ListingWriteResult(
        tiktok_product_id=tiktok_product_id,
        operations=operations,
        fields=fields,
        confirmed=listing_field_values(after),
        confirmed_at=confirmed_at,
        image_uri=staged[0] if staged else None,
    )


# -- "Đồng bộ ngay" ------------------------------------------------------------------------

#: The reviewer's "Sync now" may enqueue one ``poll_shop`` per this many seconds per shop.
SYNC_INTERVAL_SECONDS = 60.0
_sync_lock = threading.Lock()
_last_sync: dict[uuid.UUID, float] = {}


def claim_sync_slot(shop_id: uuid.UUID, *, now: float | None = None) -> float:
    """0 when a sync may be enqueued now (and the slot is taken), else seconds to wait.

    In-process: the API runs one uvicorn worker (``infra/systemd/juli-api.service``), and
    ``poll_shop`` itself holds the shop's cycle lock, so a second process at worst queues
    one more cycle that skips.
    """
    moment = time.monotonic() if now is None else now
    with _sync_lock:
        last = _last_sync.get(shop_id)
        if last is not None and moment - last < SYNC_INTERVAL_SECONDS:
            return SYNC_INTERVAL_SECONDS - (moment - last)
        _last_sync[shop_id] = moment
        return 0.0


def release_sync_slot(shop_id: uuid.UUID) -> None:
    """Give the slot back (the enqueue failed: nothing was queued)."""
    with _sync_lock:
        _last_sync.pop(shop_id, None)


def forget_sync_slots() -> None:
    with _sync_lock:
        _last_sync.clear()


async def connection_info(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, Any]:
    """The shop's TikTok connection and last successful sync (the caller holds its scope).

    Identifiers, timestamps and scope names only -- never a token or merchant id.
    """
    from juli_backend.models.models import TikTokSyncState

    credential = (
        (
            await session.execute(
                select(TikTokCredential)
                .where(TikTokCredential.shop_id == shop_id)
                .order_by(TikTokCredential.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    states = list(
        (
            await session.execute(
                select(TikTokSyncState)
                .where(TikTokSyncState.shop_id == shop_id)
                .order_by(TikTokSyncState.endpoint)
            )
        ).scalars()
    )
    successes = [state.last_success_at for state in states if state.last_success_at is not None]
    connection: dict[str, Any] | None = None
    if credential is not None:
        connection = {
            "status": credential.status,
            "capability": credential.capability,
            "authorized_at": _iso(credential.created_at),
            "last_refreshed_at": _iso(credential.last_refreshed_at),
            "token_expires_at": _iso(credential.token_expires_at),
            "scopes": [s.strip() for s in (credential.scopes or "").split(",") if s.strip()],
        }
    return {
        "connection": connection,
        "synced_at": _iso(max(successes)) if successes else None,
        "endpoints": [
            {
                "endpoint": state.endpoint,
                "last_success_at": _iso(state.last_success_at),
                "last_outcome": state.last_outcome,
                "last_outcome_at": _iso(state.last_outcome_at),
            }
            for state in states
        ],
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "MODE_MASKED",
    "MODE_SANDBOX",
    "REASON_NOT_SANDBOX",
    "REASON_PRODUCTION_READ",
    "REASON_PRODUCTION_WRITE",
    "REASON_SANDBOX_REFUSED",
    "TIKTOK_PRODUCT_NOT_OWNED",
    "SYNC_INTERVAL_SECONDS",
    "ListingWriteResult",
    "PinMode",
    "ProductNotOwnedBySandboxSeller",
    "ReviewerWriteRefused",
    "claim_sync_slot",
    "classify_pin",
    "connection_info",
    "forget_sync_slots",
    "release_sync_slot",
    "load_reviewer_write_resources",
    "write_listing",
]
