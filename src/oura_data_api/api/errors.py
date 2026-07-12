"""Sanitized RFC 9457-compatible problem responses."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from oura_data_api.errors import (
    ApiError,
    AuthenticationError,
    ConfigurationError,
    ConfigurationFileMissingError,
    FixtureError,
    TokenStoreError,
)

from .models import ProblemDetails

PROBLEM_BASE = "https://github.com/whuang214/oura-data-api/problems"


@dataclass(slots=True)
class APIProblem(Exception):
    status: int
    code: str
    title: str
    detail: str
    retryable: bool = False
    retry_after_seconds: int | None = None
    type_uri: str | None = None


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


def _response(request: Request, problem: APIProblem) -> JSONResponse:
    payload = ProblemDetails(
        type=problem.type_uri or f"{PROBLEM_BASE}/{problem.code.replace('_', '-')}",
        title=problem.title,
        status=problem.status,
        detail=problem.detail,
        instance=request.url.path,
        code=problem.code,
        request_id=_request_id(request),
        retryable=problem.retryable,
        retry_after_seconds=problem.retry_after_seconds,
    )
    headers: dict[str, str] = {}
    if problem.status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if problem.retry_after_seconds is not None:
        headers["Retry-After"] = str(problem.retry_after_seconds)
    return JSONResponse(
        status_code=problem.status,
        content=payload.model_dump(mode="json"),
        media_type="application/problem+json",
        headers=headers,
    )


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIProblem)
    async def api_problem_handler(request: Request, exc: APIProblem) -> JSONResponse:
        return _response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, _exc: RequestValidationError) -> JSONResponse:
        return _response(
            request,
            APIProblem(
                status=400,
                code="request_validation_failed",
                title="Request validation failed",
                detail="One or more request parameters are invalid.",
            ),
        )

    @app.exception_handler(ConfigurationFileMissingError)
    async def missing_configuration_handler(request: Request, _exc: ConfigurationFileMissingError) -> JSONResponse:
        return _response(
            request,
            APIProblem(503, "configuration_unavailable", "Configuration unavailable", "The service is not configured."),
        )

    @app.exception_handler(ConfigurationError)
    async def configuration_handler(request: Request, exc: ConfigurationError) -> JSONResponse:
        message = str(exc).casefold()
        connection_related = any(word in message for word in ("connect", "authoriz", "token", "credential"))
        if connection_related:
            problem = APIProblem(
                409,
                "oura_not_connected",
                "Oura is not connected",
                "Connect or reauthorize Oura before requesting this resource.",
            )
        else:
            problem = APIProblem(
                503,
                "configuration_unavailable",
                "Configuration unavailable",
                "The service is not configured for this operation.",
            )
        return _response(request, problem)

    @app.exception_handler(AuthenticationError)
    async def authentication_handler(request: Request, _exc: AuthenticationError) -> JSONResponse:
        return _response(
            request,
            APIProblem(
                409,
                "oura_not_connected",
                "Oura is not connected",
                "Connect or reauthorize Oura before requesting this resource.",
            ),
        )

    @app.exception_handler(ApiError)
    async def provider_api_handler(request: Request, exc: ApiError) -> JSONResponse:
        status = exc.status_code
        if status == 400:
            problem = APIProblem(
                400,
                "invalid_request",
                "Invalid request",
                "The request could not be applied to this resource.",
            )
        elif status == 401:
            problem = APIProblem(
                409,
                "oura_reauthorization_required",
                "Oura reauthorization required",
                "Reconnect Oura before requesting this resource.",
            )
        elif status == 403:
            problem = APIProblem(
                403,
                "provider_forbidden",
                "Oura capability unavailable",
                "The Oura connection cannot access this resource.",
            )
        elif status == 404:
            problem = APIProblem(404, "resource_not_found", "Resource not found", "The requested resource does not exist.")
        elif status == 429:
            problem = APIProblem(
                429,
                "provider_rate_limited",
                "Oura request rate limited",
                "Oura temporarily rate limited this request.",
                retryable=True,
            )
        elif status == 504:
            problem = APIProblem(
                504,
                "provider_timeout",
                "Oura request timed out",
                "Oura did not respond within the allowed time.",
                retryable=True,
            )
        elif status == 503:
            problem = APIProblem(
                503,
                "provider_unavailable",
                "Oura temporarily unavailable",
                "Oura is temporarily unavailable.",
                retryable=True,
            )
        else:
            problem = APIProblem(
                502,
                "provider_unavailable",
                "Oura response unavailable",
                "A usable Oura response was not available.",
                retryable=status is None or status >= 500,
            )
        return _response(request, problem)

    @app.exception_handler(FixtureError)
    async def fixture_handler(request: Request, _exc: FixtureError) -> JSONResponse:
        return _response(
            request,
            APIProblem(502, "fixture_unavailable", "Fixture unavailable", "A usable fixture response was not available."),
        )

    @app.exception_handler(TokenStoreError)
    async def token_store_handler(request: Request, _exc: TokenStoreError) -> JSONResponse:
        return _response(
            request,
            APIProblem(
                503,
                "token_store_unavailable",
                "Token store unavailable",
                "The secure token store is unavailable.",
                retryable=True,
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 404:
            problem = APIProblem(404, "not_found", "Resource not found", "The requested resource does not exist.")
        elif exc.status_code == 405:
            problem = APIProblem(405, "method_not_allowed", "Method not allowed", "The method is not allowed here.")
        else:
            problem = APIProblem(exc.status_code, "http_error", "HTTP request failed", "The request could not be completed.")
        return _response(request, problem)

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, _exc: Exception) -> JSONResponse:
        return _response(
            request,
            APIProblem(
                status=500,
                code="internal_error",
                title="Internal server error",
                detail="The request failed unexpectedly. Use the request ID when reporting this problem.",
            ),
        )
