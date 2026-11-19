"""The Juli tab (batch-1120 T3): asks, the answer's event stream, history, card send / dismiss.

``/v1/demo/juli``; the shop comes from ``X-Shop-Id``. The behaviour lives in
``services.juli_agent_api``; this module resolves the shop, applies the gates, maps the
service's typed errors, commits, and starts the run.

Gates, in order:

1. ``JULI_AGENT_ENABLED`` -- off: 404 on every route, before anything else; a shop not on a
   shop-list value: 404 too.
2. ``require_capability("read_shop_totals", requires_data_on=("shopee", "tiktok"))`` -- a
   TikTok shop is admitted so the ENGINE answers "Thiếu dữ liệu"; never the 409.
3. Writes (ask, cancel, send, dismiss) need ``require_writable_shop``: a read-only shop or a
   pending account deletion answers 403. Card send is for a member of the shop
   (``get_active_shop``).
4. A partner reviewer (``api/reviewer.py`` ``JULI_PIN_ENDPOINTS``, ``admit_juli_pin``, checked
   before the capability): the sample pin (no card send: 403) and Juli's writable sandbox pin;
   any other pin 403 ``read_only``. The sandbox send is the same Tự tạo card path, audited
   ``reviewer_sandbox_approve``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.background import BackgroundTask

from juli_backend.api import reviewer as reviewer_gate
from juli_backend.api.capability_gate import check_open
from juli_backend.api.dependencies import get_active_shop, require_writable_shop
from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, User, get_session
from juli_backend.database.database import ensure_worker_session_factory
from juli_backend.services import agent_runs, juli_agent_api
from juli_backend.services.agent import abuse_limits as agent_abuse_limits
from juli_backend.services.juli_agent_api import ChatError, Engine, PortsFactory
from juli_backend.services.ops import audit

logger = logging.getLogger(__name__)

CAPABILITY = "read_shop_totals"
DATA_PLATFORMS: tuple[str, ...] = ("shopee", "tiktok")
OPERATION_ASK = "juli_ask"


async def _flag_on() -> None:
    if not juli_agent_api.config.flag_state().on:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


router = APIRouter(prefix="/demo/juli", tags=["juli-agent"], dependencies=[Depends(_flag_on)])


async def _admit(request: Request, session: AsyncSession, shop: Shop) -> Shop:
    """The flag for this shop (404), a reviewer's pin (403, ``admit_juli_pin``), then the
    capability (``read_shop_totals`` on Shopee or TikTok; a TikTok shop reaches the engine)."""
    if not juli_agent_api.config.flag_state().allows(shop.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    context = reviewer_gate.reviewer_context(request)
    if context is not None:
        await reviewer_gate.admit_juli_pin(session, context)
    check_open(shop.platform, CAPABILITY, DATA_PLATFORMS)
    return shop


async def juli_shop(
    request: Request,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> Shop:
    return await _admit(request, session, shop)


async def juli_writable_shop(
    request: Request,
    shop: Shop = Depends(require_writable_shop),
    session: AsyncSession = Depends(get_session),
) -> Shop:
    return await _admit(request, session, shop)


# -- overridable dependencies --------------------------------------------------------------------


def get_engine() -> Engine:
    return juli_agent_api.get_engine()


def get_ports_factory() -> PortsFactory:
    return juli_agent_api.get_ports_factory()


async def get_run_session_factory() -> async_sessionmaker[AsyncSession]:
    """Sessions for the run and the stream: both outlive the request session."""
    return ensure_worker_session_factory(agent_runs.run_events_database_url())


def get_poll_interval_s() -> float:
    return juli_agent_api.events.DEFAULT_POLL_INTERVAL_S


def get_card_creator() -> juli_agent_api.CardCreator:
    return juli_agent_api.create_via_manual


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _refused(exc: ChatError) -> HTTPException:
    detail: dict[str, Any] = {"code": exc.code, "message": exc.message, **exc.extra}
    headers = None
    if exc.status == status.HTTP_429_TOO_MANY_REQUESTS:
        headers = {"Retry-After": str(exc.extra.get("retry_after_seconds", 60))}
    return HTTPException(status_code=exc.status, detail=detail, headers=headers)


def _templates(engine: Engine) -> list[juli_agent_api.TemplateInfo]:
    try:
        return engine.templates()
    except juli_agent_api.EngineUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "juli_unavailable", "message": "Juli đang gặp sự cố, thử lại sau"},
        ) from None


# -- bodies ------------------------------------------------------------------------------------


class Choice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: Literal["metric", "window", "product", "chain"]
    value: str = Field(min_length=1, max_length=200)


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: uuid.UUID | None = None
    text: str | None = Field(default=None, max_length=2000)
    template: str | None = Field(default=None, max_length=64)
    choice: Choice | None = None


class AskOut(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID


class SendBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_label: str | None = Field(default=None, max_length=200)
    acknowledge_breaches: bool = False


class SendOut(BaseModel):
    card_code: str | None
    card_id: str | None
    status: str | None
    already_sent: bool


class TemplateOut(BaseModel):
    key: str
    label_vi: str


class ShopStateOut(BaseModel):
    """The same sources as ``require_writable_shop`` (term read-only, pending deletion)."""

    read_only: bool


class TemplatesOut(BaseModel):
    templates: list[TemplateOut]
    shop_state: ShopStateOut


# -- routes ------------------------------------------------------------------------------------


@router.get("/templates", response_model=TemplatesOut)
async def list_templates(
    shop: Shop = Depends(juli_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    engine: Engine = Depends(get_engine),
) -> TemplatesOut:
    """The 5 templates and the shop's state for the page (``read_only``: Gửi / ask disabled)."""
    from juli_backend.services.privacy import deletion_pending
    from juli_backend.services.subscriptions import is_read_only

    read_only = deletion_pending(user) or await is_read_only(session, shop.id)
    await session.commit()
    return TemplatesOut(
        templates=[TemplateOut(key=t.key, label_vi=t.label_vi) for t in _templates(engine)],
        shop_state=ShopStateOut(read_only=read_only),
    )


