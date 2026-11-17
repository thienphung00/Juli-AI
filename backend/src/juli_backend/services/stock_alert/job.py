"""The 07:00 GMT+7 stock e-mail (Part S): one per shop per local day, idempotent.

``run_shop`` (inside the shop's tenant scope; the caller commits):

1. settings: ``off`` (default) or the reviewer's sample shop -> nothing; ``preview`` -> the Ops
   address only; ``on`` -> every member (``recipients``), Ops in BCC for the first 14 days.
2. a ``shopee_stock_alert_sends`` row for (shop, local day) already exists -> nothing. The row is
   written BEFORE the mail goes out, so a second run (or a parallel one) can never send twice.
3. the variations' facts (``data``), the "Theo dõi" defaults stored (``settings.sync_defaults``),
   the eligible tracked ones that trigger (``eligibility``) -> ``alert`` or ``empty``; no variation
   with a usable stock read -> ``no_read``.
4. the rows not in yesterday's e-mail first ("Mới hôm nay"), then the rest ("Đang sắp hết");
   a variation is listed every morning while it triggers.
5. one message per recipient (each carries their own unsubscribe link).

No SMTP host: the row is still written (the day is "done") and the job logs
``stock_alert_mail_not_configured``; nothing is sent.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.stock_alert import (
    KIND_ALERT,
    KIND_EMPTY,
    KIND_NO_READ,
    ShopeeStockAlertSend,
)
from juli_backend.services.stock_alert import data, links, recipients, settings
from juli_backend.services.stock_alert import stock_basis as sb
from juli_backend.services.stock_alert.compose import compose, row_line, row_title
from juli_backend.services.stock_alert.eligibility import alerts, is_eligible, split_new
from juli_backend.services.stock_alert.mail import (
    StockMail,
    StockMailer,
    get_stock_mailer,
    send_all,
)

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Any]


@dataclass(frozen=True)
class ShopRun:
    status: str
    kind: str | None = None
    rows: int = 0
    recipients: int = 0
    sent: int = 0


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _first_send_day(session: AsyncSession, shop_id: uuid.UUID) -> date | None:
    return await session.scalar(
        select(func.min(ShopeeStockAlertSend.local_date)).where(
            ShopeeStockAlertSend.shop_id == shop_id, ShopeeStockAlertSend.preview.is_(False)
        )
    )


async def _already_sent(session: AsyncSession, shop_id: uuid.UUID, day: date) -> bool:
    found = await session.scalar(
        select(ShopeeStockAlertSend.id).where(
            ShopeeStockAlertSend.shop_id == shop_id, ShopeeStockAlertSend.local_date == day
        )
    )
    return found is not None


async def _previous_keys(session: AsyncSession, shop_id: uuid.UUID, today: date) -> set[str] | None:
    """The variations listed in yesterday's e-mail; None when nothing went out yesterday."""
    row = await session.scalar(
        select(ShopeeStockAlertSend).where(
            ShopeeStockAlertSend.shop_id == shop_id,
            ShopeeStockAlertSend.local_date == today - timedelta(days=1),
        )
    )
    if row is None:
        return None
    return {str(r.get("key")) for r in row.rows or [] if isinstance(r, dict) and r.get("key")}


