from typing import Any

from fastapi import APIRouter, FastAPI

from juli_backend.api.routes.action_cards import router as action_cards_router
from juli_backend.api.routes.auth_tiktok import router as auth_tiktok_router
from juli_backend.api.routes.auth_tiktok_business_advertiser import (
    router as auth_tiktok_business_advertiser_router,
)
from juli_backend.api.routes.creators import router as creators_router
from juli_backend.api.routes.debug_tiktok import router as debug_tiktok_router
from juli_backend.api.routes.executions import router as executions_router
from juli_backend.api.routes.orders import router as orders_router
from juli_backend.api.routes.outcomes import router as outcomes_router
from juli_backend.api.routes.products import router as products_router
from juli_backend.api.routes.recommendations import router as recommendations_router
from juli_backend.api.routes.shops import router as shops_router
from juli_backend.api.routes.webhook_tiktok import router as webhook_tiktok_router
from juli_backend.api.routes.workflow_outcomes import router as workflow_outcomes_router


def create_app(*, lifespan: Any | None = None) -> FastAPI:
    """Build and return the Juli API application."""
    app = FastAPI(
        title="Juli API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    v1_router = APIRouter(prefix="/v1")
    v1_router.include_router(auth_tiktok_router)
    v1_router.include_router(auth_tiktok_business_advertiser_router)
    v1_router.include_router(shops_router)
    v1_router.include_router(orders_router)
    v1_router.include_router(products_router)
    v1_router.include_router(recommendations_router)
    v1_router.include_router(outcomes_router)
    v1_router.include_router(executions_router)
    v1_router.include_router(action_cards_router)
    v1_router.include_router(workflow_outcomes_router)
    v1_router.include_router(creators_router)
    app.include_router(v1_router)
    app.include_router(debug_tiktok_router)
    # Not under /v1 — TikTok Partner Center calls the literal path it was
    # registered with (see juli_backend.services.webhook.app.WEBHOOK_PATH).
    app.include_router(webhook_tiktok_router)

    return app
