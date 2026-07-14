"""TikTok Shop webhook ingress — mounted on the main API (Issue #381).

TikTok Partner Center is configured to push webhook deliveries to
``https://api.app-juli.com/webhooks/tiktok``. Nginx already proxies every path
under ``api.app-juli.com`` to the ``juli-api`` process (see
``infra/nginx/api.app-juli.com.conf``); there is no separate webhook systemd
service deployed. Registering the route here — instead of only on the
standalone app in ``juli_backend.services.webhook`` — is what makes that
already-proxied path resolve instead of 404.

Reuses the verified signature/dispatch assembly from
``juli_backend.services.webhook.app.build_webhook_service`` and the
request-scoped DB session used by every other API route (``get_session``),
rather than the standalone app's injected ``session_factory``. TikTok
credentials are resolved lazily per-request via ``require_env``, matching
``get_tiktok_oauth_service`` / ``get_verify_connection_service`` in the
sibling route modules.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config.runtime import require_env
from juli_backend.database import get_session
from juli_backend.services.etl.consumer import EtlConsumer
from juli_backend.services.ingestion.handoff import make_etl_handoff
from juli_backend.services.tiktok.webhook_handlers import DatabaseWebhookSideEffects
from juli_backend.services.webhook.app import WEBHOOK_PATH, build_webhook_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])


async def _dlq_handoff(channel: str, shop_key: str, payload: bytes) -> None:
    logger.error(
        "webhook_etl_dlq",
        extra={"channel": channel, "shop_key": shop_key, "payload_bytes": len(payload)},
    )


def _resolve_tiktok_credentials() -> tuple[str, str]:
    try:
        app_key = require_env("TIKTOK_APP_KEY")
        app_secret = require_env("TIKTOK_APP_SECRET")
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TikTok webhook receiver is not configured",
        ) from exc
    return app_key, app_secret


@router.post(WEBHOOK_PATH)
async def handle_tiktok_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Receive a TikTok Shop webhook delivery (Partner Center push notification)."""
    app_key, app_secret = _resolve_tiktok_credentials()
    body = await request.body()
    signature = request.headers.get("Authorization")

    consumer = EtlConsumer(session=session, dlq_handoff=_dlq_handoff)
    service = build_webhook_service(
        app_key=app_key,
        app_secret=app_secret,
        handoff_fn=make_etl_handoff(consumer),
        side_effects=DatabaseWebhookSideEffects(session),
    )
    result = await service.handle(body=body, signature=signature)
    await session.commit()

    return JSONResponse(result.body, status_code=result.status_code)