async def run_shop(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    now: datetime | None = None,
    mailer: StockMailer | None = None,
) -> ShopRun:
    moment = (now or _now()).replace(tzinfo=None)
    today = sb.local_day(moment)
    conf = await settings.load_settings(session, shop_id)
    if not conf.sends:
        return ShopRun("sample" if conf.sample else "off")
    if await _already_sent(session, shop_id, today):
        return ShopRun("already_sent")

    states, _catalog = await data.load_states(session, shop_id, today, moment)
    eligible = {s.facts.key for s in states if s.stock is not None and is_eligible(s.facts, today)}
    tracked_map = await settings.sync_defaults(
        session, shop_id, [s.facts.key for s in states], eligible, now=moment
    )
    usable = [s for s in states if s.stock is not None]
    rows = (
        alerts(
            [s.facts for s in usable],
            today,
            alert_days=conf.days,
            tracked={k for k, on in tracked_map.items() if on},
        )
        if usable
        else []
    )
    kind = KIND_NO_READ if not usable else (KIND_ALERT if rows else KIND_EMPTY)
    read_at: datetime | None = None
    deducted = 0
    if usable:
        newest = max(usable, key=lambda s: s.stock.read_at if s.stock else datetime.min)
        read_at = newest.stock.read_at if newest.stock else None
        deducted = max((s.stock.deducted_orders for s in usable if s.stock), default=0)
    orders_through = max(
        (s.facts.orders_through for s in states if s.facts.orders_through is not None),
        default=None,
    )
    reads = [s.last_read_at for s in states if s.last_read_at is not None]
    no_read_since = sb.local_day(max(reads)) if reads else today

    if conf.status == settings.STATUS_PREVIEW:
        people: list[recipients.Recipient] = []
        bcc: tuple[str, ...] = ()
    else:
        people = await recipients.members(session, shop_id)
        first = await _first_send_day(session, shop_id)
        bcc = (
            (recipients.ops_email(),)
            if first is None or (today - first).days < recipients.OPS_BCC_DAYS
            else ()
        )
    previous = await _previous_keys(session, shop_id, today)
    new, ongoing = split_new(rows, previous)
    rows = [*new, *ongoing]
    fresh = {r.facts.key for r in new}
    keys = [r.facts.key for r in rows]
    log_rows = [
        {
            "key": r.facts.key,
            "reason": r.reason,
            "new": r.facts.key in fresh,
            "title": row_title(r),
            "line": row_line(r),
        }
        for r in rows
    ]
    # the day's row first: a second or parallel run finds it and sends nothing
    try:
        async with session.begin_nested():
            session.add(
                ShopeeStockAlertSend(
                    shop_id=shop_id,
                    local_date=today,
                    kind=kind,
                    rows=log_rows,
                    recipients=len(people) or 1,
                    preview=conf.status == settings.STATUS_PREVIEW,
                )
            )
            await session.flush()
    except IntegrityError:
        return ShopRun("already_sent")

    def mail_for(to: str, user_id: uuid.UUID | None, extra_bcc: tuple[str, ...]) -> StockMail:
        unsub = links.unsubscribe_url(shop_id, user_id) if user_id else links.open_url()
        c = compose(
            kind,
            rows,
            today=today,
            alert_days=conf.days,
            open_url=links.open_url(keys),
            unsubscribe_url=unsub,
            read_at=read_at,
            deducted_orders=deducted,
            no_read_since=no_read_since,
            previous_keys=previous,
            orders_through=orders_through,
        )
        return StockMail(to=to, subject=c.subject, text=c.text, html=c.html, bcc=extra_bcc)

    if conf.status == settings.STATUS_PREVIEW:
        mails = [mail_for(recipients.ops_email(), None, ())]
    else:
        mails = [mail_for(p.email, p.user_id, bcc if i == 0 else ()) for i, p in enumerate(people)]
    mailer = mailer or get_stock_mailer()
    sent = await send_all(mailer, mails) if mails else 0
    logger.info(
        "stock_alert_shop_run",
        extra={
            "shop_id": str(shop_id),
            "kind": kind,
            "rows": len(rows),
            "recipients": len(mails),
            "sent": sent,
            "preview": conf.status == settings.STATUS_PREVIEW,
        },
    )
    return ShopRun("done", kind, len(rows), len(mails), sent)


@dataclass(frozen=True)
class RunSummary:
    shops: int = 0
    done: int = 0
    failed: int = 0


async def run_all(factory: SessionFactory, *, now: datetime | None = None) -> RunSummary:
    """Every Shopee shop whose stock e-mail is on or in preview; one session each."""
    from juli_backend.database.tenant_context import with_shop_scope
    from juli_backend.services.ops.overview import list_shops

    async with factory() as session:
        shop_ids = [s.shop_id for s in await list_shops(session) if s.platform == "shopee"]
    done = failed = 0
    for shop_id in shop_ids:
        try:
            async with factory() as session:
                async with with_shop_scope(session, shop_id):
                    result = await run_shop(session, shop_id, now=now)
                    await session.commit()
            done += result.status == "done"
        except Exception as exc:  # type only: a message can carry client values
            failed += 1
            logger.error(
                "stock_alert_shop_failed",
                extra={"shop_id": str(shop_id), "error_type": type(exc).__name__},
            )
    return RunSummary(len(shop_ids), done, failed)


__all__ = ["RunSummary", "ShopRun", "run_all", "run_shop"]
