"""Clean stored raw payloads and re-key stored ``buyer_id`` (ADR-116 §4, D76).

The allowlist and the pseudonym apply to every NEW raw write. This operator command
brings the rows stored before them into line:

- ``bronze.order_raw_payloads`` / ``bronze.return_raw_payloads`` /
  ``public.ingest_raw_payloads``: the payload reduced to its endpoint's allowlist,
  every ``buyer_id`` in it as the shop's pseudonym. An ingest row whose dataset has
  no allowlist keeps nothing (``{}``) -- fail closed, as for a new write;
- ``public.orders`` / ``public.returns``: ``buyer_id`` as the shop's pseudonym, and
  ``cancel_reason`` / ``return_reason`` kept only as a reason code or a catalogued
  platform label, else ``"other"`` (decision A; ``reason_labels``) -- the raw
  payloads' reason fields get the same rule through their allowlist;
- ``public.workflow_webhook_signals``: ``payload`` reduced to the webhook allowlist
  of its kind (owner decision D16; ``services/tiktok/webhook_redaction``), its
  ``buyer_id`` as the shop's pseudonym; an ``event_id`` that embedded the delivery's
  ``data`` (``extract_event_id``'s JSON fallback) keeps its prefix and replaces the
  JSON with a digest, so the column stays unique;
- ``public.shop_ingestion_state`` / ``public.tiktok_sync_state``: ``last_error``
  rewritten from an older ``repr(exc)`` to the class-and-code label
  (``core.privacy.relabel_stored_error``);
- ``public.webhook_raw_events`` (no shop column: the archive keeps deliveries for
  unknown shops too): ``raw_body`` reduced to the webhook allowlist with any
  ``buyer_id`` DROPPED (not re-keyed -- a stored delivery cannot prove its shop), a
  body that is not a JSON object any more (truncated) cleared, and an ``event_id``
  that embedded the delivery's JSON recomputed from the reduced body. Processed
  after the shops, ``BATCH`` rows per transaction.

It is a DATA change, so it is not a migration (``migration_additive_gate.py``
refuses data UPDATEs from a release). Run it once the release carrying migration
104 and the allowlist is serving -- before that, the old code would keep writing
raw payloads::

    python -m juli_backend.services.privacy.payload_cleanup            # dry run
    python -m juli_backend.services.privacy.payload_cleanup --apply

It connects as the migration owner (``migration_database_url``: ``DATABASE_DIRECT_URL``
then ``DATABASE_URL``), like the deferred data steps: ``juli_app`` has no UPDATE on
the append-only raw tables, by design. Each shop is processed in its own
transaction under its own scope (``with_shop_scope``) and every statement also
filters on ``shop_id``; the shop list is identifiers only. A dry run does the same
work and rolls each shop back, so it writes nothing; a shop without a pseudonym key
gets a throwaway one for the dry run instead of a stored one.
It prints row counts per table, never payload content or ids. Idempotent: a second
``--apply`` changes zero rows.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from juli_backend.core.privacy import relabel_stored_error
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.ingest import IngestRawPayload
from juli_backend.models.ingestion import ShopIngestionState
from juli_backend.models.models import (
    BronzeOrderRawPayload,
    BronzeReturnRawPayload,
    Order,
    Return,
    Shop,
    TikTokSyncState,
    WebhookRawEvent,
    WorkflowWebhookSignal,
)
from juli_backend.services.privacy.payload_allowlist import (
    ORDERS_RAW,
    ORDERS_RECONCILE_PAGE,
    RETURNS_RAW,
    TIKTOK,
    UnknownPayloadEndpoint,
    ingest_endpoint,
)
from juli_backend.services.privacy.pseudonym import (
    pseudonymize_buyer_id,
    use_ephemeral_key_if_missing,
)
from juli_backend.services.privacy.raw_payload import sanitize_raw_payload
from juli_backend.services.privacy.reason_labels import safe_reason
from juli_backend.services.tiktok.webhook_redaction import (
    TRUNCATION_SUFFIX,
    allowlist_webhook,
    drop_buyer_ids,
    parse_webhook_body,
    serialize_stored_body,
    webhook_endpoint,
)

BATCH = 500
#: The bronze ``ingest_source`` of batch-reconcile pages (``services/cdp_batch``).
RECONCILE_SOURCE = "batch_reconcile"
RECONCILE_META_KEY = "_batch_reconcile"

TABLES: tuple[str, ...] = (
    "bronze.order_raw_payloads",
    "bronze.return_raw_payloads",
    "public.ingest_raw_payloads",
    "public.orders",
    "public.returns",
    "public.workflow_webhook_signals",
    "public.shop_ingestion_state",
    "public.tiktok_sync_state",
    "public.webhook_raw_events",
)
#: Cleaned once per run, not per shop (no shop column).
UNSCOPED_TABLES: frozenset[str] = frozenset({"public.webhook_raw_events"})


@dataclass
class TableCount:
    scanned: int = 0
    changed: int = 0


@dataclass
class CleanupReport:
    shops: int = 0
    tables: dict[str, TableCount] = field(
        default_factory=lambda: {name: TableCount() for name in TABLES}
    )

    def add(self, other: dict[str, TableCount]) -> None:
        for name, count in other.items():
            self.tables[name].scanned += count.scanned
            self.tables[name].changed += count.changed

    def render(self, *, applied: bool) -> str:
        verb = "changed" if applied else "would change"
        lines = [
            f"payload_cleanup: {'APPLIED' if applied else 'DRY RUN'} over {self.shops} shop(s)"
        ]
        for name, count in self.tables.items():
            lines.append(f"  {name}: scanned {count.scanned}, {verb} {count.changed}")
        return "\n".join(lines)


async def _batches(session: AsyncSession, model: Any, shop_id: uuid.UUID):
    """Every row of ``model`` for the shop, ``BATCH`` at a time, by id."""
    last: uuid.UUID | None = None
    while True:
        stmt = select(model).where(model.shop_id == shop_id).order_by(model.id).limit(BATCH)
        if last is not None:
            stmt = stmt.where(model.id > last)
        rows = list((await session.execute(stmt)).scalars())
        if not rows:
            return
        yield rows
        last = rows[-1].id


def _order_endpoint(row: BronzeOrderRawPayload) -> str:
    if row.ingest_source == RECONCILE_SOURCE or RECONCILE_META_KEY in (row.payload or {}):
        return ORDERS_RECONCILE_PAGE
    return ORDERS_RAW


async def _clean_payloads(
    session: AsyncSession,
    shop_id: uuid.UUID,
    model: Any,
    endpoint_of: Callable[[Any], tuple[str, str]],
) -> TableCount:
    count = TableCount()
    async for rows in _batches(session, model, shop_id):
        for row in rows:
            count.scanned += 1
            current = row.payload if isinstance(row.payload, dict) else {}
            platform, endpoint = endpoint_of(row)
            try:
                cleaned = await sanitize_raw_payload(
                    session, shop_id, platform=platform, endpoint=endpoint, payload=current
                )
            except UnknownPayloadEndpoint:
                cleaned = {}  # fail closed: nothing reviewed, nothing kept
            if cleaned != row.payload:
                row.payload = cleaned
                count.changed += 1
        await session.flush()
        session.expunge_all()
    return count


async def _rekey_buyer_ids(
    session: AsyncSession, shop_id: uuid.UUID, model: Any, reason_column: str
) -> TableCount:
    """``buyer_id`` as the shop's pseudonym, and the reason column a platform reason."""
    count = TableCount()
    async for rows in _batches(session, model, shop_id):
        for row in rows:
            count.scanned += 1
            changed = False
            keyed = await pseudonymize_buyer_id(session, shop_id, row.buyer_id)
            if keyed != row.buyer_id:
                row.buyer_id = keyed
                changed = True
            reason = getattr(row, reason_column)
            kept = safe_reason(TIKTOK, reason_column, reason)
            if kept != reason:
                setattr(row, reason_column, kept)
                changed = True
            count.changed += int(changed)
        await session.flush()
        session.expunge_all()
    return count


