"""Ops "Tổng quan" (D25.5): totals and one row per shop.

The shop list comes from the SECURITY DEFINER ``ops_list_shops()`` (juli_ops
only); each shop's numbers are read under THAT shop's scope
(``with_shop_scope``), so every tenant read still goes through RLS one shop at
a time -- the ADR-089 shape. No buyer data is read.

D27.1 (P18): the per-shop numbers are computed ONCE A DAY -- right after the
shop's daily diagnosis build (new analytics days landed) -- and stored in
``ops_shop_daily_summary`` (:func:`refresh_shop_summary`). The overview reads
every summary row in one query beside the listing; a shop with no row yet is
computed live once and stored. "Làm mới" (``POST /v1/ops/overview/refresh``)
recomputes every shop. Stage and pending invites stay live (ops tables, one
query each). ``active`` is judged against the summary's ``generated_at``, the
moment the numbers describe.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import JSONB
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
from juli_backend.models.ops import (
    STAGE_LABELS,
    STAGE_TRIAL,
    OpsShopDailySummary,
    OpsShopInvite,
    OpsShopSettings,
)
from juli_backend.models.shop_diagnosis import ShopDailyStream, ShopDiagnosisReport
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
    #: D27.1: when these numbers were computed, and the last analytics day they cover.
    generated_at: datetime | None = None
    data_through: date | None = None

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
        reference = self.generated_at or now
        return self.last_poll_at is not None and reference - self.last_poll_at <= ACTIVE_WITHIN

    def numbers(self) -> dict[str, Any]:
        """The stored part (``ops_shop_daily_summary.payload``), JSON-ready."""
        return {
            "connection": self.connection,
            "last_poll_at": _iso(self.last_poll_at),
            "last_diagnosis_at": _iso(self.last_diagnosis_at),
            "cards_open": self.cards_open,
            "cards_approved_30d": self.cards_approved_30d,
            "cards_rejected_30d": self.cards_rejected_30d,
            "failed_runs_30d": self.failed_runs_30d,
            "openai_cost_month_usd": str(self.openai_cost_month_usd),
            "openai_cap_usd": None if self.openai_cap_usd is None else str(self.openai_cap_usd),
            "gmv_30d": self.gmv_30d,
            "permissions": self.extra.get("permissions"),
        }

    def load_numbers(self, summary: Any) -> None:
        """From an ``OpsShopDailySummary`` (or anything with its three columns)."""
        data = summary.payload if isinstance(summary.payload, dict) else {}
        self.connection = str(data.get("connection") or CONN_NONE)
        self.last_poll_at = _parse_dt(data.get("last_poll_at"))
        self.last_diagnosis_at = _parse_dt(data.get("last_diagnosis_at"))
        self.cards_open = int(data.get("cards_open") or 0)
        self.cards_approved_30d = int(data.get("cards_approved_30d") or 0)
        self.cards_rejected_30d = int(data.get("cards_rejected_30d") or 0)
        self.failed_runs_30d = int(data.get("failed_runs_30d") or 0)
        self.openai_cost_month_usd = Decimal(str(data.get("openai_cost_month_usd") or "0"))
        cap = data.get("openai_cap_usd")
        self.openai_cap_usd = None if cap is None else Decimal(str(cap))
        gmv = data.get("gmv_30d")
        self.gmv_30d = None if gmv is None else float(gmv)
        self.extra["permissions"] = data.get("permissions")
        self.generated_at = summary.generated_at
        self.data_through = summary.data_through

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
            "generated_at": _iso(self.generated_at),
            "data_through": self.data_through.isoformat() if self.data_through else None,
        }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


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
    return [_listing_from_row(row) for row in rows_pg]


def _listing_from_row(row: Any) -> ShopListing:
    return ShopListing(
        shop_id=row["out_shop_id"],
        shop_name=row["out_shop_name"],
        tiktok_shop_id=row["out_tiktok_shop_id"],
        is_active=bool(row["out_is_active"]),
        owner_user_id=row["out_owner_user_id"],
        owner_email=row["out_owner_email"],
        owner_consent_at=row["out_owner_consent_at"],
    )


async def find_shop(session: AsyncSession, shop_id: uuid.UUID) -> ShopListing | None:
    """One shop's listing (``ops_find_shop``, migration 085) -- never lists every shop."""
    if is_sqlite(session):
        found = (
            await session.execute(
                select(Shop, User).join(User, User.id == Shop.user_id).where(Shop.id == shop_id)
            )
        ).first()
        if found is None:
            return None
        shop, user = found
        return ShopListing(
            shop_id=shop.id,
            shop_name=shop.shop_name,
            tiktok_shop_id=shop.tiktok_shop_id,
            is_active=shop.is_active,
            owner_user_id=user.id,
            owner_email=user.email,
            owner_consent_at=user.staff_access_consent_at,
        )
    async with ops_role(session):
        result = await session.execute(
            text("SELECT * FROM public.ops_find_shop(:shop_id)"), {"shop_id": shop_id}
        )
        row = result.mappings().first()
    return None if row is None else _listing_from_row(row)


