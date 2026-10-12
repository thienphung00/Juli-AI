"""The ingest gateway and Juli Connector pairing (fast track P24, D31.3 / D31.4).

Two kinds of caller:

- the SELLER, signed in on demo.app-juli.com (Supabase JWT + ``X-Shop-Id``):
  ``POST /v1/ingest/pairing-codes``, ``GET /v1/ingest/tokens``,
  ``DELETE /v1/ingest/tokens/{token_id}``;
- the EXTENSION (or another source) holding an ingest token
  (``Authorization: Bearer jci_...``): ``POST /v1/ingest/pair`` (no token yet:
  the pairing code), ``POST /v1/ingest/token/rotate``, ``GET`` / ``POST
  /v1/ingest/status`` and ``POST /v1/ingest/{platform}/{dataset}``.

An ingest token is accepted by these routes only; it is not a Supabase JWT, so
every other route refuses it. Errors carry a stable ``code`` for the client.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.dependencies import get_active_shop
from juli_backend.core.security import get_current_user
from juli_backend.database import Shop, User, get_session
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.repositories import utc_now_naive
from juli_backend.services import ingest as ingest_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])

_PLATFORMS = ("shopee", "tiktok")


def _error(status_code: int, code: str, **more: Any) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, **more})


async def _rate_limited(key: str, limit: tuple[int, int]) -> None:
    decision = await ingest_service.get_ingest_rate_gate().hit(key, limit[0], limit[1])
    if not decision.allowed:
        logger.info("ingest_rate_limited", extra={"key": key})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "rate_limited", "retry_after_seconds": decision.retry_after_seconds},
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )


async def get_ingest_principal(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> ingest_service.IngestPrincipal:
    """The live ingest token in ``Authorization: Bearer``, or 401."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _error(status.HTTP_401_UNAUTHORIZED, "missing_token")
    principal = await ingest_service.resolve_token(session, token.strip(), utc_now_naive())
    if principal is None:
        await session.rollback()
        raise _error(status.HTTP_401_UNAUTHORIZED, "invalid_token")
    await _rate_limited(f"shop:{principal.shop_id}", ingest_service.shop_limit())
    return principal


async def _json_body(request: Request) -> Any:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > ingest_service.MAX_BODY_BYTES:
        raise _error(status.HTTP_413_CONTENT_TOO_LARGE, "body_too_large")
    raw = await request.body()
    if len(raw) > ingest_service.MAX_BODY_BYTES:
        raise _error(status.HTTP_413_CONTENT_TOO_LARGE, "body_too_large")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise _error(status.HTTP_400_BAD_REQUEST, "invalid_json") from None