@router.post("/ask", status_code=status.HTTP_202_ACCEPTED, response_model=AskOut)
async def ask(
    body: AskBody,
    shop: Shop = Depends(juli_writable_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    engine: Engine = Depends(get_engine),
    ports_factory: PortsFactory = Depends(get_ports_factory),
    run_factory: async_sessionmaker[AsyncSession] = Depends(get_run_session_factory),
) -> AskOut:
    if juli_agent_api.active_runs() >= juli_agent_api.config.max_concurrent_runs():
        # this process runs as many answers as it may: a short wait, not a queue
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "juli_busy_system", "message": "Juli đang bận, thử lại sau"},
            headers={"Retry-After": "10"},
        )
    templates = _templates(engine) if body.template is not None else []
    try:
        started = await juli_agent_api.start_ask(
            session,
            shop_id=shop.id,
            platform=shop.platform,
            user_id=user.id,
            conversation_id=body.conversation_id,
            text=body.text,
            template=body.template,
            choice=body.choice.model_dump() if body.choice is not None else None,
            templates=templates,
            now=_now(),
        )
        switch_platforms = await juli_agent_api.other_platforms(session, shop, user.id)
        await session.commit()
    except ChatError as exc:
        await session.rollback()
        if exc.status == status.HTTP_429_TOO_MANY_REQUESTS:
            agent_abuse_limits.log_abuse_limit_exceeded(
                logger,
                shop_id=str(shop.id),
                operation=OPERATION_ASK,
                retry_after_seconds=int(exc.extra.get("retry_after_seconds", 0)),
            )
        raise _refused(exc) from None
    juli_agent_api.schedule(
        message_id=started.message_id,
        request=started.request,
        engine=engine,
        ports_factory=ports_factory,
        write_factory=run_factory,
        read_factory=run_factory,
        switch_platforms=switch_platforms,
    )
    logger.info(
        "juli_agent_ask_started",
        extra={"shop_id": str(shop.id), "message_id": str(started.message_id)},
    )
    return AskOut(conversation_id=started.conversation_id, message_id=started.message_id)


class _StreamSlot:
    """The per-shop SSE slot, released exactly once whichever exit comes first."""

    def __init__(self, gate: agent_abuse_limits.AbuseLimitGate, shop_id: str) -> None:
        self._gate, self._shop_id, self._released = gate, shop_id, False

    async def release(self) -> None:
        if not self._released:
            self._released = True
            await self._gate.release_stream(self._shop_id)


async def _with_stream_slot(generator: AsyncIterator[str], slot: _StreamSlot) -> AsyncIterator[str]:
    try:
        async for chunk in generator:
            yield chunk
    finally:
        await slot.release()


def _sse_response(
    generator: AsyncIterator[str], gate: agent_abuse_limits.AbuseLimitGate, shop_id: str
) -> StreamingResponse:
    """The stream, its slot released on a clean end, a mid-stream end AND a disconnect before
    the first byte: a generator that never started has no ``finally`` to run, so the response's
    background task releases too (idempotent). The gate's one-hour TTL stays the backstop."""
    slot = _StreamSlot(gate, shop_id)
    return StreamingResponse(
        _with_stream_slot(generator, slot),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
        background=BackgroundTask(slot.release),
    )


