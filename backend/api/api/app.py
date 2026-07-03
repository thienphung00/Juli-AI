from typing import Any

from fastapi import APIRouter, FastAPI

from backend.api.api.routers.auth_tiktok import router as auth_tiktok_router
from backend.api.api.routers.alerts import router as alerts_router
from backend.api.api.routers.analytics import router as analytics_router
from backend.api.api.routers.creators import router as creators_router
from backend.api.api.routers.inventory import router as inventory_router
from backend.api.api.routers.livestreams import router as livestreams_router
from backend.api.api.routers.orders import router as orders_router
from backend.api.api.routers.outcomes import router as outcomes_router
from backend.api.api.routers.products import router as products_router
from backend.api.api.routers.recommendations import router as recommendations_router
from backend.api.api.routers.settlements import router as settlements_router
from backend.api.api.routers.shops import router as shops_router


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
    v1_router.include_router(shops_router)
    v1_router.include_router(orders_router)
    v1_router.include_router(products_router)
    v1_router.include_router(inventory_router)
    v1_router.include_router(analytics_router)
    v1_router.include_router(alerts_router)
    v1_router.include_router(recommendations_router)
    v1_router.include_router(outcomes_router)
    v1_router.include_router(livestreams_router)
    v1_router.include_router(creators_router)
    v1_router.include_router(settlements_router)
    app.include_router(v1_router)

    return app
