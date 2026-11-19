"""What the Connector last told Juli about itself, and the one command Juli can give it (P100).

Tables ``shopee_connector_state`` (one row per shop) and ``shopee_connector_commands`` (migration
128).

- Heartbeat: the Connector's fill-job poll (every few minutes) says whether a Seller Centre tab is
  open and acknowledges the command it ran.
- Command ``reconcile`` ("Đối chiếu ngay"): the web app asks, the next poll hands it to the
  Connector (``pending`` -> ``sent``), which runs its readers now; the ack closes it (``acked``).

Reviewer requests never write here (``reviewer_session_active``).

Reader blocks (Connector 0.3.22, migration 131): a login wall or CAPTCHA on one Seller Centre page
now blocks that page only (outcome ``blocked:login`` / ``blocked:captcha``) and the run goes on. A
daily run's report (``POST /v1/ingest/connector-ticks``) replaces ``reader_blocks`` on the state
row; any other run (a ``reread``, a stock run) merges into it (done readers leave, blocked ones
join), skips leave it, and an accepted extension ingest of a blocked reader's dataset captured
after ``reader_blocks_at`` removes that reader. A session-wide stop is the page's
``blocked_login`` / ``blocked_captcha`` (run result ``blocked:<reason>``).

More than one computer (batch-1118e R7, migration 135): each ingest token (one per computer) has its
own row in ``shopee_connector_token_state``; the routes write that row and the shop row above is
recomputed as the aggregate (``aggregate``): alive if any computer is fresh, the newest version seen
in ``VERSION_WINDOW``, the tab open if any fresh computer says so, and the union of the blocks every
computer reported in ``BLOCKS_WINDOW`` (a block shows while any recent computer reports it). The
clear-on-ingest clears every computer's row. Called without a token (internal callers, tests),
the shop row is written directly as before.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingest import IngestToken
from juli_backend.models.shopee_connector import (
    COMMAND_ACKED,
    COMMAND_PENDING,
    COMMAND_RECONCILE,
    COMMAND_SENT,
    ShopeeConnectorCommand,
    ShopeeConnectorState,
    ShopeeConnectorTokenState,
)
from juli_backend.services.shop_proposals.cycle import ProposalError

COMMAND_ID_MAX = 64
#: The poll runs every 3 minutes; a heartbeat older than this says nothing about the tab.
HEARTBEAT_FRESH = timedelta(minutes=10)
#: R7 windows, kept here in one place. A fill job handed to one computer stays its own this long
#: (the holder's poll and reports extend it); after that another computer may take it.
FILL_LEASE = timedelta(minutes=10)
#: The shop's version is the newest one a computer reported in this window.
VERSION_WINDOW = timedelta(days=7)
#: A computer's reader blocks count toward the shop's for this long after its last run report.
BLOCKS_WINDOW = timedelta(hours=36)
ERROR_REVIEWER = "connector_command_refused"
_OPEN = (COMMAND_PENDING, COMMAND_SENT)

#: The audit action of the Connector's scheduler tick (``POST /v1/ingest/connector-ticks``).
ACTION_CONNECTOR_TICK = "system_connector_tick"
#: The readers on Phân tích bán hàng (Seller Centre /datacenter), which asks for the password again.
DATACENTER_READERS = frozenset({"shop_totals", "traffic", "product_period", "item_traffic"})
SECTION_DATACENTER = "phan_tich_ban_hang"
SECTION_SELLER_CENTRE = "seller_centre"
#: ``no_permission`` (Connector 0.3.26): the sub-account may not open Tài chính (the income page);
#: page-only, a Seller Centre section block.
#: ``traffic_check`` (Connector 0.3.28): Shopee sent the tab to ``/verify/traffic``; it stops the
#: whole Seller Centre, so it is always a Seller Centre block, whichever reader hit it.
_BLOCK_REASONS = ("login", "captcha", "password_recheck", "no_permission", "traffic_check")

#: Reader -> the datasets it posts; kept equal to ``READER_DATASETS`` in
#: ``apps/connector/src/platforms/shopee/config.ts`` (a test reads that file). An accepted
#: extension ingest of any of a blocked reader's datasets proves the page was read.
READER_DATASETS: dict[str, tuple[str, ...]] = {
    "products": ("item_catalog", "item_snapshot"),
    "item_traffic": ("item_traffic_sources",),
    "vouchers": ("voucher_settings",),
    "ads": ("ads_campaign_daily", "ads_campaign_settings"),
    "ads_detail": ("ads_campaign_detail",),
    "health": ("shop_health_daily",),
    "shop_totals": ("shop_overview",),
    "product_period": ("product_period",),
    "ads_products": ("ads_campaign_period",),
    "orders": ("order_lines",),
    "order_income": ("order_income",),
    "traffic": ("traffic_overview", "shop_traffic"),
    "affiliate": ("affiliate_order_lines",),
    "affiliate_kols": ("affiliate_partner_period",),
    "affiliate_dashboard": ("affiliate_shop_period",),
    "affiliate_products": ("affiliate_product_period",),
    "affiliate_campaigns": ("affiliate_shop_campaigns",),
    "affiliate_commissions": ("affiliate_commission_period",),
    "affiliate_content": ("affiliate_content_period",),
    "affiliate_bills": ("affiliate_bill_period",),
}


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat() + "Z"


async def _open_command(
    session: AsyncSession, shop_id: uuid.UUID, kind: str = COMMAND_RECONCILE
) -> ShopeeConnectorCommand | None:
    return await session.scalar(
        select(ShopeeConnectorCommand).where(
            ShopeeConnectorCommand.shop_id == shop_id,
            ShopeeConnectorCommand.type == kind,
            ShopeeConnectorCommand.status.in_(_OPEN),
        )
    )


async def record_heartbeat(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    seller_centre_open: bool | None,
    ack: str | None,
    now: datetime,
    version: str | None = None,
    token_id: uuid.UUID | None = None,
) -> None:
    """The Connector's poll: the tab flag (None = it did not say), its version, and the command it
    ran (an id this shop does not have, or one already closed, changes nothing). With the caller's
    ``token_id`` the computer's own row is written and the shop row recomputed from all of them."""
    row = await _shop_row(session, shop_id)
    target: ShopeeConnectorState | ShopeeConnectorTokenState = row
    if token_id is not None:
        target = await _token_row(session, shop_id, token_id)
    target.heartbeat_at = now
    target.updated_at = now
    if seller_centre_open is not None:
        target.seller_centre_open = seller_centre_open
    if version:
        target.connector_version = version[:32]
    if token_id is not None:
        await session.flush()
        _apply_beat(row, aggregate(await _token_rows(session, shop_id), now=now))
        row.updated_at = now
    if ack:
        try:
            command_id = uuid.UUID(ack)
        except ValueError:
            command_id = None
        cmd = None if command_id is None else await session.get(ShopeeConnectorCommand, command_id)
        if cmd is not None and cmd.shop_id == shop_id and cmd.status in _OPEN:
            cmd.status, cmd.acked_at = COMMAND_ACKED, now
    await session.flush()