def _validation_error(exc: ValidationError) -> HTTPException:
    errors = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors(include_url=False, include_input=False)[:20]
    ]
    return _error(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_body", errors=errors)


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    host = forwarded or (request.client.host if request.client else "unknown")
    return host[:64]


def _token_json(issued: ingest_service.IssuedToken) -> dict[str, Any]:
    return {
        "token": issued.token,
        "token_id": str(issued.token_id),
        "shop_id": str(issued.shop_id),
        "platform": issued.platform,
        "expires_at": issued.expires_at.isoformat() + "Z",
        "rotate_after": issued.rotate_after.isoformat() + "Z",
    }


# -- seller (Supabase JWT + X-Shop-Id) ---------------------------------------------------


@router.post("/pairing-codes", status_code=status.HTTP_201_CREATED)
async def create_pairing_code(
    user: User = Depends(get_current_user),
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """A 10-minute, single-use code the seller types into the Juli Connector."""
    try:
        issued = await ingest_service.create_pairing_code(
            session, shop=shop, user_id=user.id, now=utc_now_naive()
        )
    except ingest_service.PairingError as exc:
        await session.rollback()
        raise _error(exc.status, exc.code) from None
    await session.commit()
    return {
        "code": issued.code,
        "expires_at": issued.expires_at.isoformat() + "Z",
        "ttl_seconds": int(ingest_service.PAIRING_CODE_TTL.total_seconds()),
    }


@router.get("/tokens")
async def list_ingest_tokens(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """The shop's connector tokens (never the token or its hash)."""
    tokens = await ingest_service.list_tokens(session, shop.id)
    now = utc_now_naive()
    return {
        "data": [
            {
                "id": str(t.id),
                "platform": t.platform,
                "client_label": t.client_label,
                "created_at": t.created_at.isoformat() + "Z",
                "expires_at": t.expires_at.isoformat() + "Z",
                "last_used_at": t.last_used_at.isoformat() + "Z" if t.last_used_at else None,
                "revoked_at": t.revoked_at.isoformat() + "Z" if t.revoked_at else None,
                "superseded_at": t.superseded_at.isoformat() + "Z" if t.superseded_at else None,
                "active": t.revoked_at is None
                and t.expires_at > now
                and (
                    t.superseded_at is None or now < t.superseded_at + ingest_service.ROTATION_GRACE
                ),
            }
            for t in tokens
        ]
    }


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_ingest_token(
    token_id: uuid.UUID,
    user: User = Depends(get_current_user),
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """The seller disconnects a browser: the token (and its rotations) stop at once."""
    shop_id, user_id = shop.id, user.id
    found = await ingest_service.revoke_token(
        session, shop_id=shop_id, token_id=token_id, reason="seller", now=utc_now_naive()
    )
    if not found:
        await session.rollback()
        raise _error(status.HTTP_404_NOT_FOUND, "token_not_found")
    await session.commit()
    logger.info(
        "ingest_token_revoked_by_seller",
        extra={"shop_id": str(shop_id), "user_id": str(user_id), "token_id": str(token_id)},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- extension ------------------------------------------------------------------------


@router.post("/pair")
async def pair(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Exchange a pairing code for an ingest token (no Juli session involved)."""
    await _rate_limited(f"pair:{_client_key(request)}", ingest_service.pair_limit())
    limit, window = ingest_service.pair_limit()
    await _rate_limited("pair:all", (limit * 30, window))
    try:
        body = ingest_service.PairRequest.model_validate(await _json_body(request))
    except ValidationError as exc:
        raise _validation_error(exc) from None
    try:
        issued = await ingest_service.redeem_pairing_code(
            session,
            code=body.code,
            platform=body.platform,
            platform_shop_id=body.platform_shop_id,
            client_label=body.client_label,
            now=utc_now_naive(),
        )
    except ingest_service.PairingError as exc:
        await session.rollback()
        raise _error(exc.status, exc.code) from None
    await session.commit()
    return _token_json(issued)


@router.post("/token/rotate")
async def rotate(
    principal: ingest_service.IngestPrincipal = Depends(get_ingest_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        issued = await ingest_service.rotate_token(session, principal, now=utc_now_naive())
    except ingest_service.PairingError as exc:
        await session.rollback()
        raise _error(exc.status, exc.code) from None
    await session.commit()
    return _token_json(issued)


@router.get("/status")
async def get_status(
    principal: ingest_service.IngestPrincipal = Depends(get_ingest_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """For the extension popup: last ingest and drift per dataset, token expiry."""
    async with with_shop_scope(session, principal.shop_id):
        datasets = await ingest_service.dataset_status(
            session, shop_id=principal.shop_id, platform=principal.platform
        )
    await session.commit()
    return {
        "shop_id": str(principal.shop_id),
        "platform": principal.platform,
        "token": {
            "expires_at": principal.expires_at.isoformat() + "Z",
            "rotate_after": principal.rotate_after.isoformat() + "Z",
        },
        "datasets": datasets,
    }


@router.post("/status")
async def post_status(
    request: Request,
    principal: ingest_service.IngestPrincipal = Depends(get_ingest_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """The extension reports schema drift (or its end) for one dataset."""
    try:
        report = ingest_service.DriftReport.model_validate(await _json_body(request))
    except ValidationError as exc:
        raise _validation_error(exc) from None
    if report.platform != principal.platform:
        raise _error(status.HTTP_403_FORBIDDEN, "platform_not_allowed")
    try:
        async with with_shop_scope(session, principal.shop_id):
            await ingest_service.report_drift(
                session, shop_id=principal.shop_id, report=report, now=utc_now_naive()
            )
    except LookupError:
        await session.rollback()
        raise _error(status.HTTP_404_NOT_FOUND, "unknown_dataset") from None
    await session.commit()
    return {"dataset": report.dataset, "drift": report.state}


@router.post("/{platform}/{dataset}")
async def post_dataset(
    platform: str,
    dataset: str,
    request: Request,
    principal: ingest_service.IngestPrincipal = Depends(get_ingest_principal),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """One dataset for the token's shop: raw kept, normalized days upserted."""
    if platform not in _PLATFORMS:
        raise _error(status.HTTP_404_NOT_FOUND, "unknown_platform")
    if platform != principal.platform:
        raise _error(status.HTTP_403_FORBIDDEN, "platform_not_allowed")
    if ingest_service.dataset_spec(platform, dataset) is None:
        raise _error(status.HTTP_404_NOT_FOUND, "unknown_dataset")
    try:
        body = ingest_service.IngestBody.model_validate(await _json_body(request))
    except ValidationError as exc:
        raise _validation_error(exc) from None
    if (
        principal.platform_shop_id
        and body.platform_shop_id
        and principal.platform_shop_id != body.platform_shop_id
    ):
        logger.warning(
            "ingest_shop_mismatch",
            extra={"shop_id": str(principal.shop_id), "token_id": str(principal.token_id)},
        )
        raise _error(status.HTTP_409_CONFLICT, "shop_mismatch")
    try:
        async with with_shop_scope(session, principal.shop_id):
            result = await ingest_service.ingest(
                session,
                shop_id=principal.shop_id,
                platform=platform,
                dataset=dataset,
                body=body,
                token_id=principal.token_id,
                now=utc_now_naive(),
            )
    except ingest_service.IngestRejected as exc:
        await session.rollback()
        logger.info(
            "ingest_rejected",
            extra={
                "shop_id": str(principal.shop_id),
                "platform": platform,
                "dataset": dataset,
                "code": exc.code,
                "errors": len(exc.errors),
            },
        )
        raise _error(exc.status, exc.code, errors=exc.errors) from None
    await session.commit()
    return result.to_json()
