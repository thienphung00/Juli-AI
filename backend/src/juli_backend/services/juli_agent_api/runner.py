"""One answer's run: the engine, its events persisted, and the rows it leaves behind.

The ask route commits the question and a ``running`` answer, then :func:`schedule` starts
:func:`execute` as a task in the API process (the answer streams in seconds; a Celery hop would
only add latency). The run writes through its own sessions -- the request's is closed by then --
each in the shop's scope. The analysis itself reads through read-only sessions
(``engine.read_only_session_factory``).

Ending, in one transaction: the card drafts, the routing decisions, the message's status /
stop reasons / cost / ms / pending choice, and last the ``done`` (or ``error``) event.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.agent_chat import (
    DRAFT_DRAFTED,
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_FAILED,
    AgentCardDraft,
    AgentMessage,
    AgentRoutingDecision,
)
from juli_backend.services.juli_agent_api import config
from juli_backend.services.juli_agent_api.engine import (
    Engine,
    PortsFactory,
    read_only_session_factory,
)
from juli_backend.services.juli_agent_api.events import PersistingSink
from juli_backend.services.juli_agent_api.ports import JevUnavailable, LLMUnavailable

logger = logging.getLogger(__name__)

#: running tasks of THIS process, by answer id (cancel reaches a local run at once; a run in
#: another process stops at its next flush, which reads ``cancel_requested``)
_TASKS: dict[uuid.UUID, asyncio.Task[None]] = {}


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _field(result: Any, name: str, default: Any = None) -> Any:
    if isinstance(result, Mapping):
        return result.get(name, default)
    return getattr(result, name, default)


def _drafts_of(result: Any) -> list[dict[str, Any]]:
    """The engine's card drafts (``AnswerResult``): full card JSON, each with its ``draft_ref``."""
    raw = _field(result, "drafts")
    if raw is None:
        raw = _field(result, "cards", [])
    out = []
    for item in raw or []:
        card = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        if card.get("draft_ref"):
            out.append(card)
    return out


def _routing_rows(
    routing: Any, *, shop_id: uuid.UUID, message_id: uuid.UUID, now: datetime
) -> list[AgentRoutingDecision]:
    rows = []
    for item in routing or []:
        entry = dict(item) if isinstance(item, Mapping) else {"answers": item}
        answers = entry.get("answers", entry.get("answer"))
        rows.append(
            AgentRoutingDecision(
                id=uuid.uuid4(),
                shop_id=shop_id,
                message_id=message_id,
                intent=(str(entry["intent"])[:64] if entry.get("intent") else None),
                answers=answers if isinstance(answers, dict) else {"value": answers},
                thresholds=entry.get("thresholds"),
                outcome=(str(entry["outcome"])[:64] if entry.get("outcome") else None),
                created_at=now,
            )
        )
    return rows


async def _finish(
    factory: async_sessionmaker[AsyncSession],
    *,
    shop_id: uuid.UUID,
    message_id: uuid.UUID,
    sink: PersistingSink,
    status: str,
    terminal: tuple[str, dict[str, Any]],
    stop_reasons: list[str] | None = None,
    cost_usd: float | None = None,
    ms: int,
    routing: Any = None,
    drafts: list[dict[str, Any]] | None = None,
) -> None:
    now = _utcnow()
    kind, payload = terminal
    events = [*sink.events, {"seq": len(sink.events) + 1, "type": kind, "payload": payload}]
    async with factory() as session, with_shop_scope(session, shop_id):
        row = await session.get(AgentMessage, message_id)
        if row is None:  # pragma: no cover - the row was purged mid-run
            return
        for card in drafts or []:
            session.add(
                AgentCardDraft(
                    id=uuid.uuid4(),
                    shop_id=shop_id,
                    message_id=message_id,
                    draft_ref=str(card["draft_ref"])[:64],
                    card=card,
                    status=DRAFT_DRAFTED,
                    created_at=now,
                )
            )
        session.add_all(_routing_rows(routing, shop_id=shop_id, message_id=message_id, now=now))
        row.events = events
        row.status = status
        row.stop_reasons = stop_reasons
        row.cost_usd = Decimal(str(cost_usd)) if cost_usd is not None else None
        row.ms = ms
        row.pending = sink.private.get("pending")
        row.updated_at = now
        await session.commit()
    sink.events = events  # only once written: a retried ending never doubles its terminal event


