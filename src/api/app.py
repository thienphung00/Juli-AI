from fastapi import APIRouter, FastAPI

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
    app.include_router(v1_router)

    return app
