from fastapi import APIRouter, FastAPI

from src.api.routers.analytics import router as analytics_router
from src.api.routers.creators import router as creators_router
from src.api.routers.inventory import router as inventory_router
from src.api.routers.livestreams import router as livestreams_router
from src.api.routers.orders import router as orders_router
from src.api.routers.products import router as products_router
from src.api.routers.settlements import router as settlements_router
from src.api.routers.shops import router as shops_router


def create_app() -> FastAPI:
    """Build and return the Juli API application."""
    app = FastAPI(
        title="Juli API",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    v1_router = APIRouter(prefix="/v1")
    v1_router.include_router(shops_router)
    v1_router.include_router(orders_router)
    v1_router.include_router(products_router)
    v1_router.include_router(inventory_router)
    v1_router.include_router(analytics_router)
    v1_router.include_router(livestreams_router)
    v1_router.include_router(creators_router)
    v1_router.include_router(settlements_router)
    app.include_router(v1_router)

    return app
