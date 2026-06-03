from fastapi import APIRouter, FastAPI

from src.apps.api_gateway.api.routers.auth import router as auth_router
from src.apps.api_gateway.api.routers.creators import router as creators_router
from src.apps.api_gateway.api.routers.products import router as products_router
from src.apps.api_gateway.api.routers.outcomes import router as outcomes_router
from src.apps.api_gateway.api.routers.recommendations import router as recommendations_router
from src.apps.api_gateway.api.routers.shops import router as shops_router


def create_app() -> FastAPI:
    """Build and return the Juli API application.

    Phase 1 (Creator <-> Shop Matching) surface only: authentication, shops,
    creators, products, and decision-focused recommendations. Seller-OS
    surfaces (orders, inventory, settlements, livestream ops, analytics,
    alerts) were removed during the matching pivot — see
    docs/decisions/006-matching-pivot.md.
    """
    app = FastAPI(
        title="Juli API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    v1_router = APIRouter(prefix="/v1")
    v1_router.include_router(auth_router)
    v1_router.include_router(shops_router)
    v1_router.include_router(creators_router)
    v1_router.include_router(products_router)
    v1_router.include_router(recommendations_router)
    v1_router.include_router(outcomes_router)
    app.include_router(v1_router)

    return app