def scrub_event_id(event_id: str | None, event_type: str | None) -> str | None:
    """An ``event_id`` whose JSON fallback carried more than the allowlist, digested.

    ``extract_event_id`` keys a delivery without a known id as ``wh:...:{data json}``.
    Written from an unfiltered body, that JSON can hold buyer data; it is replaced by
    its digest (``wh:...:d:<32 hex>``, still unique). JSON the allowlist would keep
    unchanged -- what the current writers produce -- is left alone, so a second run
    changes nothing.
    """
    if not event_id or "{" not in event_id:
        return event_id
    head, _, tail = event_id.partition("{")
    try:
        data = json.loads("{" + tail)
    except ValueError:
        data = None
    if isinstance(data, dict):
        kept = drop_buyer_ids(allowlist_webhook({"type": event_type, "data": data}))
        if kept.get("data") == data:
            return event_id
    digest = hashlib.sha256(("{" + tail).encode()).hexdigest()[:32]
    return f"{head}d:{digest}"


async def _clean_signals(session: AsyncSession, shop_id: uuid.UUID) -> TableCount:
    count = TableCount()
    async for rows in _batches(session, WorkflowWebhookSignal, shop_id):
        for row in rows:
            count.scanned += 1
            changed = False
            if row.payload is not None:
                try:
                    current = json.loads(row.payload)
                except ValueError:
                    current = None
                if isinstance(current, dict):
                    endpoint = webhook_endpoint(current.get("type") or row.event_type)
                    cleaned = await sanitize_raw_payload(
                        session, shop_id, platform=TIKTOK, endpoint=endpoint, payload=current
                    )
                    text_ = json.dumps(cleaned, sort_keys=True, default=str)
                else:
                    text_ = None
                if text_ != row.payload:
                    row.payload = text_
                    changed = True
            scrubbed = scrub_event_id(row.event_id, row.event_type)
            if scrubbed != row.event_id:
                row.event_id = scrubbed or row.event_id
                changed = True
            count.changed += int(changed)
        await session.flush()
        session.expunge_all()
    return count


