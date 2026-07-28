"""TikTok Shop webhook ingress — mounted on the main API (Issue #381).

TikTok Partner Center is configured to push webhook deliveries to
``https://api.app-juli.com/webhooks/tiktok``. Nginx already proxies every path
under ``api.app-juli.com`` to the ``juli-api`` process (see
``infra/nginx/api.app-juli.com.conf``); there is no separate webhook systemd
service deployed. Registering the route here — instead of only on the
standalone app in ``juli_backend.services.webhook`` — is what makes that
already-proxied path resolve instead of 404.

HTTP wiring delegates to ``juli_backend.services.webhook.handle_tiktok_webhook_delivery``.
TikTok credentials are resolved lazily per-request via ``require_env``, matching
the sibling TikTok auth route modules.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config.runtime import require_env
from juli_backend.database import get_session
from juli_backend.services.webhook import WEBHOOK_PATH, handle_tiktok_webhook_delivery

router = APIRouter(tags=["webhooks"])


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

    result = await handle_tiktok_webhook_delivery(
        session=session,
        app_key=app_key,
        app_secret=app_secret,
        body=body,
        signature=signature,
        headers=dict(request.headers),
    )

    return JSONResponse(result.body, status_code=result.status_code)
