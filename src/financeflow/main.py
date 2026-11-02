from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from financeflow.api.v1.router import api_router
from financeflow.core.config import get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    yield


settings = get_settings()

app = FastAPI(
    title="FinanceFlow API",
    description="Simulated financial invoice financing and reconciliation platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    """Health check endpoint confirming application readiness."""
    return {"status": "healthy"}
