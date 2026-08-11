from typing import Any

from fastapi import APIRouter, FastAPI

from juli_backend.api.middleware import CorrelationIdMiddleware, install_error_boundary
from juli_backend.api.routes.action_cards import router as action_cards_router
from juli_backend.api.routes.auth_tiktok import router as auth_tiktok_router
from juli_backend.api.routes.auth_tiktok_business_account_holder import (
    router as auth_tiktok_business_account_holder_router,
)
from juli_backend.api.routes.auth_tiktok_business_advertiser import (
    router as auth_tiktok_business_advertiser_router,
)
from juli_backend.api.routes.creators import router as creators_router
from juli_backend.api.routes.debug_tiktok import router as debug_tiktok_router
from juli_backend.api.routes.demo_analytics import router as demo_analytics_router
from juli_backend.api.routes.demo_decisions import router as demo_decisions_router
from juli_backend.api.routes.demo_execution import router as demo_execution_router
from juli_backend.api.routes.executions import router as executions_router
from juli_backend.api.routes.orders import router as orders_router
from juli_backend.api.routes.outcomes import router as outcomes_router
from juli_backend.api.routes.products import router as products_router
from juli_backend.api.routes.recommendations import router as recommendations_router
from juli_backend.api.routes.shops import router as shops_router
from juli_backend.api.routes.webhook_tiktok import router as webhook_tiktok_router
from juli_backend.api.routes.workflow_outcomes import router as workflow_outcomes_router
from juli_backend.core.config import is_production


def create_app(*, lifespan: Any | None = None) -> FastAPI:
    """Build and return the Juli API application."""
    # Interactive docs, the ReDoc view and the raw schema hand any caller who can reach
    # the host a complete map of every route, its parameters and its models. Harmless in
    # development, a free reconnaissance pass in production (ADR-061, #903). Passing
    # None to FastAPI does not merely hide them — the routes are never registered.
    production = is_production()
    app = FastAPI(
        title="Juli API",
        version="0.1.0",
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
        lifespan=lifespan,
    )

    v1_router = APIRouter(prefix="/v1")
    v1_router.include_router(auth_tiktok_router)
    v1_router.include_router(auth_tiktok_business_advertiser_router)
    v1_router.include_router(auth_tiktok_business_account_holder_router)
    v1_router.include_router(shops_router)
    v1_router.include_router(orders_router)
    v1_router.include_router(products_router)
    v1_router.include_router(recommendations_router)
    v1_router.include_router(outcomes_router)
    v1_router.include_router(executions_router)
    v1_router.include_router(action_cards_router)
    v1_router.include_router(workflow_outcomes_router)
    v1_router.include_router(creators_router)
    v1_router.include_router(demo_analytics_router)
    v1_router.include_router(demo_decisions_router)
    v1_router.include_router(demo_execution_router)
    app.include_router(v1_router)
    # The diagnostic router is not mounted in production at all. Its own
    # ENABLE_TIKTOK_DEBUG flag is deliberately NOT consulted here: the environment check
    # takes precedence, so an operator who leaves the flag on cannot expose it (#903 AC).
    # Not-mounted beats mounted-and-404ing — an unregistered route cannot be reached by a
    # future refactor that forgets the guard.
    if not production:
        app.include_router(debug_tiktok_router)
    # Not under /v1 — TikTok Partner Center calls the literal path it was
    # registered with (see juli_backend.services.webhook.app.WEBHOOK_PATH).
    app.include_router(webhook_tiktok_router)

    # Correlation must wrap everything, so it is added last (Starlette applies middleware
    # outermost-last) and therefore sees the request before any route or handler runs.
    app.add_middleware(CorrelationIdMiddleware)
    install_error_boundary(app)

    return app
