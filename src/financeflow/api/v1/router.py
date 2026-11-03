from fastapi import APIRouter

from financeflow.api.v1.endpoints.disbursements import router as disbursements_router
from financeflow.api.v1.endpoints.financing import router as financing_router
from financeflow.api.v1.endpoints.invoices import router as invoices_router
from financeflow.api.v1.endpoints.ledger import router as ledger_router
from financeflow.api.v1.endpoints.settlements import router as settlements_router

api_router = APIRouter()
api_router.include_router(invoices_router)
api_router.include_router(financing_router)
api_router.include_router(disbursements_router)
api_router.include_router(ledger_router)
api_router.include_router(settlements_router)
