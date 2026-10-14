"""The partner reviewer gate, shop pin and response mask (fast track P32-A, D42).

Contract ``fasttrack/contracts/p32-reviewer-access.md`` §2-§3. Three pieces:

- :func:`reviewer_gate` -- bound into ``core.security.get_current_user`` by
  :func:`install`. Runs for every reviewer token before the ``users`` read and
  before any route code: account state (expired / revoked / unknown → 403),
  then the **allowlist** of ``(method, route template)`` (anything else → 403,
  audited), then the once-per-session sign-in audit. It leaves a
  :class:`ReviewerContext` on ``request.state``.
- :func:`enter_reviewer_shop` -- what ``get_active_shop`` does for a reviewer:
  only the alias id is accepted in ``X-Shop-Id``; the pinned shop
  (``REVIEWER_SHOP_ID``) is entered through the ops view-as machinery.
- :class:`ReviewerMaskMiddleware` -- masks every JSON body of a reviewer
  request (D25.6 / ADR-038 §8); a non-JSON body becomes 502 (fail closed).

The guarantee that a reviewer never writes is the allowlist: no route that is
not a read (or the audit-only simulation) is on it, whatever the UI shows.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from juli_backend.core.security import (
    REVIEWER_DENIED_HEADER,
    VerifiedToken,
    bind_reviewer_gate,
)
from juli_backend.database import Shop, set_tenant_context
from juli_backend.services import reviewer as reviewer_service
from juli_backend.services.ops import audit
from juli_backend.services.reviewer import MaskDictionary, ReviewerAccount

logger = logging.getLogger(__name__)

#: ``request.state`` attribute (and ``scope["state"]`` key) of a reviewer request.
STATE_KEY = "juli_reviewer"

_GET = "GET"
_R = "juli_backend.api.routes."
#: Contract §2. Keyed by the matched endpoint (``module:function``) and method:
#: unambiguous whatever router prefix a route sits under (FastAPI ≥ 0.13x keeps
#: only the innermost router's prefix in ``route.path``). A renamed or moved
#: endpoint drops off the list -- refused, never widened.
#: ``tests/unit/test_reviewer_no_write.py`` pins each entry to its URL template.
ALLOWED_ENDPOINTS: frozenset[tuple[str, str]] = frozenset(
    {
        (_GET, _R + "shops:list_shops"),  # /v1/shops
        (_GET, _R + "shops:get_current_shop"),  # /v1/shops/me
        (_GET, _R + "shops:get_current_shop_term"),  # /v1/shops/me/term
        (_GET, _R + "shops:get_current_shop_permissions"),  # /v1/shops/me/permissions
        (_GET, _R + "shops:get_current_shop_onboarding"),  # /v1/shops/me/onboarding
        (_GET, _R + "demo_analysis:get_demo_analysis"),  # /v1/demo/analysis
        (_GET, _R + "demo_analysis:get_demo_metric_ranking"),  # /v1/demo/analysis/rankings
        (_GET, _R + "demo_decisions:list_demo_decisions"),  # /v1/demo/decisions
        (_GET, _R + "demo_decisions:get_demo_decision"),  # /v1/demo/decisions/{id}
        (_GET, _R + "agent_runs:list_demo_runs"),  # /v1/demo/runs
        (_GET, _R + "demo_run_flows:get_demo_run"),  # /v1/demo/runs/{run_id}
        (_GET, _R + "demo_run_changes:get_run_changes"),  # …/changes
        (_GET, _R + "demo_run_flows:get_run_instructions"),  # …/instructions
        (_GET, _R + "demo_run_flows:get_run_measurement"),  # …/measurement
        (_GET, _R + "demo_run_changes:list_revert_questions"),  # /v1/demo/revert-questions
        (_GET, _R + "demo_rules:get_shop_rules"),  # /v1/demo/rules
        (_GET, _R + "demo_content_analysis:list_content_analyses"),  # /v1/demo/content-analysis
        (_GET, _R + "demo_content_analysis:get_content_analysis"),  # …/{analysis_id}
        (_GET, _R + "reviewer:reviewer_me"),  # /v1/reviewer/me
        ("POST", _R + "reviewer:simulate_decision"),  # /v1/reviewer/decisions/{id}/simulate
    }
)

_DENIED_DETAIL = {
    "unknown": "Tài khoản dùng thử không hợp lệ",
    "revoked": "Tài khoản dùng thử này đã bị thu hồi",
    "expired": "Tài khoản dùng thử này đã hết hạn",
    "read_only": "Tài khoản dùng thử chỉ xem · thao tác này bị chặn",
    "unconfigured": "Tài khoản dùng thử chưa sẵn sàng",
    "shop": "Shop not accessible",
}


@dataclass
class ReviewerContext:
    account: ReviewerAccount
    platform: str
    #: The pinned (real) shop id -- never sent to the reviewer.
    shop_id: uuid.UUID
    alias_id: uuid.UUID
    dictionary: MaskDictionary | None = None
    shop: Shop | None = field(default=None, repr=False)

    def mask_dictionary(self) -> MaskDictionary:
        return self.dictionary or MaskDictionary(shop_id=self.shop_id, alias_id=self.alias_id)


def reviewer_context(request: Request) -> ReviewerContext | None:
    value = getattr(request.state, STATE_KEY, None)
    return value if isinstance(value, ReviewerContext) else None


def _deny(code: str, *, status_code: int = status.HTTP_403_FORBIDDEN) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=_DENIED_DETAIL[code],
        headers={REVIEWER_DENIED_HEADER: code},
    )


def endpoint_key(request: Request) -> str | None:
    """``module:function`` of the endpoint FastAPI matched, or None."""
    endpoint = request.scope.get("endpoint")
    module = getattr(endpoint, "__module__", None)
    name = getattr(endpoint, "__qualname__", None)
    if not isinstance(module, str) or not isinstance(name, str):
        return None
    return f"{module}:{name}"


def is_allowed(method: str, endpoint: str | None) -> bool:
    return endpoint is not None and (method.upper(), endpoint) in ALLOWED_ENDPOINTS


async def reviewer_gate(request: Request, session: AsyncSession, token: VerifiedToken) -> None:
    """Refuse (raise) or admit a reviewer request; see the module docstring."""
    method = request.method.upper()
    template = endpoint_key(request)
    account = await reviewer_service.load_account(session, token.user_id)
    if account is None or account.platform != token.reviewer_platform:
        await session.rollback()
        logger.warning("reviewer_unknown", extra={"user_id": str(token.user_id)})
        raise _deny("unknown")
    state = account.status()
    if state != reviewer_service.accounts.STATUS_ACTIVE:
        await session.rollback()
        logger.info("reviewer_denied", extra={"user_id": str(token.user_id), "state": state})
        raise _deny(state)
    shop_id = reviewer_service.config.reviewer_shop_id()
    if shop_id is None:
        await session.rollback()
        logger.error("reviewer_shop_unconfigured")
        raise _deny("unconfigured", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if not is_allowed(method, template):
        action = (
            audit.ACTION_REVIEWER_READ_REFUSED
            if method in (_GET, "HEAD", "OPTIONS")
            else audit.ACTION_REVIEWER_WRITE_REFUSED
        )
        await audit.record(
            session,
            account.actor,
            action,
            shop_id=shop_id,
            after={
                "platform": account.platform,
                "method": method,
                "endpoint": template,
                "path": request.url.path,
            },
        )
        await session.commit()
        logger.warning(
            "reviewer_request_refused",
            extra={"platform": account.platform, "method": method, "endpoint": template},
        )
        raise _deny("read_only")
    if token.session_id and token.session_id != account.last_session_id:
        if await reviewer_service.accounts.claim_sign_in(session, account, token.session_id):
            await audit.record(
                session,
                account.actor,
                audit.ACTION_REVIEWER_SIGN_IN,
                shop_id=shop_id,
                after={"platform": account.platform, "session_id": token.session_id},
            )
    # Ends the account read / sign-in transaction (and the juli_ops role with it):
    # ``load_authenticated_user`` must start from a clean session.
    await session.commit()
    logger.info(
        "reviewer_request",
        extra={"platform": account.platform, "method": method, "endpoint": template},
    )
    setattr(
        request.state,
        STATE_KEY,
        ReviewerContext(
            account=account,
            platform=account.platform,
            shop_id=shop_id,
            alias_id=reviewer_service.config.shop_alias_id(shop_id),
        ),
    )


async def enter_reviewer_shop(
    session: AsyncSession, context: ReviewerContext, x_shop_id: str | None
) -> Shop:
    """The pinned shop, in its read scope; ``X-Shop-Id`` must be the alias (None: skip check)."""
    if x_shop_id is not None and x_shop_id.strip().lower() != str(context.alias_id):
        logger.warning("reviewer_shop_refused", extra={"platform": context.platform})
        raise _deny("shop")
    if context.shop is not None:
        return context.shop
    shop = await reviewer_service.enter_shop_read_scope(session, context.shop_id)
    if shop is None:
        logger.error("reviewer_shop_missing")
        raise _deny("unconfigured", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    set_tenant_context(shop.id, shop.user_id)
    context.dictionary = await reviewer_service.catalog.load_dictionary(session, shop)
    context.shop = shop
    return shop


# -- response mask ------------------------------------------------------------------------


def _headers_without_length(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    return [(k, v) for k, v in headers if k.lower() != b"content-length"]


def masked_body(context: ReviewerContext, body: bytes) -> tuple[int | None, bytes]:
    """(override status or None, new body) for one reviewer response body."""
    if not body:
        return None, body
    try:
        payload: Any = json.loads(body)
    except ValueError:
        logger.error("reviewer_response_not_json")
        return 502, json.dumps({"detail": "Masked response unavailable"}).encode()
    masked = reviewer_service.mask_payload(payload, context.mask_dictionary())
    return None, json.dumps(masked, ensure_ascii=False, separators=(",", ":")).encode()


class ReviewerMaskMiddleware:
    """Pure ASGI: buffer and mask the body of every reviewer request's response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start: Message | None = None
        chunks: list[bytes] = []

        async def wrapped(message: Message) -> None:
            nonlocal start
            if message["type"] == "http.response.start":
                state = scope.get("state")
                context = state.get(STATE_KEY) if isinstance(state, dict) else None
                if not isinstance(context, ReviewerContext):
                    await send(message)
                    return
                start = message
                return
            if message["type"] == "http.response.body" and start is not None:
                chunks.append(message.get("body", b""))
                if message.get("more_body", False):
                    return
                state = scope.get("state")
                context = state[STATE_KEY]
                override, body = masked_body(context, b"".join(chunks))
                headers = _headers_without_length(list(start.get("headers", [])))
                headers.append((b"content-length", str(len(body)).encode()))
                if override is not None:
                    headers = [(k, v) for k, v in headers if k.lower() != b"content-type"]
                    headers.append((b"content-type", b"application/json"))
                await send(
                    {
                        **start,
                        "status": override or start["status"],
                        "headers": headers,
                    }
                )
                await send({"type": "http.response.body", "body": body, "more_body": False})
                return
            await send(message)

        await self.app(scope, receive, wrapped)


def install(app: FastAPI) -> None:
    """Bind the gate and add the mask middleware (``create_app``)."""
    bind_reviewer_gate(reviewer_gate)
    app.add_middleware(ReviewerMaskMiddleware)


__all__ = [
    "ALLOWED_ENDPOINTS",
    "endpoint_key",
    "STATE_KEY",
    "ReviewerContext",
    "ReviewerMaskMiddleware",
    "enter_reviewer_shop",
    "install",
    "is_allowed",
    "reviewer_context",
    "reviewer_gate",
]