_FIND_SHOP_COLUMNS = (
    "out_shop_id",
    "out_shop_name",
    "out_tiktok_shop_id",
    "out_is_active",
    "out_owner_user_id",
    "out_owner_email",
    "out_owner_consent_at",
)


async def find_shop_and_settings(
    session: AsyncSession, shop_id: uuid.UUID
) -> tuple[ShopListing | None, OpsShopSettings | None]:
    """The listing AND the ``ops_shop_settings`` row in ONE statement (P29).

    ``ops_find_shop`` LEFT JOIN the settings row: the two reads every per-shop
    Ops page made back to back, ~395 ms each from the VPS. Both are ops reads
    (``juli_ops``); nothing tenant-scoped is touched. The settings row comes
    back as an ORM entity, exactly what ``ops_settings.settings_row`` returns.
    """
    if is_sqlite(session):
        listing = await find_shop(session, shop_id)
        if listing is None:
            return None, None
        async with ops_role(session):
            return listing, await session.get(OpsShopSettings, shop_id)
    found = func.ops_find_shop(shop_id).table_valued(*_FIND_SHOP_COLUMNS).alias("f")
    stmt = select(found, OpsShopSettings).outerjoin(
        OpsShopSettings, OpsShopSettings.shop_id == found.c.out_shop_id
    )
    async with ops_role(session):
        row = (await session.execute(stmt)).first()
    if row is None:
        return None, None
    return _listing_from_row(row._mapping), row._mapping[OpsShopSettings]


# Find the shop AND enter the seller's own tenant scope, in ONE statement (P29).
#
# "Xem như shop" used to read the listing as ``juli_ops`` and then, in a second
# statement, switch the role back and set the shop + owner GUCs from it. The
# FROM clause here runs ``ops_find_shop`` -- its EXECUTE privilege is checked at
# executor start, while the transaction is still ``juli_ops`` -- and the
# projection, evaluated only once the function scan has produced the row, does
# exactly what ``_apply_tenant_context_to_session(restore_role=...)`` does with
# the values just read. No row (unknown shop) means no ``set_config`` ran at
# all: the caller restores the role itself before answering 404.
_FIND_AND_ENTER_SQL = (
    "SELECT f.out_shop_id, f.out_shop_name, f.out_tiktok_shop_id, f.out_is_active, "  # nosec B608
    "f.out_owner_user_id, f.out_owner_email, f.out_owner_consent_at, "
    "set_config('role', :role, true), "
    "set_config(:shop_key, f.out_shop_id::text, true), "
    "set_config(:user_key, coalesce(f.out_owner_user_id::text, ''), true) "
    "FROM public.ops_find_shop(:shop_id) AS f"
)


