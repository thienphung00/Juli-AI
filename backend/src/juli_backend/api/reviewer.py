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
  (``REVIEWER_SHOP_ID``) is entered through the ops view-as machinery. With
  no pin (D42 amendment, 2026-10-15: the reviewer uses the demo's sample shop,
  which needs no API) the reviewer has no shop at all: 403 ``shop``.
- :class:`ReviewerMaskMiddleware` -- masks every JSON body of a reviewer
  request (D25.6 / ADR-038 §8); a non-JSON body becomes 502 (fail closed).

The guarantee that a reviewer never writes is the allowlist: no route that is
not a read (or the audit-only simulation) is on it, whatever the UI shows.

Fast track P64 (D73): a pin to Juli's own TikTok Shop SANDBOX shop is the "live
sandbox" mode (``services/reviewer/sandbox.classify_pin``): no identity mask, and
more allowlisted routes -- only there: ``/v1/reviewer/shop`` (connection + synced
at), ``/v1/reviewer/shop/sync`` and (D73.4) the seller's own agent-run routes
(:data:`SANDBOX_RUN_ENDPOINTS`, with "Hoàn tác" since P70), plus the shop's rule
writes ("Đặt ngưỡng" / "Sửa quy tắc", :data:`SANDBOX_RULE_ENDPOINTS`) on that shop's
own Juli rows. Duyệt starts the same agent run a seller's approve starts, streamed
over the same SSE route; its writes reach TikTok only through the sandbox shop's
``SandboxWriteClientFactory`` (``services/agent/composition``). Each refuses (403
``sandbox_only``) unless the pin is a writable sandbox shop; the simulation refuses
(403 ``sandbox_live``) when it is. Every reviewer request is marked
(``integrations.tiktok.mark_reviewer_session``) so the production write resolver and
factory refuse it whatever route it reaches.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from juli_backend.core.security import (
    REVIEWER_DENIED_HEADER,
    REVIEWER_USER_STATE_KEY,
    VerifiedToken,
    bind_reviewer_gate,
)
from juli_backend.database import Shop, set_tenant_context
from juli_backend.database.tenant_context import _apply_tenant_context_to_session
from juli_backend.integrations.tiktok import mark_reviewer_session
from juli_backend.models.models import ActionCardApproval
from juli_backend.services import reviewer as reviewer_service
from juli_backend.services.agent_runs import RunViewer
from juli_backend.services.ops import audit
from juli_backend.services.reviewer import MaskDictionary, PinMode, ReviewerAccount

logger = logging.getLogger(__name__)

#: ``request.state`` attribute (and ``scope["state"]`` key) of a reviewer request.
STATE_KEY = "juli_reviewer"

_GET = "GET"
_R = "juli_backend.api.routes."
#: P64 (D73.4): the seller's own agent-run routes, for a reviewer ONLY on a writable
#: sandbox pin (``enter_reviewer_shop`` refuses them, 403 ``sandbox_only``, on any other
#: pin). Duyệt starts the same run a seller's approve starts; the run streams over the
#: same SSE route and waits for the same confirmation. Seller Center "applied" stays off
#: the list (read-only); the rules are :data:`SANDBOX_RULE_ENDPOINTS`.
#:
#: P70 (owner, 2026-10-28): "Hoàn tác" joins the list. A revert starts a NEW run that
#: stops at the same confirmation before any TikTok write (``RevertPlanner`` + the CONFIRM
#: pause), and that write goes through the same sandbox write leg as Duyệt's
#: (``workers/tasks/agent_workflow._write_resources_for_leg``) -- same safety as Duyệt. The
#: route itself refuses a run the reviewer did not start (P66, ``reviewer_started_run``).
#: The day-7 "Giữ thay đổi" (``dismiss_revert_question``) stays off: the sandbox shop has
#: no measurement, so the panel never asks it.
SANDBOX_RUN_ENDPOINTS: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", _R + "demo_execution:approve_demo_decision"),  # /v1/demo/decisions/{id}/approve
        (_GET, _R + "agent_runs:stream_run_events"),  # /v1/demo/runs/{run_id}/events
        ("POST", _R + "agent_runs:submit_confirmation_decision"),  # …/confirmations/{id}
        ("POST", _R + "agent_runs:cancel_run"),  # /v1/demo/runs/{run_id}/cancel
        ("POST", _R + "demo_run_flows:submit_run_photo"),  # /v1/demo/runs/{run_id}/photo
        ("POST", _R + "demo_run_changes:decline_run"),  # /v1/demo/runs/{run_id}/decline
        ("POST", _R + "demo_run_changes:start_run_revert"),  # /v1/demo/runs/{run_id}/revert
    }
)
#: P64 (D73.4, integration): the seller's own rule writes -- "Đặt ngưỡng" (the stability
#: bands) and "Sửa quy tắc" -- for a reviewer ONLY on a writable sandbox pin, exactly like
#: :data:`SANDBOX_RUN_ENDPOINTS` (403 ``sandbox_only`` + refusal audit on any other pin). They
#: write Juli's own ``shop_rules`` rows for the pinned sandbox shop (its tenant scope); nothing
#: reaches TikTok. Without them a reviewer can never set the bands Duyệt waits for.
SANDBOX_RULE_ENDPOINTS: frozenset[tuple[str, str]] = frozenset(
    {
        ("PUT", _R + "demo_rules:put_shop_rule"),  # /v1/demo/rules/{rule_key}
        ("DELETE", _R + "demo_rules:delete_shop_rule"),  # /v1/demo/rules/{rule_key}
    }
)
#: Every route a reviewer reaches only on a writable sandbox pin.
SANDBOX_ONLY_ENDPOINTS: frozenset[tuple[str, str]] = SANDBOX_RUN_ENDPOINTS | SANDBOX_RULE_ENDPOINTS

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
    | {
        # P64 (D73): the live sandbox routes. On the allowlist for every pin; each one
        # refuses unless the pin is a writable sandbox shop (``require_sandbox_pin``).
        (_GET, _R + "reviewer:reviewer_shop"),  # /v1/reviewer/shop
        ("POST", _R + "reviewer:reviewer_sync_shop"),  # /v1/reviewer/shop/sync
    }
    | SANDBOX_ONLY_ENDPOINTS
)