def _data_until_vi(result: Any) -> str | None:
    """The latest data day the answer used, "dd/mm" (the engine's ``data_until_vi`` / ``as_of``)."""
    text = _field(result, "data_until_vi", None)
    if text:
        return str(text)
    day = _field(result, "data_until", None) or _field(result, "as_of", None)
    return f"{day:%d/%m}" if isinstance(day, date) else None


def _template_choice(engine: Engine) -> dict[str, Any]:
    """The ``needs_choice`` that offers the templates (item ``template``: a click asks it)."""
    try:
        templates = engine.templates()
    except Exception:  # the engine itself is down: no buttons, the line still shows
        templates = []
    return {
        "item": "template",
        "question_vi": "Juli chưa phân tích được câu hỏi này. Chọn một câu hỏi mẫu:",
        "options": [{"label_vi": t.label_vi, "value": t.key} for t in templates],
    }


async def _mark_ended(
    factory: async_sessionmaker[AsyncSession],
    shop_id: uuid.UUID,
    message_id: uuid.UUID,
    status: str,
) -> None:
    """Last resort when the full ending could not be written: the row leaves ``running``."""
    try:
        async with factory() as session, with_shop_scope(session, shop_id):
            row = await session.get(AgentMessage, message_id)
            if row is not None and row.status == "running":
                row.status = status
                row.updated_at = _utcnow()
            await session.commit()
    except Exception:
        logger.exception("juli_agent_mark_ended_failed", extra={"message_id": str(message_id)})


async def _finish_safely(
    *args: Any, before: tuple[str, dict[str, Any]] | None = None, **kw: Any
) -> None:
    """:func:`_finish`, and whatever happens the row does not stay ``running``."""
    sink: PersistingSink = kw["sink"]
    if before is not None:
        sink.append(*before)
    try:
        await _finish(*args, **kw)
    except (Exception, asyncio.CancelledError):
        logger.exception("juli_agent_finish_failed", extra={"message_id": str(kw["message_id"])})
        await _mark_ended(args[0], kw["shop_id"], kw["message_id"], kw["status"])


