"""Conversations and asks: the rows a question writes before its run starts, and the history.

Everything here runs on the request's session, inside the shop scope ``get_active_shop`` set,
and never commits (the route does). Failures are typed :class:`ChatError` with a
machine-readable ``code`` and the HTTP status the route maps them to.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.agent_chat import (
    ROLE_ASSISTANT,
    ROLE_USER,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_RUNNING,
    AgentCardDraft,
    AgentConversation,
    AgentMessage,
)
from juli_backend.services.agent.abuse_limits import AbuseLimitDecision
from juli_backend.services.juli_agent_api import config
from juli_backend.services.juli_agent_api.engine import TemplateInfo

ERROR_BAD_ASK = "juli_ask_invalid"
ERROR_UNKNOWN_TEMPLATE = "juli_unknown_template"
ERROR_NO_PENDING_CHOICE = "juli_no_pending_choice"
ERROR_BUSY = "juli_busy"
ERROR_LIMITED = "juli_limited"
ERROR_NOT_FOUND = "juli_not_found"

#: A run that has not finished in this long is dead (its process went away): it no longer
#: blocks its conversation and is marked failed on the next ask.
STALE_RUNNING_AFTER = timedelta(minutes=15)
TITLE_MAX = 200
HISTORY_LIMIT = 50


class ChatError(Exception):
    def __init__(self, code: str, status: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message
        self.extra = extra


@dataclass(frozen=True)
class AskStarted:
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    #: the engine's ``AskRequest`` fields (contract §T1), minus ``as_of`` (latest day)
    request: dict[str, Any]


# -- limits ------------------------------------------------------------------------------------


async def check_limits(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    now: datetime,
    user_id: uuid.UUID | None = None,
) -> tuple[AbuseLimitDecision, datetime | None]:
    """30 asks per rolling hour and 200 per rolling day per shop, counted on stored answers.

    ``user_id`` (a partner reviewer): the limit is that reviewer's own, not the shop's -- the
    sample shop is shared by every reviewer, so one must not use up another's asks. The count
    runs under the pinned shop's scope (RLS), so it is per reviewer on that pin.

    Postgres-counted (not Redis): the answers are the record of what was asked, they survive
    a restart, and the retry time is exact -- when the oldest ask in the full window leaves it.
    """
    for window, limit in (
        (timedelta(hours=1), config.limit_per_hour()),
        (timedelta(days=1), config.limit_per_day()),
    ):
        since = now - window
        base = select(AgentMessage.created_at).where(
            AgentMessage.shop_id == shop_id,
            AgentMessage.role == ROLE_ASSISTANT,
            AgentMessage.created_at > since,
        )
        if user_id is not None:
            base = base.where(AgentMessage.created_by_user_id == user_id)
        count = await session.scalar(select(func.count()).select_from(base.subquery()))
        if (count or 0) >= limit:
            oldest = await session.scalar(
                base.order_by(AgentMessage.created_at).offset(int(count or 0) - limit).limit(1)
            )
            retry_at = (oldest or now) + window
            seconds = max(1, int((retry_at - now).total_seconds()))
            return AbuseLimitDecision(allowed=False, retry_after_seconds=seconds), retry_at
    return AbuseLimitDecision(allowed=True, retry_after_seconds=0), None


# -- cost guard --------------------------------------------------------------------------------

ERROR_COST_CAP = "juli_cost_cap"


async def check_cost_guard(session: AsyncSession, shop_id: uuid.UUID, *, now: datetime) -> None:
    """The existing LLM cost guard (which counts the Juli tab's own spend).

    Refused (429 ``juli_cost_cap``) when the system-wide monthly cap is reached
    (``ops.system_cap.system_cap_reached``) or when the shop's month spend
    (``shop_rules.openai_cap.openai_spend_this_month``: runs + content analyses + the Juli
    tab) reaches the shop's monthly cap (``openai_monthly_cap_usd``).
    """
    from juli_backend.services.ops.system_cap import system_cap_reached
    from juli_backend.services.shop_rules.openai_cap import (
        openai_monthly_cap_usd,
        openai_spend_this_month,
    )

    aware = now.replace(tzinfo=UTC)
    if await system_cap_reached(session, now=aware):
        raise ChatError(ERROR_COST_CAP, 429, "the monthly LLM limit is reached", scope="system")
    spend = await openai_spend_this_month(session, shop_id, now=aware)
    cap = await openai_monthly_cap_usd(session, shop_id)
    if spend >= cap.usd:
        raise ChatError(ERROR_COST_CAP, 429, "the monthly LLM limit is reached", scope="shop")


# -- ask ---------------------------------------------------------------------------------------


def _title_of(text: str | None, template: TemplateInfo | None) -> str:
    if text:
        return " ".join(text.split())[:TITLE_MAX] or "Câu hỏi"
    if template is not None:
        return template.label_vi[:TITLE_MAX]
    return "Câu hỏi"


async def _conversation(
    session: AsyncSession, shop_id: uuid.UUID, conversation_id: uuid.UUID
) -> AgentConversation:
    row = await session.get(AgentConversation, conversation_id)
    if row is None or row.shop_id != shop_id:  # another shop's thread is missing, not forbidden
        raise ChatError(ERROR_NOT_FOUND, 404, "conversation not found")
    return row


async def _retire_stale_runs(
    session: AsyncSession, conversation_id: uuid.UUID, *, now: datetime
) -> None:
    await session.execute(
        update(AgentMessage)
        .where(
            AgentMessage.conversation_id == conversation_id,
            AgentMessage.status == STATUS_RUNNING,
            AgentMessage.updated_at < now - STALE_RUNNING_AFTER,
        )
        .values(status=STATUS_FAILED, updated_at=now)
    )


async def _last_pending(session: AsyncSession, conversation_id: uuid.UUID) -> dict[str, Any] | None:
    """The routing state of the conversation's last answer, if that answer asked a choice."""
    pending = await session.scalar(
        select(AgentMessage.pending)
        .where(
            AgentMessage.conversation_id == conversation_id,
            AgentMessage.role == ROLE_ASSISTANT,
        )
        .order_by(AgentMessage.created_at.desc())
        .limit(1)
    )
    return pending or None


async def start_ask(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    platform: str,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    text: str | None,
    template: str | None,
    choice: dict[str, Any] | None,
    templates: list[TemplateInfo],
    now: datetime,
    reviewer: bool = False,
) -> AskStarted:
    """Write the question and a ``running`` answer; the caller commits, then starts the run.

    Raises ``ChatError``: 422 (not exactly one of text / template / choice, unknown template,
    a choice with nothing pending), 404 (conversation), 409 (an answer is running), 429.
    """
    text = (text or "").strip() or None
    given = [x for x in (text, template, choice) if x is not None]
    if len(given) != 1:
        raise ChatError(ERROR_BAD_ASK, 422, "send exactly one of text, template, choice")
    tpl = None
    if template is not None:
        tpl = next((t for t in templates if t.key == template), None)
        if tpl is None:
            raise ChatError(ERROR_UNKNOWN_TEMPLATE, 422, "unknown template")

    if conversation_id is not None:
        conv = await _conversation(session, shop_id, conversation_id)
        await _retire_stale_runs(session, conv.id, now=now)
        running = await session.scalar(
            select(AgentMessage.id).where(
                AgentMessage.conversation_id == conv.id, AgentMessage.status == STATUS_RUNNING
            )
        )
        if running is not None:
            raise ChatError(ERROR_BUSY, 409, "an answer is still running", message_id=str(running))
    elif choice is not None:
        raise ChatError(ERROR_NO_PENDING_CHOICE, 422, "a choice answers a conversation")

    pending = None
    if choice is not None:
        pending = await _last_pending(session, conv.id)
        if pending is None:
            raise ChatError(ERROR_NO_PENDING_CHOICE, 422, "nothing is waiting for a choice")

    # a partner reviewer: the limits are the reviewer's own, and the cost guard applies
    decision, retry_at = await check_limits(
        session, shop_id, now=now, user_id=user_id if reviewer else None
    )
    if not decision.allowed:
        assert retry_at is not None
        raise ChatError(
            ERROR_LIMITED,
            429,
            "too many questions for this shop",
            retry_at=retry_at.isoformat() + "Z",
            retry_after_seconds=decision.retry_after_seconds,
        )
    if reviewer:
        await check_cost_guard(session, shop_id, now=now)

    if conversation_id is None:
        conv = AgentConversation(
            id=uuid.uuid4(),
            shop_id=shop_id,
            platform=platform,
            title=_title_of(text, tpl),
            created_by_user_id=user_id,
            created_at=now,
            updated_at=now,
        )
        session.add(conv)
    else:
        conv.updated_at = now

    question = AgentMessage(
        id=uuid.uuid4(),
        shop_id=shop_id,
        conversation_id=conv.id,
        role=ROLE_USER,
        question_text=text,
        template=template,
        choice=choice,
        events=[],
        status=STATUS_DONE,
        created_by_user_id=user_id,
        created_at=now,
        updated_at=now,
    )
    answer = AgentMessage(
        id=uuid.uuid4(),
        shop_id=shop_id,
        conversation_id=conv.id,
        role=ROLE_ASSISTANT,
        events=[],
        status=STATUS_RUNNING,
        created_by_user_id=user_id,
        # one tick later: the answer sorts after its question
        created_at=now + timedelta(microseconds=1),
        updated_at=now,
    )
    session.add_all([question, answer])
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:  # the one-running index: a concurrent ask won the race
        raise ChatError(ERROR_BUSY, 409, "an answer is still running") from None
    return AskStarted(
        conversation_id=conv.id,
        message_id=answer.id,
        request={
            "shop_id": shop_id,
            "platform": platform,
            "text": text,
            "template": template,
            "choice": choice,
            "pending": pending,
            "as_of": None,
        },
    )


# -- platform hint -----------------------------------------------------------------------------


async def other_platforms(session: AsyncSession, shop: Any, user_id: uuid.UUID) -> frozenset[str]:
    """Platforms of the business's (else the user's) other shops: when ``unsupported`` may say
    "switch to TikTok / Shopee". Read under the request's scope (the ``shops`` policies)."""
    from juli_backend.models.models import Shop

    stmt = select(Shop.platform).where(Shop.id != shop.id)
    business_id = getattr(shop, "business_id", None)
    if business_id is not None:
        stmt = stmt.where(Shop.business_id == business_id)
    else:
        stmt = stmt.where(Shop.user_id == user_id)
    found = {str(p) for p in await session.scalars(stmt)}
    return frozenset(found - {shop.platform})


# -- cancel ------------------------------------------------------------------------------------


async def owned_answer(
    session: AsyncSession, shop_id: uuid.UUID, message_id: uuid.UUID
) -> AgentMessage:
    row = await session.get(AgentMessage, message_id)
    if row is None or row.shop_id != shop_id or row.role != ROLE_ASSISTANT:
        raise ChatError(ERROR_NOT_FOUND, 404, "message not found")
    return row


async def request_cancel(
    session: AsyncSession, shop_id: uuid.UUID, message_id: uuid.UUID, *, now: datetime
) -> AgentMessage:
    """Idempotent: flags a running answer; a finished one is left as it is."""
    row = await owned_answer(session, shop_id, message_id)
    if row.status == STATUS_RUNNING:
        row.cancel_requested = True
        row.updated_at = now
    return row


# -- history -----------------------------------------------------------------------------------


def _data_until_vi(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        if event.get("type") == "done":
            value = (event.get("payload") or {}).get("data_until_vi")
            return str(value) if value else None
    return None


def _message_json(row: AgentMessage, drafts: list[AgentCardDraft]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(row.id),
        "role": row.role,
        "status": row.status,
        "created_at": row.created_at.isoformat() + "Z",
    }
    if row.role == ROLE_USER:
        out.update({"text": row.question_text, "template": row.template, "choice": row.choice})
    else:
        events = list(row.events or [])
        out.update(
            {
                "events": events,
                "stop_reasons": row.stop_reasons,
                "cost_usd": float(row.cost_usd) if row.cost_usd is not None else None,
                "ms": row.ms,
                "data_until_vi": _data_until_vi(events),
                "cards": [
                    {
                        "draft_ref": d.draft_ref,
                        "status": d.status,
                        "sent_card_code": d.card_code,
                        "version_label": d.version_label,
                    }
                    for d in drafts
                ],
            }
        )
    return out


def _conversation_json(row: AgentConversation) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "platform": row.platform,
        "title": row.title,
        "created_at": row.created_at.isoformat() + "Z",
        "updated_at": row.updated_at.isoformat() + "Z",
    }


async def list_conversations(
    session: AsyncSession, shop_id: uuid.UUID, *, platform: str | None = None
) -> list[dict[str, Any]]:
    """The shop's threads, newest first -- every member sees the same list."""
    stmt = select(AgentConversation).where(AgentConversation.shop_id == shop_id)
    if platform is not None:
        stmt = stmt.where(AgentConversation.platform == platform)
    rows = await session.scalars(
        stmt.order_by(AgentConversation.updated_at.desc()).limit(HISTORY_LIMIT)
    )
    return [_conversation_json(r) for r in rows]


async def get_conversation(
    session: AsyncSession, shop_id: uuid.UUID, conversation_id: uuid.UUID
) -> dict[str, Any]:
    conv = await _conversation(session, shop_id, conversation_id)
    rows = list(
        await session.scalars(
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conv.id)
            .order_by(AgentMessage.created_at)
        )
    )
    drafts: dict[uuid.UUID, list[AgentCardDraft]] = {}
    ids = [r.id for r in rows if r.role == ROLE_ASSISTANT]
    if ids:
        for d in await session.scalars(
            select(AgentCardDraft)
            .where(AgentCardDraft.message_id.in_(ids))
            .order_by(AgentCardDraft.created_at)
        ):
            drafts.setdefault(d.message_id, []).append(d)
    return {
        **_conversation_json(conv),
        "messages": [_message_json(r, drafts.get(r.id, [])) for r in rows],
    }


__all__ = [
    "ERROR_BAD_ASK",
    "ERROR_BUSY",
    "ERROR_COST_CAP",
    "ERROR_LIMITED",
    "ERROR_NOT_FOUND",
    "ERROR_NO_PENDING_CHOICE",
    "ERROR_UNKNOWN_TEMPLATE",
    "STALE_RUNNING_AFTER",
    "AskStarted",
    "ChatError",
    "check_cost_guard",
    "check_limits",
    "get_conversation",
    "list_conversations",
    "other_platforms",
    "owned_answer",
    "request_cancel",
    "start_ask",
]