_DENIED_DETAIL = {
    "unknown": "Tài khoản đối tác không hợp lệ",
    "revoked": "Tài khoản đối tác này đã bị thu hồi",
    "expired": "Tài khoản đối tác này đã hết hạn",
    "read_only": "Tài khoản đối tác chỉ xem · thao tác này bị chặn",
    "unconfigured": "Tài khoản đối tác chưa sẵn sàng",
    "shop": "Shop not accessible",
    # P64 (D73): a live sandbox route on a pin that is not a writable sandbox shop.
    "sandbox_only": "Chỉ dùng được với shop sandbox của Juli",
    # P64 (D73): the simulation on a live sandbox pin (the real routes replace it).
    "sandbox_live": "Shop sandbox thực thi thật · không dùng mô phỏng",
}


@dataclass
class ReviewerContext:
    account: ReviewerAccount
    platform: str
    #: The pinned (real) shop id -- never sent to the reviewer. None: no pin
    #: (``REVIEWER_SHOP_ID`` unset), the reviewer sees the demo's sample shop.
    shop_id: uuid.UUID | None
    alias_id: uuid.UUID | None
    dictionary: MaskDictionary | None = None
    shop: Shop | None = field(default=None, repr=False)
    #: P64 (D73): what the pinned shop is, set when the shop is entered. None until
    #: then -- the mask stays on (fail closed).
    pin: PinMode | None = None
    #: P64 (D73.4): the request is one of :data:`SANDBOX_ONLY_ENDPOINTS` -- refused unless
    #: the pin is a writable sandbox shop.
    sandbox_only: bool = False
    #: The request's method and matched endpoint (the refusal audit names them).
    method: str = ""
    endpoint: str | None = None
    #: P69b: the pinned shop's row + mode from the gate's identity load (None: no pin,
    #: or the shop does not exist -- the shop entry then takes the ops path and refuses).
    pinned: reviewer_service.pin_cache.PinnedShop | None = field(default=None, repr=False)

    @property
    def mask_enabled(self) -> bool:
        return self.pin is None or self.pin.mask

    def mask_dictionary(self) -> MaskDictionary:
        return self.dictionary or MaskDictionary(shop_id=self.shop_id, alias_id=self.alias_id)


def reviewer_context(request: Request) -> ReviewerContext | None:
    value = getattr(request.state, STATE_KEY, None)
    return value if isinstance(value, ReviewerContext) else None


def sandbox_run_viewer(request: Request) -> RunViewer | None:
    """P66: a reviewer on the writable sandbox pin sees its own runs and the shop's runs
    since its account was created -- not the team's older verification runs (C7)."""
    context = reviewer_context(request)
    pin = context.pin if context is not None else None
    if context is None or pin is None or not pin.sandbox:
        return None
    return RunViewer(user_id=context.account.user_id, since=context.account.created_at)