async def _shop_row(session: AsyncSession, shop_id: uuid.UUID) -> ShopeeConnectorState:
    row = await session.get(ShopeeConnectorState, shop_id)
    if row is None:
        row = ShopeeConnectorState(shop_id=shop_id)
        session.add(row)
    return row


async def _token_row(
    session: AsyncSession, shop_id: uuid.UUID, token_id: uuid.UUID
) -> ShopeeConnectorTokenState:
    row = await session.get(ShopeeConnectorTokenState, token_id)
    if row is None:
        row = ShopeeConnectorTokenState(token_id=token_id, shop_id=shop_id, reader_blocks=[])
        session.add(row)
    return row


async def _token_rows(session: AsyncSession, shop_id: uuid.UUID) -> list[ShopeeConnectorTokenState]:
    return list(
        (
            await session.scalars(
                select(ShopeeConnectorTokenState).where(
                    ShopeeConnectorTokenState.shop_id == shop_id
                )
            )
        ).all()
    )


def _newest_version(versions: list[str]) -> str | None:
    from juli_backend.services.ingest.status import version_key

    return max(versions, key=version_key) if versions else None


def _union_blocks(rows: list[ShopeeConnectorTokenState]) -> list[dict[str, Any]]:
    """The blocks of ``rows`` (newest report first), one entry per (section, reason), each reader
    once."""
    merged: list[dict[str, Any]] = []
    for r in rows:
        for block in r.reader_blocks or []:
            key = (block.get("section"), block.get("reason"))
            target = next((m for m in merged if (m["section"], m["reason"]) == key), None)
            if target is None:
                target = {"section": key[0], "reason": key[1], "readers": []}
                merged.append(target)
            for reader in block.get("readers", []):
                if reader not in target["readers"]:
                    target["readers"].append(reader)
    return [m for m in merged if m["readers"]]