async def find_shop_entering_seller_scope(
    session: AsyncSession, shop_id: uuid.UUID, *, restore_role: str
) -> ShopListing | None:
    """``find_shop``, then the seller's scope (shop + owner) and ``restore_role``.

    For a caller inside an ``ops_role`` block whose restore it took over
    (``OpsRoleBlock.hand_over``). On ``None`` the role is STILL ``juli_ops``
    and the GUCs are untouched; :func:`leave_ops_role` puts the role back.
    """
    from juli_backend.database.tenant_context import (
        _SHOP_GUC,
        _USER_GUC,
        _require_tenant_context,
    )

    row = (
        (
            await session.execute(
                text(_FIND_AND_ENTER_SQL).bindparams(
                    role=restore_role, shop_key=_SHOP_GUC, user_key=_USER_GUC, shop_id=shop_id
                )
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    listing = _listing_from_row(row)
    # The same fail-closed decision `_apply_tenant_context_to_session` makes; a
    # shop with no owner would have left the user GUC empty (every user-keyed
    # policy denies), and is refused here before any tenant read runs.
    _require_tenant_context(listing.shop_id, listing.owner_user_id)
    return listing


async def leave_ops_role(session: AsyncSession, role: str) -> None:
    """Switch back from ``juli_ops`` after a handed-over block found nothing."""
    await session.execute(text("SELECT set_config('role', :role, true)").bindparams(role=role))


async def _shop_numbers(session: AsyncSession, row: ShopRow, now: datetime) -> None:
    """One shop's numbers (caller holds the shop's scope), in four statements.

    P22: these were fourteen sequential reads -- ~3 s per shop at the
    production pooler's ~220 ms a round trip, paid by every "Làm mới" and by
    the first overview after a shop connects. The eight aggregates are now
    scalar subqueries of ONE statement, and the credential rows are read once
    for both the connection state and the permissions. Every read is still the
    caller's shop scope under RLS; nothing here widens what is visible.
    """
    from juli_backend.services.ops.scopes import status_from_credentials

    shop_id = row.listing.shop_id
    since = now - timedelta(days=WINDOW_DAYS)
    creds = (
        await session.execute(
            select(
                TikTokCredential.status,
                TikTokCredential.refresh_token_expires_at,
                TikTokCredential.scopes,
            ).where(TikTokCredential.shop_id == shop_id)
        )
    ).all()
    if not creds:
        row.connection = CONN_NONE
    elif any(
        status == "active" and (expires is None or expires > now) for status, expires, _ in creds
    ):
        row.connection = CONN_OK
    else:
        row.connection = CONN_EXPIRED

    def count(model: Any, *where: Any) -> Any:
        return select(func.count()).select_from(model).where(*where).scalar_subquery()

    def newest(column: Any, *where: Any) -> Any:
        return select(func.max(column)).where(*where).scalar_subquery()

    numbers = (
        await session.execute(
            select(
                newest(TikTokSyncState.last_success_at, TikTokSyncState.shop_id == shop_id),
                newest(ShopDiagnosisReport.built_at, ShopDiagnosisReport.shop_id == shop_id),
                count(
                    ActionCard,
                    ActionCard.shop_id == shop_id,
                    ActionCard.status == "active",
                    ActionCard.surfaced_at.is_not(None),
                ),
                count(
                    WorkflowRun,
                    WorkflowRun.shop_id == shop_id,
                    WorkflowRun.action_card_id.is_not(None),
                    WorkflowRun.created_at >= since,
                ),
                count(
                    DecisionReason,
                    DecisionReason.shop_id == shop_id,
                    DecisionReason.action == ACTION_REJECT,
                    DecisionReason.decided_at >= since,
                ),
                count(
                    WorkflowRun,
                    WorkflowRun.shop_id == shop_id,
                    WorkflowRun.status.in_(FAILED_RUN_STATUSES),
                    WorkflowRun.created_at >= since,
                ),
                newest(ShopDailyStream.day, ShopDailyStream.shop_id == shop_id),
                newest(ShopDiagnosisReport.end_date, ShopDiagnosisReport.shop_id == shop_id),
            )
        )
    ).one()
    (
        row.last_poll_at,
        row.last_diagnosis_at,
        cards_open,
        approved,
        rejected,
        failed,
        stream_through,
        report_through,
    ) = numbers
    row.cards_open = int(cards_open or 0)
    row.cards_approved_30d = int(approved or 0)
    row.cards_rejected_30d = int(rejected or 0)
    row.failed_runs_30d = int(failed or 0)
    row.data_through = stream_through or report_through
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
    row.extra["permissions"] = status_from_credentials(
        [(scopes, status) for status, _, scopes in creds]
    ).to_json()


def _gmv_last_days(report: Any, days: int) -> float | None:
    if not isinstance(report, dict):
        return None
    daily = report.get("daily_gmv")
    if not isinstance(daily, dict) or not daily:
        return None
    keys = sorted(daily)[-days:]
    return float(sum(float(daily[k] or 0) for k in keys))


def _naive_utc(now: datetime | None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None)


async def _computed_row(session: AsyncSession, shop_id: uuid.UUID, current: datetime) -> ShopRow:
    """One shop's numbers, read under that shop's own scope (ADR-089)."""
    placeholder = ShopListing(
        shop_id=shop_id,
        shop_name="",
        tiktok_shop_id=None,
        is_active=True,
        owner_user_id=shop_id,
        owner_email=None,
        owner_consent_at=None,
    )
    row = ShopRow(listing=placeholder)
    async with with_shop_scope(session, shop_id):
        await _shop_numbers(session, row, current)
    return row


def _store_summary(
    session: AsyncSession,
    shop_id: uuid.UUID,
    row: ShopRow,
    current: datetime,
    summary: OpsShopDailySummary | None,
) -> OpsShopDailySummary:
    """Write ``row``'s numbers into ``summary`` (new when None); inside an ops block."""
    if summary is None:
        summary = OpsShopDailySummary(shop_id=shop_id)
        session.add(summary)
    summary.payload = row.numbers()
    summary.data_through = row.data_through
    summary.generated_at = current
    return summary


async def refresh_shop_summary(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime | None = None
) -> OpsShopDailySummary:
    """Compute one shop's numbers now and store them (upsert; no commit)."""
    current = _naive_utc(now)
    row = await _computed_row(session, shop_id, current)
    async with ops_role(session):
        summary = await session.get(OpsShopDailySummary, shop_id)
        return _store_summary(session, shop_id, row, current, summary)


# Tổng quan's four ops reads -- the shop list, every stage, the pending
# invites, every stored summary -- as ONE statement (P29; they were four, ~1.2 s
# more from the VPS). ``WITH ORDINALITY`` keeps ``ops_list_shops()``'s own order
# (by shop creation) through the joins.
_OVERVIEW_SQL = """
SELECT f.out_shop_id, f.out_shop_name, f.out_tiktok_shop_id, f.out_is_active,
       f.out_owner_user_id, f.out_owner_email, f.out_owner_consent_at,
       s.stage AS stage,
       EXISTS (
           SELECT 1 FROM public.ops_shop_invites i
           WHERE i.shop_id = f.out_shop_id AND i.accepted_at IS NULL
             AND i.revoked_at IS NULL AND i.expires_at > :now
       ) AS invite_pending,
       d.shop_id IS NOT NULL AS has_summary,
       d.payload AS payload, d.data_through AS data_through, d.generated_at AS generated_at
FROM public.ops_list_shops() WITH ORDINALITY AS f(
    out_shop_id, out_shop_name, out_tiktok_shop_id, out_is_active, out_created_at,
    out_owner_user_id, out_owner_email, out_owner_consent_at, ord)
LEFT JOIN public.ops_shop_settings s ON s.shop_id = f.out_shop_id
LEFT JOIN public.ops_shop_daily_summary d ON d.shop_id = f.out_shop_id
ORDER BY f.ord
"""


@dataclass(frozen=True)
class _StoredSummary:
    """A summary row's three columns, read without loading the ORM entity."""

    payload: Any
    data_through: date | None
    generated_at: datetime | None


async def _overview_fused(
    session: AsyncSession, current: datetime, *, transaction_ends_after: bool
) -> tuple[list[ShopListing], dict[uuid.UUID, str], set[uuid.UUID], dict[uuid.UUID, Any]]:
    """The four ops reads in one statement.

    Leaves ``juli_ops`` before returning unless nothing else will run in this
    transaction (``transaction_ends_after`` and every shop has a summary).
    """
    stmt = text(_OVERVIEW_SQL).columns(payload=JSONB)
    async with ops_role(session) as block:
        rows = list((await session.execute(stmt, {"now": current})).mappings())
        previous_role = block.hand_over()
    listings: list[ShopListing] = []
    stages: dict[uuid.UUID, str] = {}
    pending: set[uuid.UUID] = set()
    summaries: dict[uuid.UUID, Any] = {}
    for row in rows:
        listing = _listing_from_row(row)
        listings.append(listing)
        if row["stage"] is not None:
            stages[listing.shop_id] = row["stage"]
        if row["invite_pending"]:
            pending.add(listing.shop_id)
        if row["has_summary"]:
            summaries[listing.shop_id] = _StoredSummary(
                payload=row["payload"],
                data_through=row["data_through"],
                generated_at=row["generated_at"],
            )
    missing = any(listing.shop_id not in summaries for listing in listings)
    if previous_role is not None and (missing or not transaction_ends_after):
        # More statements follow (a missing summary is computed under the
        # shop's own scope, as juli_app): leave juli_ops first.
        await leave_ops_role(session, previous_role)
    return listings, stages, pending, summaries


async def build_overview(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    refresh: bool = False,
    transaction_ends_after: bool = False,
) -> dict[str, Any]:
    """Tổng quan from the stored daily summaries (D27.1); ``refresh`` recomputes every shop.

    Writes a summary for any shop that has none (and every shop on refresh):
    the caller commits. ``transaction_ends_after`` (P29): the caller commits
    right after, so a final ``juli_ops`` role restore is skipped.
    """
    current = _naive_utc(now)
    if not refresh and not is_sqlite(session):
        listings, stage_of, pending, summaries = await _overview_fused(
            session, current, transaction_ends_after=transaction_ends_after
        )
        computed = {
            listing.shop_id: await _computed_row(session, listing.shop_id, current)
            for listing in listings
            if listing.shop_id not in summaries
        }
        if computed:
            async with ops_role(session, transaction_ends_after=transaction_ends_after):
                for shop_id, numbers in computed.items():
                    summaries[shop_id] = _store_summary(session, shop_id, numbers, current, None)
        return _overview_body(listings, stage_of, pending, summaries, current)
    # ONE ops block for the listing and the three ops tables (P22): ops_role is
    # re-entrant, so list_shops' own block costs nothing in here.
    async with ops_role(session):
        listings = await list_shops(session)
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
        summaries = {
            s.shop_id: s
            for s in (await session.execute(select(OpsShopDailySummary))).scalars().all()
        }
    # Shops with no summary yet (or every shop on refresh) are computed one at a
    # time, each under its OWN shop scope -- that is ADR-089, not an N+1 to
    # remove -- and then stored together in ONE ops block rather than one
    # role switch per shop (P22).
    computed = {
        listing.shop_id: await _computed_row(session, listing.shop_id, current)
        for listing in listings
        if refresh or listing.shop_id not in summaries
    }
    if computed:
        async with ops_role(session):
            for shop_id, numbers in computed.items():
                summaries[shop_id] = _store_summary(
                    session, shop_id, numbers, current, summaries.get(shop_id)
                )
    return _overview_body(
        listings, {k: v.stage for k, v in settings.items()}, pending, summaries, current
    )


def _overview_body(
    listings: list[ShopListing],
    stage_of: dict[uuid.UUID, str],
    pending: set[uuid.UUID],
    summaries: dict[uuid.UUID, Any],
    current: datetime,
) -> dict[str, Any]:
    rows: list[ShopRow] = []
    for listing in listings:
        row = ShopRow(listing=listing)
        stage = stage_of.get(listing.shop_id)
        if stage is not None:
            row.stage = stage
        row.invite_pending = listing.shop_id in pending
        row.load_numbers(summaries[listing.shop_id])
        rows.append(row)
    connected = [r for r in rows if r.connection != CONN_NONE]
    approved = sum(r.cards_approved_30d for r in rows)
    rejected = sum(r.cards_rejected_30d for r in rows)
    generated = [r.generated_at for r in rows if r.generated_at is not None]
    return {
        # D27.1: the OLDEST summary shown ("cập nhật lúc"), and the last analytics day.
        "generated_at": (min(generated) if generated else current).isoformat(),
        "data_through": _data_through(rows),
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


def _data_through(rows: list[ShopRow]) -> str | None:
    """The oldest last-analytics-day among connected shops (else among all), ISO."""
    connected = [r.data_through for r in rows if r.connection == CONN_OK and r.data_through]
    days = connected or [r.data_through for r in rows if r.data_through]
    return min(days).isoformat() if days else None