class ConfirmedWriteOut(BaseModel):
    """P67 (D75 Q2): what a sandbox reviewer's run wrote on TikTok (``agent_runs.ConfirmedWrite``):
    ``create_product`` / ``create_promotion`` / ``listing_edit`` / ``price_edit``, the TikTok
    id, when TikTok confirmed it, the discount and the listing fields changed."""

    model_config = ConfigDict(from_attributes=True)

    kind: str
    tiktok_id: str | None = None
    confirmed_at: str | None = None
    discount_pct: int | None = None
    fields: list[str] = Field(default_factory=list)


def confirmed_write_out(value: object | None) -> ConfirmedWriteOut | None:
    return ConfirmedWriteOut.model_validate(value) if value is not None else None


def deny(code: str, *, status_code: int = status.HTTP_403_FORBIDDEN) -> HTTPException:
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
    # P64 (D73 Q6 layer 2): before anything else, so even a refused request is marked.
    mark_reviewer_session()
    method = request.method.upper()
    template = endpoint_key(request)
    # D42 amendment (2026-10-15): the pin is optional. Unset, the reviewer has
    # no shop (sample mode in the UI); the allowlist below is unchanged.
    shop_id = reviewer_service.config.reviewer_shop_id()
    # P69b: account, users row and pinned shop -- cached, else ONE load per concurrent
    # burst for this verified sub (single flight), in three statements on Postgres.
    identity = await reviewer_service.identity.load_identity(session, token.user_id, shop_id)
    account = identity.account
    if account is None or account.platform != token.reviewer_platform:
        await session.rollback()
        logger.warning("reviewer_unknown", extra={"user_id": str(token.user_id)})
        raise deny("unknown")
    state = account.status()
    if state != reviewer_service.accounts.STATUS_ACTIVE:
        await session.rollback()
        logger.info("reviewer_denied", extra={"user_id": str(token.user_id), "state": state})
        raise deny(state)
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
        raise deny("read_only")
    if shop_id is None and (method, template) in SANDBOX_ONLY_ENDPOINTS:
        # P64 (D73.4): no pin, no sandbox -- refused (and audited) before any shop lookup.
        await _audit_sandbox_refusal(
            session, account, shop_id=None, method=method, endpoint=template, path=request.url.path
        )
        raise deny("sandbox_only")
    if token.session_id and token.session_id != account.last_session_id:
        if await reviewer_service.accounts.claim_sign_in(session, account, token.session_id):
            await audit.record(
                session,
                account.actor,
                audit.ACTION_REVIEWER_SIGN_IN,
                shop_id=shop_id,
                after={"platform": account.platform, "session_id": token.session_id},
            )
        # The claim (and its audit) are writes: committed here, exactly as before. The
        # committed row now holds this session id, so the next request needs no claim.
        await session.commit()
        reviewer_service.accounts.remember_signed_in(account, token.session_id)
    elif identity.user_values is None:
        # ``load_authenticated_user`` (a first sighting, or no users row read) starts
        # from a clean session, as before P69b.
        await session.commit()
    # P69b: otherwise nothing was written and nothing is committed. The identity load
    # restored the role in its own statement; the route's shop entry sets the shop's
    # tenant scope next, as on every warm request.
    if identity.user_values is not None:
        setattr(request.state, REVIEWER_USER_STATE_KEY, identity.user_values)
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
            alias_id=(
                reviewer_service.config.shop_alias_id(shop_id) if shop_id is not None else None
            ),
            sandbox_only=(method, template) in SANDBOX_ONLY_ENDPOINTS,
            method=method,
            endpoint=template,
            pinned=identity.pinned,
        ),
    )


