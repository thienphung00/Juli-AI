"""The outside-Juli import as a background job (F6.2, E67).

A big file can take longer than the proxy lets one request live, so the commit route answers at
once with a job id and the work runs in the API process (the same ``create_task`` pattern as
``shopee_reco_refresh``). The job lives in one ``shop_rules`` row per shop (key
``board_import_job``, shop-wide; no new table): it holds the status and, when done, the per-card
result, so the last import of the shop can be read again after a reload. Rules readers ignore the
key.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.tenant_context import with_tenant_scope
from juli_backend.models.models import Shop
from juli_backend.models.run_changes import ShopRule
from juli_backend.services.planned_changes import external
from juli_backend.services.shop_proposals import ProposalError

logger = logging.getLogger(__name__)

RULE_KEY = "board_import_job"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
#: a running job older than this died with its process
STALE_AFTER = timedelta(minutes=20)
ERROR_STALLED = "import_stalled"
ERROR_FAILED = "import_failed"

SessionFactory = Callable[[], Any]
_TASKS: set[asyncio.Task[Any]] = set()


def _naive(now: datetime) -> datetime:
    return now.replace(tzinfo=None) if now.tzinfo else now


async def _row(session: AsyncSession, shop_id: uuid.UUID) -> ShopRule | None:
    return (
        await session.execute(
            select(ShopRule).where(
                ShopRule.shop_id == shop_id, ShopRule.rule_key == RULE_KEY, ShopRule.scope_ref == ""
            )
        )
    ).scalar_one_or_none()


def _public(value: dict[str, Any], now: datetime) -> dict[str, Any]:
    out = dict(value)
    started = out.get("started_at")
    if out.get("status") == RUNNING and started:
        try:
            age = _naive(now) - datetime.fromisoformat(started)
        except ValueError:
            age = timedelta(0)
        if age > STALE_AFTER:
            out.update(status=FAILED, error={"code": ERROR_STALLED, "message": ERROR_STALLED})
    return out


async def latest(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime
) -> dict[str, Any] | None:
    """The shop's last import job (``None`` when it never imported)."""
    row = await _row(session, shop_id)
    return None if row is None else _public(dict(row.value), now)


async def _store(
    session: AsyncSession,
    shop_id: uuid.UUID,
    user_id: uuid.UUID,
    value: dict[str, Any],
    now: datetime,
) -> None:
    row = await _row(session, shop_id)
    if row is None:
        session.add(
            ShopRule(
                shop_id=shop_id,
                rule_key=RULE_KEY,
                scope_ref="",
                value=value,
                set_by="seller",
                set_by_user_id=user_id,
                set_at=_naive(now),
            )
        )
    else:
        row.value = value
        row.set_by_user_id = user_id
        row.set_at = _naive(now)
    await session.flush()


async def create(
    session: AsyncSession, shop_id: uuid.UUID, user_id: uuid.UUID, *, file_hash: str, now: datetime
) -> tuple[dict[str, Any], bool]:
    """Record a running job. ``(job, started)``: ``started`` is False when one is already running
    (the caller returns that one and starts nothing). The caller commits."""
    current = await latest(session, shop_id, now=now)
    if current is not None and current.get("status") == RUNNING:
        return current, False
    job = {
        "job_id": uuid.uuid4().hex,
        "status": RUNNING,
        "file_hash": file_hash,
        "started_at": _naive(now).isoformat(),
        "finished_at": None,
        "result": None,
        "error": None,
    }
    await _store(session, shop_id, user_id, job, now)
    return job, True


async def run(
    factory: SessionFactory,
    shop_id: uuid.UUID,
    user_id: uuid.UUID,
    job: dict[str, Any],
    data: bytes,
    token: str,
) -> dict[str, Any]:
    """Do the import in its own session, then store the outcome. Never raises."""
    finished: dict[str, Any] = {**job}
    try:
        async with factory() as session, with_tenant_scope(session, shop_id, user_id):
            shop = await session.get(Shop, shop_id)
            if shop is None:
                raise ProposalError(ERROR_FAILED, 404, "shop not found")
            try:
                result = await external.commit_import(
                    session, shop, data, token=token, user_id=user_id, reviewer=False,
                    now=datetime.now(UTC),
                )  # fmt: skip
                if result.created == 0 and result.exists == 0 and result.refused == 0:
                    raise ProposalError(
                        "external_nothing_to_import", 409, "Tệp không có dòng nào để nhập"
                    )
            except Exception:
                await session.rollback()
                raise
            await session.commit()
            finished.update(status=DONE, result=external.commit_json(result), error=None)
    except ProposalError as exc:
        finished.update(status=FAILED, error={"code": exc.code, "message": exc.detail or exc.code})
    except Exception as exc:  # type only: a message can carry client values
        logger.error(
            "shopee_external_import_failed",
            extra={"shop_id": str(shop_id), "error_type": type(exc).__name__},
        )
        finished.update(status=FAILED, error={"code": ERROR_FAILED, "message": ERROR_FAILED})
    now = datetime.now(UTC)
    finished["finished_at"] = _naive(now).isoformat()
    try:
        async with factory() as session, with_tenant_scope(session, shop_id, user_id):
            await _store(session, shop_id, user_id, finished, now)
            await session.commit()
    except Exception as exc:
        logger.error(
            "shopee_external_import_store_failed",
            extra={"shop_id": str(shop_id), "error_type": type(exc).__name__},
        )
    return finished


def spawn(
    factory: SessionFactory,
    shop_id: uuid.UUID,
    user_id: uuid.UUID,
    job: dict[str, Any],
    data: bytes,
    token: str,
) -> None:
    """Start :func:`run` in the background (tests replace this to run it inline)."""
    task = asyncio.get_running_loop().create_task(run(factory, shop_id, user_id, job, data, token))
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


__all__ = ["RULE_KEY", "create", "latest", "run", "spawn"]
