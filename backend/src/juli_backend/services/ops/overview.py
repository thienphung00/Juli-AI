"""Ops "Tổng quan" (D25.5): totals and one row per shop.

The shop list comes from the SECURITY DEFINER ``ops_list_shops()`` (juli_ops
only); each shop's numbers are then read under THAT shop's scope
(``with_shop_scope``), so every tenant read still goes through RLS one shop at
a time -- the ADR-089 shape. No buyer data is read.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.decision_reasons import ACTION_REJECT, DecisionReason
from juli_backend.models.models import (
    ActionCard,
    Shop,
    TikTokCredential,
    TikTokSyncState,
    User,
    WorkflowRun,
)
from juli_backend.models.ops import STAGE_LABELS, STAGE_TRIAL, OpsShopInvite, OpsShopSettings
from juli_backend.models.shop_diagnosis import ShopDiagnosisReport
from juli_backend.services.ops import overrides as ov
from juli_backend.services.ops.access import is_sqlite, ops_role
from juli_backend.services.ops.masking import STAFF_DOMAIN

ACTIVE_WITHIN = timedelta(hours=24)
WINDOW_DAYS = 30
CONN_OK = "ok"
CONN_EXPIRED = "expired"
CONN_NONE = "none"
FAILED_RUN_STATUSES = ("failed", "timed_out")


@dataclass(frozen=True)
class ShopListing:
    shop_id: uuid.UUID
    shop_name: str
    tiktok_shop_id: str | None
    is_active: bool
    owner_user_id: uuid.UUID
    owner_email: str | None
    owner_consent_at: datetime | None


@dataclass
class ShopRow:
    listing: ShopListing
    stage: str = STAGE_TRIAL
    connection: str = CONN_NONE
    last_poll_at: datetime | None = None
    last_diagnosis_at: datetime | None = None
    cards_open: int = 0
    cards_approved_30d: int = 0
    cards_rejected_30d: int = 0
    failed_runs_30d: int = 0
    openai_cost_month_usd: Decimal = Decimal("0")
    openai_cap_usd: Decimal | None = None
    gmv_30d: float | None = None
    invite_pending: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def approval_rate(self) -> float | None:
        decided = self.cards_approved_30d + self.cards_rejected_30d
        return None if decided == 0 else self.cards_approved_30d / decided

    @property
    def cap_reached(self) -> bool:
        return self.openai_cap_usd is not None and self.openai_cost_month_usd >= self.openai_cap_usd

    @property
    def owned_by_team(self) -> bool:
        email = (self.listing.owner_email or "").lower()
        return email.endswith("@" + STAFF_DOMAIN)

    def active(self, now: datetime) -> bool:
        return self.last_poll_at is not None and now - self.last_poll_at <= ACTIVE_WITHIN

    def to_json(self, now: datetime) -> dict[str, Any]:
        return {
            "shop_id": str(self.listing.shop_id),
            "shop_name": self.listing.shop_name,
            "tiktok_shop_id": self.listing.tiktok_shop_id,
            "owner_email": self.listing.owner_email,
            "owned_by_team": self.owned_by_team,
            "invite_pending": self.invite_pending,
            "staff_access_consent_at": _iso(self.listing.owner_consent_at),
            "stage": self.stage,
            "stage_label": STAGE_LABELS.get(self.stage, self.stage),
            "connection": self.connection,
            "active": self.active(now),
            "last_poll_at": _iso(self.last_poll_at),
            "last_diagnosis_at": _iso(self.last_diagnosis_at),
            "cards_open": self.cards_open,
            "cards_approved_30d": self.cards_approved_30d,
            "cards_rejected_30d": self.cards_rejected_30d,
            "approval_rate": self.approval_rate,
            "failed_runs_30d": self.failed_runs_30d,
            "openai_cost_month_usd": float(self.openai_cost_month_usd),
            "openai_cap_usd": float(self.openai_cap_usd)
            if self.openai_cap_usd is not None
            else None,
            "openai_cap_reached": self.cap_reached,
            "gmv_30d": self.gmv_30d,
            "permissions": self.extra.get("permissions"),
        }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def list_shops(session: AsyncSession) -> list[ShopListing]:
    if is_sqlite(session):
        rows = (
            await session.execute(
                select(Shop, User).join(User, User.id == Shop.user_id).order_by(Shop.created_at)
            )
        ).all()
        return [
            ShopListing(
                shop_id=shop.id,
                shop_name=shop.shop_name,
                tiktok_shop_id=shop.tiktok_shop_id,
                is_active=shop.is_active,
                owner_user_id=user.id,
                owner_email=user.email,
                owner_consent_at=user.staff_access_consent_at,
            )
            for shop, user in rows
        ]
    async with ops_role(session):
        result = (await session.execute(text("SELECT * FROM public.ops_list_shops()"))).mappings()
        rows_pg = list(result)
    return [
        ShopListing(
            shop_id=row["out_shop_id"],
            shop_name=row["out_shop_name"],
            tiktok_shop_id=row["out_tiktok_shop_id"],
            is_active=bool(row["out_is_active"]),
            owner_user_id=row["out_owner_user_id"],
            owner_email=row["out_owner_email"],
            owner_consent_at=row["out_owner_consent_at"],
        )
        for row in rows_pg
    ]


async def find_shop(session: AsyncSession, shop_id: uuid.UUID) -> ShopListing | None:
    for listing in await list_shops(session):
        if listing.shop_id == shop_id:
            return listing
    return None


async def _shop_numbers(session: AsyncSession, row: ShopRow, now: datetime) -> None:
    shop_id = row.listing.shop_id
    since = now - timedelta(days=WINDOW_DAYS)
    creds = (
        await session.execute(
            select(TikTokCredential.status, TikTokCredential.refresh_token_expires_at).where(
                TikTokCredential.shop_id == shop_id
            )
        )
    ).all()
    if not creds:
        row.connection = CONN_NONE
    elif any(
        status == "active" and (expires is None or expires > now) for status, expires in creds
    ):
        row.connection = CONN_OK
    else:
        row.connection = CONN_EXPIRED
    row.last_poll_at = (
        await session.execute(
            select(func.max(TikTokSyncState.last_success_at)).where(
                TikTokSyncState.shop_id == shop_id
            )
        )
    ).scalar_one()
    row.last_diagnosis_at = (
        await session.execute(
            select(func.max(ShopDiagnosisReport.built_at)).where(
                ShopDiagnosisReport.shop_id == shop_id
            )
        )
    ).scalar_one()
    row.cards_open = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ActionCard)
                .where(
                    ActionCard.shop_id == shop_id,
                    ActionCard.status == "active",
                    ActionCard.surfaced_at.is_not(None),
                )
            )
        ).scalar_one()
    )
    row.cards_approved_30d = int(
        (
            await session.execute(
                select(func.count())
                .select_from(WorkflowRun)
                .where(
                    WorkflowRun.shop_id == shop_id,
                    WorkflowRun.action_card_id.is_not(None),
                    WorkflowRun.created_at >= since,
                )
            )
        ).scalar_one()
    )
    row.cards_rejected_30d = int(
        (
            await session.execute(
                select(func.count())
                .select_from(DecisionReason)
                .where(
                    DecisionReason.shop_id == shop_id,
                    DecisionReason.action == ACTION_REJECT,
                    DecisionReason.decided_at >= since,
                )
            )
        ).scalar_one()
    )
    row.failed_runs_30d = int(
        (
            await session.execute(
                select(func.count())
                .select_from(WorkflowRun)
                .where(
                    WorkflowRun.shop_id == shop_id,
                    WorkflowRun.status.in_(FAILED_RUN_STATUSES),
                    WorkflowRun.created_at >= since,
                )
            )
        ).scalar_one()
    )
    cap = await ov.openai_cap_status(session, shop_id, now=now.replace(tzinfo=UTC))
    row.openai_cost_month_usd = cap.spent_usd
    row.openai_cap_usd = cap.cap_usd
    report = (
        (
            await session.execute(
                select(ShopDiagnosisReport.report)
                .where(ShopDiagnosisReport.shop_id == shop_id)
                .order_by(ShopDiagnosisReport.end_date.desc(), ShopDiagnosisReport.built_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    row.gmv_30d = _gmv_last_days(report, WINDOW_DAYS)
    from juli_backend.services.ops.scopes import shop_scope_status

    row.extra["permissions"] = (await shop_scope_status(session, shop_id)).to_json()


def _gmv_last_days(report: Any, days: int) -> float | None:
    if not isinstance(report, dict):
        return None
    daily = report.get("daily_gmv")
    if not isinstance(daily, dict) or not daily:
        return None
    keys = sorted(daily)[-days:]
    return float(sum(float(daily[k] or 0) for k in keys))


async def build_overview(session: AsyncSession, *, now: datetime | None = None) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None)
    listings = await list_shops(session)
    async with ops_role(session):
        settings = {
            s.shop_id: s for s in (await session.execute(select(OpsShopSettings))).scalars().all()
        }
        pending = set(
            (
                await session.execute(
                    select(OpsShopInvite.shop_id).where(
                        OpsShopInvite.accepted_at.is_(None),
                        OpsShopInvite.revoked_at.is_(None),
                        OpsShopInvite.expires_at > current,
                    )
                )
            )
            .scalars()
            .all()
        )
    rows: list[ShopRow] = []
    for listing in listings:
        row = ShopRow(listing=listing)
        cfg = settings.get(listing.shop_id)
        if cfg is not None:
            row.stage = cfg.stage
        row.invite_pending = listing.shop_id in pending
        async with with_shop_scope(session, listing.shop_id):
            await _shop_numbers(session, row, current)
        rows.append(row)
    connected = [r for r in rows if r.connection != CONN_NONE]
    approved = sum(r.cards_approved_30d for r in rows)
    rejected = sum(r.cards_rejected_30d for r in rows)
    return {
        "generated_at": current.isoformat(),
        "totals": {
            "accounts": len(rows),
            "connected": len(connected),
            "active": sum(1 for r in rows if r.connection == CONN_OK and r.active(current)),
            "disconnected": sum(1 for r in rows if r.connection == CONN_EXPIRED),
            "cards_approved_30d": approved,
            "approval_rate_30d": None
            if approved + rejected == 0
            else approved / (approved + rejected),
            "openai_cost_month_usd": float(
                sum((r.openai_cost_month_usd for r in rows), Decimal("0"))
            ),
            "openai_cap_alerts": sum(1 for r in rows if r.cap_reached),
        },
        "shops": [r.to_json(current) for r in rows],
    }
