"""The reviewer's live sandbox shop: pin check, connection info, "Đồng bộ ngay".

Fast track P64, owner decision D73 (grill 2026-10-21). Shopee's ISV review needs a REAL
working TikTok Shop integration, so the reviewer may be pinned (``REVIEWER_SHOP_ID``) to
Juli's own TikTok Shop SANDBOX shop and really write its listings there. P74-A (D77): with
``REVIEWER_SHOP_IDS`` the reviewer holds several pins, each classified here on its own; the
one ``X-Shop-Id`` selects decides the request's mode. Three layers, each
failing closed (D73 Q6):

1. **Pin** (:func:`classify_pin`). The pinned shop is ``sandbox`` only when it IS the shop of
   the sandbox credential ``resolve_sandbox_write_credential`` uses (not refused), and holds
   no ``production_read`` credential and no ``production_write_shops`` row. A pin that holds
   either is a production shop: writes off and a loud ``reviewer_pin_production_shop`` error.
   Any non-sandbox pin keeps the P32 behaviour (identity mask on, read-only).
2. **Writes** (D73.4, 2026-10-22): the reviewer's Duyệt is the seller's own approve -- an
   agent run (``services/agent``), whose writes for the sandbox shop go through
   ``SandboxWriteClientFactory`` (``services/agent/composition``: the sandbox shop owns
   the sandbox credential and has no ``production_write_shops`` row, which layer 1
   checks). Every reviewer request is marked (``integrations.tiktok.reviewer_session``),
   so every production write path refuses inside it.
3. **Tests**: ``tests/unit/test_reviewer_sandbox_live.py``.

P100 S2-B: a third mode, ``sample`` -- the synthetic Shopee shop ("Dữ liệu mẫu") a loader puts
in the database. A pin is ``sample`` only when ALL hold (:func:`_sample_refusal`): it is listed
in ``REVIEWER_SAMPLE_SHOP_IDS`` (and is a pin: ``config.reviewer_sample_shop_ids``); it is not
in ``config.NEVER_SAMPLE_SHOP_IDS`` (Fujiwa); it holds no TikTok credential row of ANY
capability (NULL included) and no ``production_write_shops`` row; it is not the sandbox
credential's shop; it is a Shopee shop with no TikTok shop id. Shopee has no platform OAuth in
Juli -- a Shopee shop's only credential is an ingest token (``ingest_tokens``), which can post
data IN and cannot write to Shopee, so it does not count. Any failing check: ``masked``, with a
``reviewer_pin_sample_refused`` warning naming the reason. ``sample`` turns the identity mask
off (the names are synthetic) and nothing else: platform writes stay off, every sandbox-only
route refuses (``sandbox`` is False) and layer 2 stays per request. P100 S2-G: the Shopee routes
the gate admits on a sample pin (``api/reviewer.SAMPLE_SHOP_ROUTES``) include the seller's own
writes to Juli's rows of that shop (real Duyệt, Kế hoạch, …), never anything outbound. Tests:
``tests/unit/test_reviewer_sample_pin.py``, ``tests/unit/test_reviewer_sample_shopee.py``.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import SandboxWriteOwner, sandbox_write_owners
from juli_backend.integrations.tiktok import TikTokCapability
from juli_backend.models.ingestion import ShopIngestionState
from juli_backend.models.models import ProductionWriteShop, Shop, TikTokCredential
from juli_backend.services.reviewer import config

logger = logging.getLogger(__name__)

MODE_SANDBOX = "sandbox"
MODE_MASKED = "masked"
#: P100 S2-B: the synthetic Shopee sample shop -- unmasked, read-only, simulated.
MODE_SAMPLE = "sample"

#: Why reviewer writes are off for a pin (``PinMode.writes_disabled_reason``).
REASON_NOT_SANDBOX = "not_sandbox_shop"
REASON_PRODUCTION_READ = "pin_holds_production_read"
REASON_PRODUCTION_WRITE = "pin_has_production_write_row"
REASON_SANDBOX_REFUSED = "sandbox_credential_refused"
#: P100 S2-B: a sample pin's writes are off by design (it is not a platform shop).
REASON_SAMPLE_SHOP = "sample_shop"
#: P100 S2-B: why a pin listed in ``REVIEWER_SAMPLE_SHOP_IDS`` is masked instead of sample.
REASON_SAMPLE_REFUSED_SHOP = "sample_refused_shop"
REASON_SAMPLE_FACTS_MISSING = "sample_facts_missing"
REASON_SAMPLE_TIKTOK_CREDENTIAL = "sample_holds_tiktok_credential"
REASON_SAMPLE_PRODUCTION_WRITE = "sample_has_production_write_row"
REASON_SAMPLE_SANDBOX_OWNER = "sample_is_sandbox_shop"
REASON_SAMPLE_NOT_SHOPEE = "sample_not_shopee_shop"
REASON_SAMPLE_TIKTOK_LINKED = "sample_has_tiktok_shop_id"


@dataclass(frozen=True)
class PinMode:
    """What the pinned shop is, for the reviewer.

    Decided on a pin-cache miss and kept for the reviewer identity TTL (P69,
    ``services/reviewer/pin_cache``): a pin that becomes a production shop loses
    reviewer writes within that window; layer 2 (D73 Q6) is still checked per request.
    """

    mode: str
    writes_enabled: bool
    writes_disabled_reason: str | None = None

    @property
    def sandbox(self) -> bool:
        return self.mode == MODE_SANDBOX

    @property
    def sample(self) -> bool:
        return self.mode == MODE_SAMPLE

    @property
    def mask(self) -> bool:
        """D73 Q1/Q2: the identity mask is off only for Juli's own sandbox shop -- and (P100
        S2-B) the synthetic sample shop, whose names are synthetic."""
        return not (self.sandbox or self.sample)


@dataclass(frozen=True)
class PinShopFacts:
    """P100 S2-B: what the sample check needs from the pinned shop's own rows.

    ``credential_rows`` counts EVERY ``tiktok_credentials`` row of the shop, whatever its
    capability or status (a NULL capability included).
    """

    platform: str | None
    tiktok_linked: bool
    credential_rows: int

    @classmethod
    def of(cls, values: dict[str, Any], credential_rows: int) -> PinShopFacts:
        linked = values.get("tiktok_shop_id") or values.get("tiktok_numeric_shop_id")
        return cls(
            platform=values.get("platform"),
            tiktok_linked=bool(linked),
            credential_rows=credential_rows,
        )


async def classify_pin(session: AsyncSession, shop_id: uuid.UUID) -> PinMode:
    """The pinned shop's mode. The caller holds the shop's read scope (``enter_reviewer_shop``)."""
    owners = await sandbox_write_owners(session)
    owner = owners[0] if owners else None
    rows = list(
        (
            await session.execute(
                select(TikTokCredential.capability).where(TikTokCredential.shop_id == shop_id)
            )
        ).scalars()
    )
    production_write_row = (
        await session.execute(
            select(ProductionWriteShop.shop_id).where(ProductionWriteShop.shop_id == shop_id)
        )
    ).scalar_one_or_none() is not None
    facts: PinShopFacts | None = None
    if shop_id in config.reviewer_sample_shop_ids():
        # Only a sample-listed pin pays this read; every other pin keeps its round trips.
        found = (
            await session.execute(
                select(Shop.platform, Shop.tiktok_shop_id, Shop.tiktok_numeric_shop_id).where(
                    Shop.id == shop_id
                )
            )
        ).first()
        if found is not None:
            facts = PinShopFacts.of(dict(found._mapping), len(rows))
    return pin_mode(
        shop_id,
        sandbox_owner=owner,
        capabilities={row for row in rows if row is not None},
        production_write_row=production_write_row,
        shop=facts,
    )


def pin_mode(
    shop_id: uuid.UUID,
    *,
    sandbox_owner: SandboxWriteOwner | None,
    capabilities: set[str],
    production_write_row: bool,
    shop: PinShopFacts | None = None,
) -> PinMode:
    """The decision of :func:`classify_pin` from facts already read (P69b: one fused read).

    ``sandbox_owner`` is the FIRST (newest) ``sandbox_write`` owner, the one
    ``resolve_sandbox_write_credential`` uses; ``capabilities`` are the pinned shop's own
    credential capabilities; ``production_write_row`` whether it has a
    ``production_write_shops`` row; ``shop`` the sample check's facts (P100 S2-B; None:
    unknown, so never ``sample``).
    """
    base = _platform_pin_mode(
        shop_id,
        sandbox_owner=sandbox_owner,
        capabilities=capabilities,
        production_write_row=production_write_row,
    )
    if shop_id not in config.reviewer_sample_shop_ids():
        return base
    refusal = _sample_refusal(
        shop_id,
        sandbox_owner=sandbox_owner,
        capabilities=capabilities,
        production_write_row=production_write_row,
        shop=shop,
    )
    if refusal is None:
        return PinMode(MODE_SAMPLE, writes_enabled=False, writes_disabled_reason=REASON_SAMPLE_SHOP)
    # Fail closed: listed but not provably synthetic -- the P32 mask, never the sandbox's writes.
    logger.warning(
        "reviewer_pin_sample_refused", extra={"shop_id": str(shop_id), "reason": refusal}
    )
    return PinMode(MODE_MASKED, writes_enabled=False, writes_disabled_reason=refusal)


def _sample_refusal(
    shop_id: uuid.UUID,
    *,
    sandbox_owner: SandboxWriteOwner | None,
    capabilities: set[str],
    production_write_row: bool,
    shop: PinShopFacts | None,
) -> str | None:
    """Why a sample-listed pin is NOT the sample shop (None: every check holds)."""
    if shop_id in config.NEVER_SAMPLE_SHOP_IDS:
        return REASON_SAMPLE_REFUSED_SHOP
    if shop is None:
        return REASON_SAMPLE_FACTS_MISSING
    if shop.credential_rows > 0 or capabilities:
        return REASON_SAMPLE_TIKTOK_CREDENTIAL
    if production_write_row:
        return REASON_SAMPLE_PRODUCTION_WRITE
    if sandbox_owner is not None and sandbox_owner.shop_id == shop_id:
        return REASON_SAMPLE_SANDBOX_OWNER
    if shop.platform != "shopee":
        return REASON_SAMPLE_NOT_SHOPEE
    if shop.tiktok_linked:
        return REASON_SAMPLE_TIKTOK_LINKED
    return None


def _platform_pin_mode(
    shop_id: uuid.UUID,
    *,
    sandbox_owner: SandboxWriteOwner | None,
    capabilities: set[str],
    production_write_row: bool,
) -> PinMode:
    """``sandbox`` or ``masked`` (P64 / P74-A), before the sample check."""
    owner = sandbox_owner
    reason: str | None = None
    if TikTokCapability.PRODUCTION_READ.value in capabilities:
        reason = REASON_PRODUCTION_READ
    elif production_write_row:
        reason = REASON_PRODUCTION_WRITE
    if reason is not None:
        # Fail closed (D73 Q6 layer 1): a reviewer must never sit on a seller's shop with
        # writes on. P74-A (D77): a production pin is now EXPECTED -- Fujiwa is the masked
        # default pin -- so that is a warning (on each pin-cache miss). Loud (an error) only
        # when the shop is the sandbox credential's own shop: the sandbox turned production.
        sandbox_turned_production = owner is not None and owner.shop_id == shop_id
        logger.log(
            logging.ERROR if sandbox_turned_production else logging.WARNING,
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

    # P73: an order-only sync (the commerce steps) moves no analytics endpoint's success time;
    # the card's "Đồng bộ lúc" is the latest sync of ANY kind. Read in the credential's
    # statement (P73b) so the route keeps its round-trip budget; with no credential the
    # shop cannot sync, so no connection means no commerce time either.
    commerce_last_run_at = (
        select(ShopIngestionState.commerce_last_run_at)
        .where(ShopIngestionState.shop_id == shop_id)
        .scalar_subquery()
    )
    row = (
        await session.execute(
            select(TikTokCredential, commerce_last_run_at)
            .where(TikTokCredential.shop_id == shop_id)
            .order_by(TikTokCredential.created_at.desc())
            .limit(1)
        )
    ).first()
    credential, commerce_at = (row[0], row[1]) if row is not None else (None, None)
    states = list(
        (
            await session.execute(
                select(TikTokSyncState)
                .where(TikTokSyncState.shop_id == shop_id)
                .order_by(TikTokSyncState.endpoint)
            )
        ).scalars()
    )
    successes = [
        _utc(state.last_success_at) for state in states if state.last_success_at is not None
    ]
    if commerce_at is not None:
        successes.append(_utc(commerce_at))
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


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "MODE_MASKED",
    "MODE_SAMPLE",
    "MODE_SANDBOX",
    "REASON_NOT_SANDBOX",
    "REASON_PRODUCTION_READ",
    "REASON_PRODUCTION_WRITE",
    "REASON_SAMPLE_FACTS_MISSING",
    "REASON_SAMPLE_NOT_SHOPEE",
    "REASON_SAMPLE_PRODUCTION_WRITE",
    "REASON_SAMPLE_REFUSED_SHOP",
    "REASON_SAMPLE_SANDBOX_OWNER",
    "REASON_SAMPLE_SHOP",
    "REASON_SAMPLE_TIKTOK_CREDENTIAL",
    "REASON_SAMPLE_TIKTOK_LINKED",
    "REASON_SANDBOX_REFUSED",
    "SYNC_INTERVAL_SECONDS",
    "PinMode",
    "PinShopFacts",
    "claim_sync_slot",
    "classify_pin",
    "pin_mode",
    "connection_info",
    "forget_sync_slots",
    "release_sync_slot",
]