def aggregate(rows: list[ShopeeConnectorTokenState], *, now: datetime) -> dict[str, Any]:
    """The shop's Connector state from its computers' rows (pure)."""
    beats = [r.heartbeat_at for r in rows if r.heartbeat_at is not None]
    fresh = [
        r for r in rows if r.heartbeat_at is not None and now - r.heartbeat_at <= HEARTBEAT_FRESH
    ]
    said = [r.seller_centre_open for r in fresh if r.seller_centre_open is not None]
    recent = [
        r.connector_version
        for r in rows
        if r.connector_version
        and r.heartbeat_at is not None
        and now - r.heartbeat_at <= VERSION_WINDOW
    ]
    reported = sorted(
        (
            r
            for r in rows
            if r.reader_blocks_at is not None and now - r.reader_blocks_at <= BLOCKS_WINDOW
        ),
        key=lambda r: r.reader_blocks_at or datetime.min,
        reverse=True,
    )
    blocks_at = [r.reader_blocks_at for r in rows if r.reader_blocks_at is not None]
    return {
        "heartbeat_at": max(beats, default=None),
        "alive": bool(fresh),
        "seller_centre_open": (True if any(said) else False) if said else None,
        "connector_version": _newest_version(recent),
        "reader_blocks": _union_blocks(reported),
        "reader_blocks_at": max(blocks_at, default=None),
    }


def _apply_beat(row: ShopeeConnectorState, agg: dict[str, Any]) -> None:
    row.heartbeat_at = agg["heartbeat_at"]
    row.seller_centre_open = agg["seller_centre_open"]
    if agg["connector_version"]:
        row.connector_version = agg["connector_version"]


def _apply_blocks(row: ShopeeConnectorState, agg: dict[str, Any]) -> None:
    row.reader_blocks = agg["reader_blocks"]
    row.reader_blocks_at = agg["reader_blocks_at"]


async def request_reconcile(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime
) -> dict[str, Any]:
    """ "Đối chiếu ngay": queue the command (one open at a time; asking twice keeps the first)."""
    from juli_backend.integrations.tiktok import reviewer_session_active

    if reviewer_session_active():
        raise ProposalError(ERROR_REVIEWER, 403)
    cmd = await _open_command(session, shop_id)
    if cmd is None:
        cmd = ShopeeConnectorCommand(
            id=uuid.uuid4(), shop_id=shop_id, type=COMMAND_RECONCILE, status=COMMAND_PENDING,
            created_at=now,
        )  # fmt: skip
        session.add(cmd)
        await session.flush()
    # F3.2: also ask for the read-back of every executed card still waiting for its verdict
    from juli_backend.services.shopee_recommendations import revert_fill

    queued = await revert_fill.queue_pending_readbacks(session, shop_id, now=now)
    return {"requested": True, "command_id": str(cmd.id), "readbacks": queued}


