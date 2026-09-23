from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes import approvals, audit, auth, cost_library, drawings, prequal, projects, taxonomy, vendors

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
