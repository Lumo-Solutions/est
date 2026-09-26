from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes import (
    approvals,
    audit,
    auth,
    boq,
    cost_library,
    drawings,
    module_e,
    prequal,
    procurement,
    projects,
    quotation_ingestion,
    semantic_matching,
    settlement,
    taxonomy,
    typology,
    vendors,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(vendors.router)
api_router.include_router(taxonomy.router)
api_router.include_router(prequal.router)
api_router.include_router(cost_library.router)
api_router.include_router(approvals.router)
api_router.include_router(audit.router)
api_router.include_router(projects.router)
api_router.include_router(drawings.router)
api_router.include_router(boq.router)
api_router.include_router(module_e.router)
api_router.include_router(procurement.router)
api_router.include_router(quotation_ingestion.router)
api_router.include_router(semantic_matching.router)
api_router.include_router(settlement.router)
api_router.include_router(typology.router)
