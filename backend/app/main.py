from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import IntegrityError

import app.models  # noqa: F401 -- populates Base.metadata for anything introspecting it
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import AppError, app_error_handler, integrity_error_handler
from app.core.logging import configure_logging
from app.core.middleware import ClientIpMiddleware, RequestIdMiddleware
from app.security.csrf import CsrfMiddleware
from app.security.middleware import AuthContextMiddleware
from app.security.sessions import SessionStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="INSTALLTEC AI Platform API", version="0.1.0", lifespan=lifespan)

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)

    session_store = SessionStore(settings)
    app.state.session_store = session_store

    # Order matters: Starlette applies middleware in reverse of add order, so
    # the LAST one added here runs FIRST on the way in. We want:
    # RequestId -> ClientIp -> CORS -> Csrf -> AuthContext -> routing
    app.add_middleware(AuthContextMiddleware, settings=settings, store=session_store)
    app.add_middleware(CsrfMiddleware, settings=settings)
    if settings.app_env == "dev":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:3000"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(ClientIpMiddleware, trusted_proxy_hops=settings.trusted_proxy_hops)
    app.add_middleware(RequestIdMiddleware)

    app.include_router(api_router, prefix="/api/v1")

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