async def commands(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime
) -> list[dict[str, str]]:
    """The open command for the Connector's poll (handed over once ``pending``; until it is acked
    the same id is served again, the Connector runs each id once)."""
    cmd = await _open_command(session, shop_id)
    if cmd is None:
        return []
    if cmd.status == COMMAND_PENDING:
        cmd.status, cmd.sent_at = COMMAND_SENT, now
        await session.flush()
    return [{"type": cmd.type, "id": str(cmd.id)}]


async def read(session: AsyncSession, shop_id: uuid.UUID, *, now: datetime) -> dict[str, Any]:
    """The Thực hiện Connector line. ``reader_blocks`` comes from the computers' rows (so a stale
    computer's blocks age out) once any computer reported a run, else from the shop row;
    ``computers`` lists each computer that ever polled."""
    row = await session.get(ShopeeConnectorState, shop_id)
    pairs = (
        await session.execute(
            select(ShopeeConnectorTokenState, IngestToken.client_label)
            .join(IngestToken, IngestToken.id == ShopeeConnectorTokenState.token_id)
            .where(ShopeeConnectorTokenState.shop_id == shop_id)
            .order_by(ShopeeConnectorTokenState.heartbeat_at.desc())
        )
    ).all()
    tokens = [t for t, _ in pairs]
    if any(t.reader_blocks_at is not None for t in tokens):
        blocks = aggregate(tokens, now=now)["reader_blocks"]
    else:
        blocks = list(row.reader_blocks or []) if row else []
    computers = [
        {
            "label": label,
            "version": t.connector_version,
            "heartbeat_at": _iso(t.heartbeat_at),
            "alive": t.heartbeat_at is not None and now - t.heartbeat_at <= HEARTBEAT_FRESH,
        }
        for t, label in pairs
    ]
    beat = row.heartbeat_at if row else None
    fresh = beat is not None and now - beat <= HEARTBEAT_FRESH
    return {
        "heartbeat_at": _iso(beat),
        "alive": fresh,
        "seller_centre_open": row.seller_centre_open if row and fresh else None,
        "connector_version": row.connector_version if row else None,
        "reconcile_pending": await _open_command(session, shop_id) is not None,
        "reader_blocks": blocks,
        "computers": computers,
    }


def _block_of(reader: str, outcome: object) -> tuple[str, str] | None:
    """(section, reason) of a blocked page outcome, or None. ``blocked:<reason>`` blocked this page
    only; ``blocked_<reason>`` is the page that stopped the whole run (a session-wide logout)."""
    if not isinstance(outcome, str):
        return None
    for reason in _BLOCK_REASONS:
        if outcome == f"blocked:{reason}" or outcome.startswith(f"blocked:{reason}|"):
            datacenter = reader in DATACENTER_READERS and reason != "traffic_check"
            return (SECTION_DATACENTER if datacenter else SECTION_SELLER_CENTRE), reason
        if outcome == f"blocked_{reason}":
            # The password dialog only exists on /datacenter; a login wall or CAPTCHA stops the
            # whole Seller Centre session.
            return (
                SECTION_DATACENTER if reason == "password_recheck" else SECTION_SELLER_CENTRE
            ), reason
    return None


def reader_blocks_of(outcomes: dict[str, str]) -> list[dict[str, Any]]:
    """The blocked sections of one run report's page outcomes, in page order."""
    blocks: dict[tuple[str, str], list[str]] = {}
    for reader, outcome in outcomes.items():
        found = _block_of(str(reader), outcome)
        if found is not None:
            blocks.setdefault(found, []).append(str(reader))
    return [
        {"section": section, "reason": reason, "readers": readers}
        for (section, reason), readers in blocks.items()
    ]