async def enter_reviewer_shop(
    session: AsyncSession, context: ReviewerContext, x_shop_id: str | None
) -> Shop:
    """The pinned shop, in its read scope; ``X-Shop-Id`` must be the alias (None: skip check)."""
    if context.shop_id is None:
        raise deny("shop")
    sent = x_shop_id.strip().lower() if x_shop_id is not None else None
    # P64 (D73): unmasked, the sandbox shop is shown under its real id, so that id is
    # accepted too -- but only once the shop is known to be the sandbox (checked below).
    if sent is not None and sent not in (str(context.alias_id), str(context.shop_id)):
        logger.warning("reviewer_shop_refused", extra={"platform": context.platform})
        raise deny("shop")
    shop = context.shop
    if shop is None:
        shop = await _enter_pinned_shop(session, context, context.shop_id)
    if sent == str(context.shop_id) and sent != str(context.alias_id) and context.mask_enabled:
        logger.warning("reviewer_shop_refused", extra={"platform": context.platform})
        raise deny("shop")
    if context.sandbox_only and not _sandbox_writable(context):
        # P64 (D73.4): a seller run route on a pin that is not Juli's writable sandbox.
        logger.warning(
            "reviewer_sandbox_route_refused",
            extra={
                "platform": context.platform,
                "reason": context.pin.writes_disabled_reason if context.pin else None,
            },
        )
        await _audit_sandbox_refusal(
            session,
            context.account,
            shop_id=context.shop_id,
            method=context.method,
            endpoint=context.endpoint,
            path=None,
        )
        raise deny("sandbox_only")
    return shop