async def _relabel_sync_errors(session: AsyncSession, shop_id: uuid.UUID) -> TableCount:
    count = TableCount()
    async for rows in _batches(session, TikTokSyncState, shop_id):
        for row in rows:
            count.scanned += 1
            relabelled = relabel_stored_error(row.last_error)
            if relabelled != row.last_error:
                row.last_error = relabelled
                count.changed += 1
        await session.flush()
        session.expunge_all()
    return count


async def _relabel_ingestion_error(session: AsyncSession, shop_id: uuid.UUID) -> TableCount:
    count = TableCount()
    row = await session.get(ShopIngestionState, shop_id)
    if row is None:
        return count
    count.scanned = 1
    relabelled = relabel_stored_error(row.last_error)
    if relabelled != row.last_error:
        row.last_error = relabelled
        count.changed = 1
        await session.flush()
    return count


async def clean_shop(
    session: AsyncSession, shop_id: uuid.UUID, *, apply: bool = True
) -> dict[str, TableCount]:
    """Clean one shop's rows in the session's open transaction; the caller commits or not.

    ``apply=False`` (a dry run) never creates the shop's pseudonym key.
    """
    async with with_shop_scope(session, shop_id):
        if not apply:
            await use_ephemeral_key_if_missing(session, shop_id)
        return {
            "bronze.order_raw_payloads": await _clean_payloads(
                session, shop_id, BronzeOrderRawPayload, lambda r: (TIKTOK, _order_endpoint(r))
            ),
            "bronze.return_raw_payloads": await _clean_payloads(
                session, shop_id, BronzeReturnRawPayload, lambda r: (TIKTOK, RETURNS_RAW)
            ),
            "public.ingest_raw_payloads": await _clean_payloads(
                session,
                shop_id,
                IngestRawPayload,
                lambda r: (r.platform, ingest_endpoint(r.dataset)),
            ),
            "public.orders": await _rekey_buyer_ids(session, shop_id, Order, "cancel_reason"),
            "public.returns": await _rekey_buyer_ids(session, shop_id, Return, "return_reason"),
            "public.workflow_webhook_signals": await _clean_signals(session, shop_id),
            "public.shop_ingestion_state": await _relabel_ingestion_error(session, shop_id),
            "public.tiktok_sync_state": await _relabel_sync_errors(session, shop_id),
        }


def clean_raw_event(row: WebhookRawEvent) -> bool:
    """Reduce one archived delivery in place; ``True`` when it changed."""
    changed = False
    if row.raw_body is not None:
        parsed = parse_webhook_body(row.raw_body.encode())
        kept = drop_buyer_ids(allowlist_webhook(parsed)) if parsed is not None else None
        body = serialize_stored_body(kept) if kept is not None else None
        if body is not None and body.endswith(TRUNCATION_SUFFIX):
            body = None  # would not parse next time; nothing partial is kept
        if body != row.raw_body:
            row.raw_body = body
            changed = True
    scrubbed = scrub_event_id(row.event_id, row.event_type)
    if scrubbed != row.event_id:
        row.event_id = scrubbed
        changed = True
    return changed


