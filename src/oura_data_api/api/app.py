"""FastAPI application factory with safe configuration-independent liveness."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import RequestResponseEndpoint
from starlette.types import Lifespan

from .cursors import CursorCodec
from .dependencies import APIService
from .errors import install_exception_handlers
from .routes import build_protected_router, build_public_router


def _cursor_secret(gateway_token: str | None, configured_secret: bytes | None) -> bytes:
    if configured_secret is not None:
        return configured_secret
    if gateway_token is not None:
        return hashlib.sha256(f"oura-data-api:cursor:{gateway_token}".encode("utf-8")).digest()
    return secrets.token_bytes(32)


def create_app(
    settings: object | None = None,
    *,
    service: APIService | None = None,
    service_factory: Callable[[object], APIService] | None = None,
    gateway_token: str | None = None,
    cursor_secret: bytes | None = None,
    lifespan: Lifespan[FastAPI] | None = None,
) -> FastAPI:
    """Create an app without loading files or process environment variables.

    Settings are injected by the composition root. Passing no settings remains
    valid so the liveness route can start even when configuration loading fails.
    """

    if service is not None and service_factory is not None:
        raise ValueError("pass service or service_factory, not both")
    if service is None and service_factory is not None and settings is not None:
        service = service_factory(settings)
    if gateway_token is None and settings is not None:
        candidate = getattr(settings, "gateway_token", None)
        if isinstance(candidate, str):
            gateway_token = candidate
    docs_enabled = bool(getattr(settings, "public_docs_enabled", True))

    @asynccontextmanager
    async def empty_lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield

    app = FastAPI(
        title="Oura Data API",
        version="1.0.0",
        description="Read-only JSON access to Oura data and deterministic recovery analytics.",
        lifespan=lifespan or empty_lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.api_service = service
    app.state.settings = settings
    app.state.gateway_token = gateway_token
    app.state.cursor_codec = CursorCodec(_cursor_secret(gateway_token, cursor_secret))

    install_exception_handlers(app)

    @app.middleware("http")
    async def request_context(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.request_id = uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return response

    app.include_router(build_public_router())
    app.include_router(build_protected_router())
    return app