def _is_done(outcome: object) -> bool:
    """``done:<dataset>=posted,...``: the page was read and posted at least one dataset. A ``done``
    that only ``=ignored`` / ``=queued`` posted nothing and proves nothing."""
    return isinstance(outcome, str) and outcome.startswith("done") and "=posted" in outcome


def _without_readers(blocks: list[dict[str, Any]], readers: set[str]) -> list[dict[str, Any]]:
    """``blocks`` minus ``readers``; a section left with no reader disappears."""
    kept: list[dict[str, Any]] = []
    for block in blocks:
        left = [r for r in block.get("readers", []) if r not in readers]
        if left:
            kept.append({**block, "readers": left})
    return kept


def merge_reader_blocks(
    existing: list[dict[str, Any]], outcomes: dict[str, str]
) -> list[dict[str, Any]]:
    """A non-daily run's report merged into the blocks: readers it finished leave their block,
    readers it reports blocked join (or move to) theirs."""
    fresh = reader_blocks_of(outcomes)
    leaving = {str(r) for r, outcome in outcomes.items() if _is_done(outcome)}
    for block in fresh:
        leaving.update(block["readers"])
    merged = _without_readers([dict(b) for b in existing], leaving)
    for block in fresh:
        for target in merged:
            if target["section"] == block["section"] and target["reason"] == block["reason"]:
                target["readers"] = [*target["readers"], *block["readers"]]
                break
        else:
            merged.append(block)
    return merged


async def record_reader_blocks(
    session: AsyncSession,
    shop_id: uuid.UUID,
    outcomes: dict[str, str],
    *,
    now: datetime,
    daily: bool = True,
    token_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    """A run's report. A daily run's blocked sections replace the last ones (``[]`` = none); any
    other run (a re-read after a block cleared, a stock run) is merged into them. With the
    caller's ``token_id`` that applies to the computer's own row and the shop row becomes the
    union of every recent computer's blocks (returned)."""
    row = await _shop_row(session, shop_id)
    target: ShopeeConnectorState | ShopeeConnectorTokenState = row
    if token_id is not None:
        target = await _token_row(session, shop_id, token_id)
    if daily:
        blocks = reader_blocks_of(outcomes)
    else:
        blocks = merge_reader_blocks(list(target.reader_blocks or []), outcomes)
    target.reader_blocks = blocks
    target.reader_blocks_at = now
    target.updated_at = now
    if token_id is not None:
        await session.flush()
        _apply_blocks(row, aggregate(await _token_rows(session, shop_id), now=now))
        row.updated_at = now
        blocks = list(row.reader_blocks or [])
    await session.flush()
    return blocks


async def clear_blocks_for_dataset(
    session: AsyncSession, shop_id: uuid.UUID, dataset: str, *, captured_at: datetime
) -> None:
    """An accepted extension ingest of ``dataset`` captured after the blocks were written: the
    readers that post it are no longer blocked. No state row or no blocks is a no-op."""
    readers = {r for r, datasets in READER_DATASETS.items() if dataset in datasets}
    if not readers:
        return
    tokens = await _token_rows(session, shop_id)
    changed = False
    for t in tokens:
        if not t.reader_blocks or t.reader_blocks_at is None or captured_at <= t.reader_blocks_at:
            continue
        kept = _without_readers(list(t.reader_blocks), readers)
        if kept != list(t.reader_blocks):
            t.reader_blocks = kept
            changed = True
    if changed:
        await session.flush()
        shop_row = await session.get(ShopeeConnectorState, shop_id)
        if shop_row is not None:
            _apply_blocks(shop_row, aggregate(tokens, now=datetime.now(UTC).replace(tzinfo=None)))
            await session.flush()
        return
    row = await session.get(ShopeeConnectorState, shop_id)
    if row is None or not row.reader_blocks:
        return
    if row.reader_blocks_at is None or captured_at <= row.reader_blocks_at:
        return
    left = _without_readers(list(row.reader_blocks), readers)
    if left != list(row.reader_blocks):
        row.reader_blocks = left
        await session.flush()
