from fastapi import APIRouter

from financeflow.api.v1.endpoints.invoices import router as invoices_router

api_router = APIRouter()
api_router.include_router(invoices_router)
