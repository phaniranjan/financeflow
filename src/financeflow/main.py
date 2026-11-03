import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from financeflow.api.v1.router import api_router
from financeflow.core.config import get_settings

logger = logging.getLogger("financeflow.error_handler")


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


@app.exception_handler(Exception)
def unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Sanitize all uncaught internal errors, preventing stack and credential leakage."""
    correlation_id = str(uuid.uuid4())
    logger.error(
        "Unhandled server exception: %s: %s (correlation_id=%s)",
        type(exc).__name__,
        exc,
        correlation_id,
        exc_info=True,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": (
                "Internal server error. Please contact support with "
                f"correlation ID: {correlation_id}"
            ),
            "correlation_id": correlation_id,
        },
    )


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    """Health check endpoint confirming application readiness."""
    return {"status": "healthy"}
