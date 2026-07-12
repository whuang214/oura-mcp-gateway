"""Service seam and authentication dependencies for the HTTP layer."""

from __future__ import annotations

import hashlib
import hmac
import inspect
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping, Protocol, Sequence, cast

from fastapi import Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .errors import APIProblem
from .models import WarningItem


@dataclass(frozen=True, slots=True)
class ServiceQuery:
    """Validated public query plus a decoded private continuation."""

    parameters: Mapping[str, Any]
    continuation: Any = None


@dataclass(frozen=True, slots=True)
class ServiceResult:
    """Presentation-neutral result returned by the application service."""

    data: Any
    warnings: Sequence[WarningItem | Mapping[str, Any]] = field(default_factory=tuple)
    continuation: Any = None
    retrieved_at: datetime | None = None
    fetched_at: datetime | None = None
    freshness_source: Literal["live", "cache"] = "live"
    stale: bool = False


class APIService(Protocol):
    def collection(self, resource: str, query: ServiceQuery) -> ServiceResult | Any: ...

    def document(self, resource: str, source_id: str) -> ServiceResult | Any: ...

    def singleton(self, resource: str) -> ServiceResult | Any: ...

    def samples(self, resource: str, source_id: str, sample: str, query: ServiceQuery) -> ServiceResult | Any: ...

    def composite_days(self, query: ServiceQuery) -> ServiceResult | Any: ...

    def composite_day(self, day: str, include: Sequence[str]) -> ServiceResult | Any: ...

    def daily_signals(self, query: ServiceQuery) -> ServiceResult | Any: ...

    def daily_coverage(self, query: ServiceQuery) -> ServiceResult | Any: ...

    def daily_signal(self, day: str) -> ServiceResult | Any: ...

    def weekly_trends(self, query: ServiceQuery) -> ServiceResult | Any: ...

    def status(self) -> ServiceResult | Any: ...

    def capabilities(self) -> ServiceResult | Any: ...

    def create_authorization(self) -> ServiceResult | Any: ...

    def oauth_callback(self, parameters: Mapping[str, Any]) -> ServiceResult | Any: ...

    def connection(self) -> ServiceResult | Any: ...

    def delete_connection(self) -> ServiceResult | Any: ...


bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="GatewayBearer",
    bearerFormat="opaque",
    description="Local API gateway token. This is not an Oura OAuth token.",
)


def _constant_time_equal(provided: str, expected: str) -> bool:
    provided_digest = hashlib.sha256(provided.encode("utf-8")).digest()
    expected_digest = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(provided_digest, expected_digest)


async def require_gateway_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> None:
    expected = cast(str | None, getattr(request.app.state, "gateway_token", None))
    valid = (
        expected is not None
        and credentials is not None
        and credentials.scheme.casefold() == "bearer"
        and _constant_time_equal(credentials.credentials, expected)
    )
    if not valid:
        raise APIProblem(
            status=401,
            code="invalid_gateway_token",
            title="Gateway authentication required",
            detail="Provide a valid gateway bearer token.",
        )


def get_service(request: Request) -> APIService:
    service = cast(APIService | None, getattr(request.app.state, "api_service", None))
    if service is None:
        raise APIProblem(
            status=503,
            code="service_unavailable",
            title="Service unavailable",
            detail="The API service is not available.",
            retryable=True,
        )
    return service


async def invoke(method: Any, *args: Any, **kwargs: Any) -> ServiceResult:
    """Support synchronous and asynchronous service implementations."""

    value = method(*args, **kwargs)
    if inspect.isawaitable(value):
        value = await value
    if isinstance(value, ServiceResult):
        return value
    return ServiceResult(data=value)