async def clean_raw_events(factory: Callable[[], AsyncSession], *, apply: bool) -> TableCount:
    """Every ``webhook_raw_events`` row, ``BATCH`` per transaction; roll back unless ``apply``."""
    count = TableCount()
    last: uuid.UUID | None = None
    while True:
        async with factory() as session:
            stmt = select(WebhookRawEvent).order_by(WebhookRawEvent.id).limit(BATCH)
            if last is not None:
                stmt = stmt.where(WebhookRawEvent.id > last)
            rows = list((await session.execute(stmt)).scalars())
            if not rows:
                await session.rollback()
                return count
            for row in rows:
                count.scanned += 1
                count.changed += int(clean_raw_event(row))
            last = rows[-1].id
            if apply:
                await session.commit()
            else:
                await session.rollback()


async def shop_ids(session: AsyncSession) -> list[uuid.UUID]:
    """Every shop id (identifiers only; the owner connection sees every shop)."""
    return list((await session.execute(select(Shop.id).order_by(Shop.id))).scalars())


async def run_cleanup(
    factory: Callable[[], AsyncSession],
    *,
    apply: bool,
    only: Sequence[uuid.UUID] | None = None,
    list_shops: Callable[[AsyncSession], Awaitable[list[uuid.UUID]]] = shop_ids,
) -> CleanupReport:
    """Clean every shop (or ``only``), one transaction per shop; roll back unless ``apply``.

    The unscoped ``webhook_raw_events`` pass runs after the shops, and only on a
    whole-fleet run (``only`` names shops; the archive has no shop column).
    """
    report = CleanupReport()
    async with factory() as session:
        targets = list(only) if only else await list_shops(session)
        await session.rollback()
    for shop_id in targets:
        async with factory() as session:
            counts = await clean_shop(session, shop_id, apply=apply)
            if apply:
                await session.commit()
            else:
                await session.rollback()
        report.shops += 1
        report.add(counts)
    if not only:
        report.add({"public.webhook_raw_events": await clean_raw_events(factory, apply=apply)})
    return report


async def _can_update(session: AsyncSession) -> bool:
    if session.get_bind().dialect.name != "postgresql":
        return True
    checks = [
        "has_table_privilege('bronze.order_raw_payloads', 'UPDATE')",
        "has_table_privilege('bronze.return_raw_payloads', 'UPDATE')",
        "has_table_privilege('public.ingest_raw_payloads', 'UPDATE')",
        "has_table_privilege('public.workflow_webhook_signals', 'UPDATE')",
        "has_table_privilege('public.webhook_raw_events', 'UPDATE')",
        "has_table_privilege('public.shop_ingestion_state', 'UPDATE')",
        "has_table_privilege('public.tiktok_sync_state', 'UPDATE')",
    ]
    sql = "SELECT " + " AND ".join(checks)
    return bool((await session.execute(text(sql))).scalar_one())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="payload_cleanup",
        description="Remove non-allowlisted fields from stored raw payloads and webhook "
        "records, re-key buyer_id as the per-shop pseudonym and relabel stored errors "
        "(ADR-116 §4, D16). Dry run unless --apply.",
    )
    parser.add_argument("--apply", action="store_true", help="commit the changes")
    parser.add_argument(
        "--shop", action="append", type=uuid.UUID, default=None, help="limit to this shop id"
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="owner connection (default: DATABASE_DIRECT_URL, then DATABASE_URL)",
    )
    return parser


async def _main(args: argparse.Namespace) -> int:
    from juli_backend.core.config import async_database_url, migration_database_url

    url = async_database_url(args.database_url or migration_database_url())
    engine = create_async_engine(url, hide_parameters=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            if args.apply and not await _can_update(session):
                print(
                    "payload_cleanup: this role cannot UPDATE the raw payload tables; "
                    "run it with the migration owner connection (DATABASE_DIRECT_URL).",
                    file=sys.stderr,
                )
                return 2
        report = await run_cleanup(factory, apply=args.apply, only=args.shop)
    finally:
        await engine.dispose()
    print(report.render(applied=args.apply))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(_main(build_parser().parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