@router.get("/messages/{message_id}/events")
async def stream_message_events(
    message_id: uuid.UUID,
    request: Request,
    after: int | None = Query(default=None, ge=0),
    shop: Shop = Depends(juli_shop),
    session: AsyncSession = Depends(get_session),
    run_factory: async_sessionmaker[AsyncSession] = Depends(get_run_session_factory),
    poll_interval_s: float = Depends(get_poll_interval_s),
) -> StreamingResponse:
    try:
        await juli_agent_api.owned_answer(session, shop.id, message_id)
    except ChatError as exc:
        raise _refused(exc) from None
    await session.commit()
    # The same per-shop SSE concurrency slot as the agent-run stream (ADR-075 decision 4),
    # taken only after tenant scoping.
    gate = agent_abuse_limits.get_agent_abuse_limit_gate()
    slot = await gate.try_acquire_stream(str(shop.id))
    if not slot.allowed:
        agent_abuse_limits.log_abuse_limit_exceeded(
            logger,
            shop_id=str(shop.id),
            operation=agent_abuse_limits.OPERATION_SSE,
            retry_after_seconds=slot.retry_after_seconds,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many concurrent event streams for this shop; "
            f"retry in {slot.retry_after_seconds}s",
            headers={"Retry-After": str(slot.retry_after_seconds)},
        )
    generator = juli_agent_api.event_stream(
        message_id=message_id,
        shop_id=shop.id,
        after_seq=juli_agent_api.resolve_after(request.headers.get("last-event-id"), after),
        session_factory=run_factory,
        poll_interval_s=poll_interval_s,
    )
    return _sse_response(generator, gate, str(shop.id))


@router.post("/messages/{message_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_message(
    message_id: uuid.UUID,
    shop: Shop = Depends(juli_writable_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """ "Dừng". Never rate-limited (the agent-run cancel rule); idempotent."""
    try:
        row = await juli_agent_api.request_cancel(session, shop.id, message_id, now=_now())
    except ChatError as exc:
        raise _refused(exc) from None
    answer_status = row.status
    await session.commit()
    juli_agent_api.cancel_local(message_id)
    return {"status": answer_status}


@router.get("/conversations")
async def list_conversations(
    platform: Literal["shopee", "tiktok"] | None = Query(default=None),
    shop: Shop = Depends(juli_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows = await juli_agent_api.list_conversations(session, shop.id, platform=platform)
    await session.commit()
    return {"conversations": rows}


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID,
    shop: Shop = Depends(juli_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        out = await juli_agent_api.get_conversation(session, shop.id, conversation_id)
    except ChatError as exc:
        raise _refused(exc) from None
    await session.commit()
    return out


@router.post("/cards/{draft_ref}/send", response_model=SendOut)
async def send_card(
    draft_ref: str,
    body: SendBody,
    request: Request,
    shop: Shop = Depends(juli_writable_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    create: juli_agent_api.CardCreator = Depends(get_card_creator),
) -> SendOut:
    """ "Gửi": the card through the Tự tạo path (origin ``agent``), into Đề xuất."""
    try:
        out = await juli_agent_api.send_card(
            session,
            shop_id=shop.id,
            user_id=user.id,
            draft_ref=draft_ref,
            version_label=body.version_label,
            now=_now(),
            acknowledge_breaches=body.acknowledge_breaches,
            create=create,
        )
        if not out["already_sent"]:
            # D73: a reviewer's real write on the sandbox pin is audited (no-op for a seller)
            await reviewer_gate.audit_reviewer_run_action(
                session,
                request,
                audit.ACTION_REVIEWER_SANDBOX_APPROVE,
                shop_id=shop.id,
                after={"endpoint": "juli_agent:send_card", "card_code": out["card_code"]},
            )
        await session.commit()
    except ChatError as exc:
        await session.rollback()
        raise _refused(exc) from None
    except Exception:
        await session.rollback()
        raise
    return SendOut(**out)


@router.post("/cards/{draft_ref}/dismiss")
async def dismiss_card(
    draft_ref: str,
    shop: Shop = Depends(juli_writable_shop),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """ "Bỏ qua": logged on the draft, nothing else is written."""
    try:
        out = await juli_agent_api.dismiss_card(
            session, shop_id=shop.id, user_id=user.id, draft_ref=draft_ref, now=_now()
        )
    except ChatError as exc:
        raise _refused(exc) from None
    await session.commit()
    return out