async def _enter_pinned_shop(
    session: AsyncSession, context: ReviewerContext, shop_id: uuid.UUID
) -> Shop:
    """Enter the pinned shop's tenant scope and learn what the pin is (P69: cached facts).

    P69b: the gate's identity load normally hands the pinned facts over
    (``context.pinned``: read in the fused identity statement or cached). A pin-cache
    hit (``services/reviewer/pin_cache``, the reviewer identity TTL) skips
    the ops read and the pin classification -- seven round trips -- but STILL applies the
    shop's tenant scope (one ``set_config`` statement) to this request's transaction, so
    RLS narrows every query exactly as on a miss.
    """
    pinned = context.pinned
    if pinned is None or pinned.shop_id != shop_id:
        pinned = reviewer_service.pin_cache.cached(shop_id)
    if pinned is not None:
        shop = pinned.shop()
        await _apply_tenant_context_to_session(session, shop.id, shop.user_id)
        pin = pinned.pin
    else:
        found = await reviewer_service.enter_shop_read_scope(session, shop_id)
        if found is None:
            logger.error("reviewer_shop_missing")
            raise deny("unconfigured", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
        shop = found
        pin = await reviewer_service.sandbox.classify_pin(session, shop.id)
        reviewer_service.pin_cache.remember(shop, pin)
    set_tenant_context(shop.id, shop.user_id)
    context.pin = pin
    if pin.mask:
        # The identity mask's dictionary (cached per shop); Juli's own sandbox shop is
        # shown unmasked (D73 Q1/Q2), so it needs none.
        context.dictionary = await reviewer_service.catalog.load_dictionary(session, shop)
    context.shop = shop
    return shop


async def _audit_sandbox_refusal(
    session: AsyncSession,
    account: ReviewerAccount,
    *,
    shop_id: uuid.UUID | None,
    method: str,
    endpoint: str | None,
    path: str | None,
) -> None:
    """A refused sandbox-only run route, audited like any refused reviewer request."""
    action = (
        audit.ACTION_REVIEWER_READ_REFUSED
        if method in (_GET, "HEAD", "OPTIONS")
        else audit.ACTION_REVIEWER_WRITE_REFUSED
    )
    after: dict[str, Any] = {
        "platform": account.platform,
        "method": method,
        "endpoint": endpoint,
        "reason": "sandbox_only",
    }
    if path is not None:
        after["path"] = path
    await audit.record(session, account.actor, action, shop_id=shop_id, after=after)
    await session.commit()


def _sandbox_writable(context: ReviewerContext) -> bool:
    return context.pin is not None and context.pin.sandbox and context.pin.writes_enabled


async def require_sandbox_pin(
    session: AsyncSession, context: ReviewerContext | None, x_shop_id: str | None
) -> Shop:
    """The pinned shop, only when it is a writable sandbox shop (D73 Q6 layer 1); else 403."""
    if context is None:
        # A seller (non-reviewer) session never reaches a reviewer-only route.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reviewer only")
    shop = await enter_reviewer_shop(session, context, x_shop_id)
    if not _sandbox_writable(context):
        logger.warning(
            "reviewer_sandbox_route_refused",
            extra={
                "platform": context.platform,
                "reason": context.pin.writes_disabled_reason if context.pin else None,
            },
        )
        raise deny("sandbox_only")
    return shop


async def audit_reviewer_run_action(
    session: AsyncSession,
    request: Request,
    action: str,
    *,
    shop_id: uuid.UUID,
    after: dict[str, Any],
) -> None:
    """P64 (D73.4): audit a reviewer's run action on a seller route (no-op for a seller).

    No commit: the row joins the route's own transaction.

    P72: the route's own pending writes are flushed FIRST, as the request's role
    (``juli_app``). ``audit.record`` runs in ``ops_role`` (``SET LOCAL ROLE juli_ops``) and
    flushes on the way out; anything still pending then -- the Hoàn tác route's
    ``close_card`` UPDATE -- was sent as ``juli_ops``, which may not write seller tables
    (``permission denied for table action_cards``, production 2026-10-28).
    """
    context = reviewer_context(request)
    if context is None:
        return
    await session.flush()
    await audit.record(
        session,
        context.account.actor,
        action,
        shop_id=shop_id,
        after={"platform": context.platform, **after},
    )


async def reviewer_started_run(session: AsyncSession, request: Request, run: Any) -> bool:
    """P66 / P70: whether a sandbox reviewer may act on ``run`` as its starter.

    Always ``True`` for a seller request. For a reviewer: whether the reviewer approved the
    run's card (the same rule as ``started_by_viewer`` on the runs list,
    ``services/agent_runs/listing._approved_by``) -- a reviewer never reverts the team's own
    verification runs, whatever the UI shows.
    """
    context = reviewer_context(request)
    if context is None:
        return True
    if run.action_card_id is None:
        return False
    found = await session.execute(
        select(ActionCardApproval.id)
        .where(
            ActionCardApproval.action_card_id == run.action_card_id,
            ActionCardApproval.approved_by_user_id == context.account.user_id,
        )
        .limit(1)
    )
    return found.first() is not None


async def audit_reviewer_confirmation(
    session: AsyncSession, request: Request, run: Any, *, tool_call_id: str, decision: str
) -> None:
    """P64 (D73.3/D73.4): a reviewer's run confirmation, audited (no-op for a seller).

    ``reviewer_sandbox_create_product`` for the sandbox ``create_product`` run,
    ``reviewer_sandbox_create_promotion`` for ``create_promotion`` (P65, D74), else
    ``reviewer_sandbox_execute``.
    """
    from juli_backend.services.agent import playbooks

    create = run.workflow_key == playbooks.CREATE_PRODUCT_WORKFLOW_KEY
    promotion = run.workflow_key == playbooks.CREATE_PROMOTION_WORKFLOW_KEY
    action = (
        audit.ACTION_REVIEWER_SANDBOX_CREATE_PRODUCT
        if create
        else audit.ACTION_REVIEWER_SANDBOX_CREATE_PROMOTION
        if promotion
        else audit.ACTION_REVIEWER_SANDBOX_EXECUTE
    )
    after: dict[str, Any] = {
        "run_id": str(run.id),
        "tool_call_id": tool_call_id,
        "decision": decision,
        "workflow_key": run.workflow_key,
    }
    # P64: what the approve will execute -- the seller's edit when there is one.
    state = run.state if isinstance(run.state, dict) else {}
    pending = state.get("pending_confirmation")
    if decision == "approve" and isinstance(pending, dict):
        edited = pending.get("edited_fields")
        if isinstance(edited, list) and edited:
            after["edited_fields"] = list(edited)
        arguments = pending.get("arguments")
        fields = (
            ("title", "description")
            if create
            else ("product_ids", "discount_pct", "end_date", "promotion_title")
            if promotion
            else ()
        )
        if isinstance(arguments, dict):
            for field in fields:
                if arguments.get(field) is not None:
                    after[field] = arguments[field]
    await audit_reviewer_run_action(session, request, action, shop_id=run.shop_id, after=after)


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
                if not context.mask_enabled:
                    # P64 (D73 Q1/Q2): Juli's own sandbox shop is shown as it is -- and
                    # streamed as it is (D73.4: the run's SSE events), never buffered.
                    await send(message)
                    return
                start = message
                return
            if message["type"] == "http.response.body" and start is not None:
                chunks.append(message.get("body", b""))
                if message.get("more_body", False):
                    return
                context = scope["state"][STATE_KEY]
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
    "SANDBOX_ONLY_ENDPOINTS",
    "SANDBOX_RULE_ENDPOINTS",
    "SANDBOX_RUN_ENDPOINTS",
    "audit_reviewer_confirmation",
    "audit_reviewer_run_action",
    "endpoint_key",
    "STATE_KEY",
    "ReviewerContext",
    "deny",
    "require_sandbox_pin",
    "ReviewerMaskMiddleware",
    "enter_reviewer_shop",
    "install",
    "is_allowed",
    "reviewer_context",
    "reviewer_gate",
    "reviewer_started_run",
]