async def execute(
    *,
    message_id: uuid.UUID,
    request: Mapping[str, Any],
    engine: Engine,
    ports_factory: PortsFactory,
    write_factory: async_sessionmaker[AsyncSession],
    read_factory: async_sessionmaker[AsyncSession],
    switch_platforms: frozenset[str] = frozenset(),
) -> None:
    """Run the engine for one answer and finish the row; never raises (the run is a task)."""
    shop_id = uuid.UUID(str(request["shop_id"]))
    sink = PersistingSink(write_factory, shop_id, message_id, switch_platforms=switch_platforms)
    started = time.monotonic()

    def elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    try:
        async with asyncio.timeout(config.run_timeout_s()):
            ports = await ports_factory(
                shop_id=shop_id, platform=str(request["platform"]), write_factory=write_factory
            )
            result = await engine.run(
                request,
                read_session_factory=read_only_session_factory(read_factory, shop_id),
                llm=ports.llm,
                jev=ports.jev,
                sink=sink,
            )
            await sink.flush()
    except TimeoutError:
        # the whole run is over its time limit: the answer ends "Juli đang bận"
        logger.warning("juli_agent_run_timeout", extra={"message_id": str(message_id)})
        await _finish_safely(
            write_factory,
            shop_id=shop_id,
            message_id=message_id,
            sink=sink,
            status=STATUS_FAILED,
            terminal=("error", {"code": "busy"}),
            ms=elapsed(),
        )
        return
    except asyncio.CancelledError:
        # "Dừng": the seller's cancel (a local task.cancel() or the flag read at a flush)
        await _finish_safely(
            write_factory,
            shop_id=shop_id,
            message_id=message_id,
            sink=sink,
            status=STATUS_CANCELLED,
            terminal=("done", {"stop_reasons": ["cancelled"], "cancelled": True, "ms": elapsed()}),
            stop_reasons=["cancelled"],
            ms=elapsed(),
        )
        return
    except JevUnavailable:
        # J11: the router is down after its retries -- offer the templates (no Jev needed)
        logger.warning("juli_agent_jev_unavailable", extra={"message_id": str(message_id)})
        await _finish_safely(
            write_factory,
            shop_id=shop_id,
            message_id=message_id,
            sink=sink,
            status=STATUS_DONE,
            before=("needs_choice", _template_choice(engine)),
            terminal=("done", {"stop_reasons": ["router_unavailable"], "ms": elapsed()}),
            stop_reasons=["router_unavailable"],
            ms=elapsed(),
        )
        return
    except Exception as exc:  # the run is a task: every failure ends the answer
        busy = isinstance(exc, LLMUnavailable) and exc.busy
        logger.exception("juli_agent_run_failed", extra={"message_id": str(message_id)})
        error = {"code": "busy" if busy else "failed"}
        if sink.error is not None and not busy:  # the engine already said which (T1)
            error = dict(sink.error["payload"])
        await _finish_safely(
            write_factory,
            shop_id=shop_id,
            message_id=message_id,
            sink=sink,
            status=STATUS_FAILED,
            terminal=("error", error),
            ms=elapsed(),
        )
        return

    if sink.error is not None:  # the engine ended the answer itself (e.g. a timeout: busy)
        await _finish_safely(
            write_factory,
            shop_id=shop_id,
            message_id=message_id,
            sink=sink,
            status=STATUS_FAILED,
            terminal=("error", dict(sink.error["payload"])),
            stop_reasons=list(_field(result, "stop_reasons", None) or []) or None,
            ms=elapsed(),
            routing=_field(result, "routing", None),
        )
        return

    ms = elapsed()
    stop_reasons = list(_field(result, "stop_reasons", None) or [])
    cost = _field(result, "cost_usd", None)
    done = dict(sink.done["payload"]) if sink.done is not None else {}
    done.update({"stop_reasons": stop_reasons or done.get("stop_reasons", []), "ms": ms})
    if cost is not None:
        done["cost_usd"] = float(cost)
    data_until = _data_until_vi(result)
    if data_until is not None:
        done["data_until_vi"] = data_until
    routing = _field(result, "routing", None)
    if routing is None:
        routing = sink.private.get("routing")
    try:
        await _finish(
            write_factory,
            shop_id=shop_id,
            message_id=message_id,
            sink=sink,
            status=STATUS_DONE,
            terminal=("done", done),
            stop_reasons=done["stop_reasons"],
            cost_usd=float(cost) if cost is not None else done.get("cost_usd"),
            ms=ms,
            routing=routing,
            drafts=_drafts_of(result),
        )
    except asyncio.CancelledError:
        # "Dừng" while the answer was being written: end it cancelled, never left "running"
        await _finish_safely(
            write_factory,
            shop_id=shop_id,
            message_id=message_id,
            sink=sink,
            status=STATUS_CANCELLED,
            terminal=("done", {"stop_reasons": ["cancelled"], "cancelled": True, "ms": ms}),
            stop_reasons=["cancelled"],
            ms=ms,
        )
    except Exception:
        logger.exception("juli_agent_finish_failed", extra={"message_id": str(message_id)})
        await _mark_ended(write_factory, shop_id, message_id, STATUS_FAILED)


def schedule(**kwargs: Any) -> asyncio.Task[None]:
    """Start :func:`execute` as a task of the running loop and remember it for cancel."""
    message_id: uuid.UUID = kwargs["message_id"]
    task = asyncio.get_running_loop().create_task(execute(**kwargs))
    _TASKS[message_id] = task
    task.add_done_callback(lambda _t: _TASKS.pop(message_id, None))
    return task


def active_runs() -> int:
    """Runs in flight in this process (the per-process cap, ``config.max_concurrent_runs``)."""
    return sum(1 for task in _TASKS.values() if not task.done())


def cancel_local(message_id: uuid.UUID) -> bool:
    """Cancel the run if this process runs it; the row flag covers the other processes."""
    task = _TASKS.get(message_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True


__all__ = ["active_runs", "cancel_local", "execute", "schedule"]
