from fastapi import APIRouter

from financeflow.api.v1.endpoints.financing import router as financing_router
from financeflow.api.v1.endpoints.invoices import router as invoices_router

api_router = APIRouter()
api_router.include_router(invoices_router)
api_router.include_router(financing_router)
