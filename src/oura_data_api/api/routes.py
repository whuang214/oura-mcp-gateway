"""Public route inventory and thin adapters to the application-service seam."""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, date, datetime
from enum import Enum
from typing import Annotated, Any, Mapping, cast

from fastapi import APIRouter, Body, Depends, Path, Query, Request, Security

from .cursors import CursorCodec
from .dependencies import (
    APIService,
    ServiceQuery,
    ServiceResult,
    get_service,
    invoke,
    require_gateway_token,
)
from .errors import APIProblem
from .models import (
    CompositeDayQuery,
    CompositeDaysQuery,
    CursorOnlyQuery,
    DateRangeMeta,
    DateRangeQuery,
    DateTimeRangeMeta,
    DateTimeRangeQuery,
    EmptyBody,
    EmptyQuery,
    FreshnessMeta,
    HealthChallengeQuery,
    OAuthCallbackQuery,
    ProblemDetails,
    ResponseMeta,
    SampleQuery,
    SleepPhaseSampleQuery,
    SuccessEnvelope,
    WarningItem,
)

API_PREFIX = "/api/v1"
HEALTH_CHALLENGE_CONTEXT = b"oura-data-api-v1-health:"

STABLE_DATE_RESOURCES: Mapping[str, str] = {
    "/daily/activity": "daily_activity",
    "/daily/readiness": "daily_readiness",
    "/daily/sleep": "daily_sleep",
    "/daily/stress": "daily_stress",
    "/daily/spo2": "daily_spo2",
    "/daily/cardiovascular-age": "daily_cardiovascular_age",
    "/sleep-periods": "sleep_periods",
    "/sleep-times": "sleep_times",
    "/workouts": "workouts",
    "/sessions": "sessions",
    "/enhanced-tags": "enhanced_tags",
    "/rest-mode-periods": "rest_mode_periods",
    "/vo2-max": "vo2_max",
}

CURSOR_ONLY_RESOURCES: Mapping[str, str] = {
    "/rings": "rings",
}

STABLE_TIME_SERIES_RESOURCES: Mapping[str, str] = {
    "/heart-rate": "heart_rate",
    "/ring-battery": "ring_battery",
}

EXPERIMENTAL_DATE_RESOURCES: Mapping[str, str] = {
    "/experimental/daily/resilience": "daily_resilience",
    "/experimental/legacy-tags": "legacy_tags",
}

SAMPLE_RESOURCES: Mapping[str, tuple[str, str]] = {
    "/sleep-periods/{source_id}/samples/heart-rate": ("sleep_periods", "heart_rate"),
    "/sleep-periods/{source_id}/samples/hrv": ("sleep_periods", "hrv"),
    "/sleep-periods/{source_id}/samples/movement": ("sleep_periods", "movement"),
    "/sessions/{source_id}/samples/heart-rate": ("sessions", "heart_rate"),
    "/sessions/{source_id}/samples/hrv": ("sessions", "hrv"),
    "/sessions/{source_id}/samples/motion": ("sessions", "motion"),
    "/daily/activity/{source_id}/samples/met": ("daily_activity", "met"),
    "/daily/activity/{source_id}/samples/classification": ("daily_activity", "classification"),
}

PROVIDER_RESOURCE_KEYS = frozenset(
    {
        *STABLE_DATE_RESOURCES.values(),
        *CURSOR_ONLY_RESOURCES.values(),
        *STABLE_TIME_SERIES_RESOURCES.values(),
        *EXPERIMENTAL_DATE_RESOURCES.values(),
        *(resource for resource, _sample in SAMPLE_RESOURCES.values()),
        "profile",
    }
)

PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {
        "model": ProblemDetails,
        "description": description,
        "content": {"application/problem+json": {}},
    }
    for status, description in {
        401: "Invalid or missing gateway token",
        403: "Capability is not granted or enabled",
        404: "Resource was not found",
        409: "Oura connection is unavailable",
        400: "Request validation failed",
        429: "Request was rate limited",
        500: "Unexpected server failure",
        502: "Provider response failed",
        503: "Application service is unavailable",
        504: "Provider request timed out",
    }.items()
}


def _now() -> datetime:
    return datetime.now(UTC)


def _codec(request: Request) -> CursorCodec:
    return cast(CursorCodec, request.app.state.cursor_codec)


def _parameters(query: Any, *, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    parameters = cast(dict[str, Any], query.model_dump(mode="json", exclude={"cursor"}))
    if extra:
        parameters.update(extra)
    return parameters


def _service_query(request: Request, query: Any, *, extra: Mapping[str, Any] | None = None) -> ServiceQuery:
    parameters = _parameters(query, extra=extra)
    cursor = getattr(query, "cursor", None)
    continuation = None
    if cursor is not None:
        continuation = _codec(request).decode(cursor, route=request.url.path, query=parameters)
    return ServiceQuery(parameters=parameters, continuation=continuation)


def _range_meta(query: Any) -> DateRangeMeta | DateTimeRangeMeta | None:
    if isinstance(query, DateRangeQuery):
        return DateRangeMeta(start_date=query.start_date, end_date=query.end_date)
    if isinstance(query, DateTimeRangeQuery):
        if query.start_datetime is not None and query.end_datetime is not None:
            return DateTimeRangeMeta(start_datetime=query.start_datetime, end_datetime=query.end_datetime)
    return None


def _envelope(
    request: Request,
    result: ServiceResult,
    *,
    query: Any | None = None,
    parameters: Mapping[str, Any] | None = None,
) -> SuccessEnvelope:
    retrieved_at = result.retrieved_at or _now()
    fetched_at = result.fetched_at or retrieved_at
    warnings = [item if isinstance(item, WarningItem) else WarningItem.model_validate(item) for item in result.warnings]
    next_cursor = None
    if result.continuation is not None:
        if parameters is None:
            if query is None:
                raise RuntimeError("paginated responses require cursor-bound parameters")
            parameters = _parameters(query)
        next_cursor = _codec(request).encode(
            route=request.url.path,
            query=parameters,
            continuation=result.continuation,
        )
    return SuccessEnvelope(
        data=result.data,
        meta=ResponseMeta(
            request_id=request.state.request_id,
            range=_range_meta(query),
            next_cursor=next_cursor,
            retrieved_at=retrieved_at,
            freshness=FreshnessMeta(
                source=result.freshness_source,
                fetched_at=fetched_at,
                stale=result.stale,
            ),
        ),
        warnings=warnings,
    )


def _ensure_day_is_not_future(day: date) -> None:
    if day > date.today():
        raise APIProblem(
            status=400,
            code="future_date_not_allowed",
            title="Future date is not allowed",
            detail="The requested day must not be in the future.",
        )


def _register_date_resource(router: APIRouter, path: str, resource: str, *, experimental: bool = False) -> None:
    tags: list[str | Enum] = ["experimental" if experimental else "oura resources"]

    async def collection(
        request: Request,
        query: Annotated[DateRangeQuery, Query()],
        service: Annotated[APIService, Depends(get_service)],
    ) -> SuccessEnvelope:
        service_query = _service_query(request, query)
        result = await invoke(service.collection, resource, service_query)
        return _envelope(request, result, query=query, parameters=service_query.parameters)

    async def document(
        request: Request,
        source_id: Annotated[str, Path(min_length=1, max_length=256)],
        _query: Annotated[EmptyQuery, Query()],
        service: Annotated[APIService, Depends(get_service)],
    ) -> SuccessEnvelope:
        result = await invoke(service.document, resource, source_id)
        return _envelope(request, result)

    label = resource.replace("_", "-")
    router.add_api_route(
        path,
        collection,
        methods=["GET"],
        response_model=SuccessEnvelope,
        responses=PROBLEM_RESPONSES,
        tags=tags,
        name=f"list-{label}",
        operation_id=f"list_{resource}",
    )
    router.add_api_route(
        f"{path}/{{source_id}}",
        document,
        methods=["GET"],
        response_model=SuccessEnvelope,
        responses=PROBLEM_RESPONSES,
        tags=tags,
        name=f"get-{label}",
        operation_id=f"get_{resource}",
    )


def _register_time_series_resource(router: APIRouter, path: str, resource: str) -> None:
    async def collection(
        request: Request,
        query: Annotated[DateTimeRangeQuery, Query()],
        service: Annotated[APIService, Depends(get_service)],
    ) -> SuccessEnvelope:
        service_query = _service_query(request, query)
        result = await invoke(service.collection, resource, service_query)
        return _envelope(request, result, query=query, parameters=service_query.parameters)

    router.add_api_route(
        path,
        collection,
        methods=["GET"],
        response_model=SuccessEnvelope,
        responses=PROBLEM_RESPONSES,
        tags=["oura resources"],
        name=f"list-{resource.replace('_', '-')}",
        operation_id=f"list_{resource}",
    )


def _register_cursor_only_resource(router: APIRouter, path: str, resource: str) -> None:
    async def collection(
        request: Request,
        query: Annotated[CursorOnlyQuery, Query()],
        service: Annotated[APIService, Depends(get_service)],
    ) -> SuccessEnvelope:
        service_query = _service_query(request, query)
        result = await invoke(service.collection, resource, service_query)
        return _envelope(request, result, query=query, parameters=service_query.parameters)

    async def document(
        request: Request,
        source_id: Annotated[str, Path(min_length=1, max_length=256)],
        _query: Annotated[EmptyQuery, Query()],
        service: Annotated[APIService, Depends(get_service)],
    ) -> SuccessEnvelope:
        return _envelope(request, await invoke(service.document, resource, source_id))

    label = resource.replace("_", "-")
    router.add_api_route(
        path,
        collection,
        methods=["GET"],
        response_model=SuccessEnvelope,
        responses=PROBLEM_RESPONSES,
        tags=["oura resources"],
        name=f"list-{label}",
        operation_id=f"list_{resource}",
    )
    router.add_api_route(
        f"{path}/{{source_id}}",
        document,
        methods=["GET"],
        response_model=SuccessEnvelope,
        responses=PROBLEM_RESPONSES,
        tags=["oura resources"],
        name=f"get-{label}",
        operation_id=f"get_{resource}",
    )


def _register_sample_resource(router: APIRouter, path: str, resource: str, sample: str) -> None:
    async def samples(
        request: Request,
        source_id: Annotated[str, Path(min_length=1, max_length=256)],
        query: Annotated[SampleQuery, Query()],
        service: Annotated[APIService, Depends(get_service)],
    ) -> SuccessEnvelope:
        service_query = _service_query(request, query)
        result = await invoke(service.samples, resource, source_id, sample, service_query)
        return _envelope(request, result, query=query, parameters=service_query.parameters)

    operation = f"get_{resource}_{sample}_samples"
    router.add_api_route(
        path,
        samples,
        methods=["GET"],
        response_model=SuccessEnvelope,
        responses=PROBLEM_RESPONSES,
        tags=["samples"],
        name=operation.replace("_", "-"),
        operation_id=operation,
    )


def _register_sleep_phase_samples(router: APIRouter) -> None:
    async def sleep_phase_samples(
        request: Request,
        source_id: Annotated[str, Path(min_length=1, max_length=256)],
        query: Annotated[SleepPhaseSampleQuery, Query()],
        service: Annotated[APIService, Depends(get_service)],
    ) -> SuccessEnvelope:
        service_query = _service_query(request, query)
        result = await invoke(service.samples, "sleep_periods", source_id, "sleep_phases", service_query)
        return _envelope(request, result, query=query, parameters=service_query.parameters)

    router.add_api_route(
        "/sleep-periods/{source_id}/samples/sleep-phases",
        sleep_phase_samples,
        methods=["GET"],
        response_model=SuccessEnvelope,
        responses=PROBLEM_RESPONSES,
        tags=["samples"],
        name="get-sleep-periods-sleep-phases-samples",
        operation_id="get_sleep_periods_sleep_phases_samples",
    )


def build_public_router() -> APIRouter:
    router = APIRouter(prefix=API_PREFIX)

    @router.get("/health", response_model=SuccessEnvelope, responses=PROBLEM_RESPONSES, tags=["meta"])
    async def health(request: Request, _query: Annotated[EmptyQuery, Query()]) -> SuccessEnvelope:
        return _envelope(request, ServiceResult(data={"status": "ok"}))

    @router.get(
        "/health/challenge",
        response_model=SuccessEnvelope,
        responses=PROBLEM_RESPONSES,
        tags=["meta"],
    )
    async def health_challenge(
        request: Request,
        query: Annotated[HealthChallengeQuery, Query()],
    ) -> SuccessEnvelope:
        gateway_token = request.app.state.gateway_token
        if not isinstance(gateway_token, str) or not gateway_token:
            raise APIProblem(
                status=503,
                code="gateway_identity_unavailable",
                title="Gateway identity is unavailable",
                detail="The local API gateway identity is not configured.",
            )
        proof = hmac.new(
            gateway_token.encode("ascii"),
            HEALTH_CHALLENGE_CONTEXT + query.nonce.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        return _envelope(
            request,
            ServiceResult(
                data={
                    "status": "ok",
                    "process_id": os.getpid(),
                    "challenge_response": proof,
                }
            ),
        )

    @router.get("/auth/callback", response_model=SuccessEnvelope, responses=PROBLEM_RESPONSES, tags=["authorization"])
    async def oauth_callback(
        request: Request,
        query: Annotated[OAuthCallbackQuery, Query()],
        service: Annotated[APIService, Depends(get_service)],
    ) -> SuccessEnvelope:
        result = await invoke(service.oauth_callback, query.model_dump(mode="json", exclude_none=True))
        return _envelope(request, result)

    return router


def build_protected_router() -> APIRouter:
    router = APIRouter(prefix=API_PREFIX, dependencies=[Security(require_gateway_token)])

    @router.get("/status", response_model=SuccessEnvelope, responses=PROBLEM_RESPONSES, tags=["meta"])
    async def status(
        request: Request,
        _query: Annotated[EmptyQuery, Query()],
        service: Annotated[APIService, Depends(get_service)],
    ) -> SuccessEnvelope:
        return _envelope(request, await invoke(service.status))

    @router.get("/capabilities", response_model=SuccessEnvelope, responses=PROBLEM_RESPONSES, tags=["meta"])
    async def capabilities(
        request: Request,
        _query: Annotated[EmptyQuery, Query()],
        service: Annotated[APIService, Depends(get_service)],
    ) -> SuccessEnvelope:
        return _envelope(request, await invoke(service.capabilities))

    @router.get("/profile", response_model=SuccessEnvelope, responses=PROBLEM_RESPONSES, tags=["oura resources"])
    async def profile(
        request: Request,
        _query: Annotated[EmptyQuery, Query()],
        service: Annotated[APIService, Depends(get_service)],
    ) -> SuccessEnvelope:
        return _envelope(request, await invoke(service.singleton, "profile"))

    @router.post("/auth/authorizations", response_model=SuccessEnvelope, responses=PROBLEM_RESPONSES, tags=["authorization"])
    async def create_authorization(
        request: Request,
        _query: Annotated[EmptyQuery, Query()],
        service: Annotated[APIService, Depends(get_service)],
        _body: Annotated[EmptyBody | None, Body()] = None,
    ) -> SuccessEnvelope:
        return _envelope(request, await invoke(service.create_authorization))

    @router.get("/auth/connection", response_model=SuccessEnvelope, responses=PROBLEM_RESPONSES, tags=["authorization"])
    async def connection(
        request: Request,
        _query: Annotated[EmptyQuery, Query()],
        service: Annotated[APIService, Depends(get_service)],
    ) -> SuccessEnvelope:
        return _envelope(request, await invoke(service.connection))

    @router.delete("/auth/connection", response_model=SuccessEnvelope, responses=PROBLEM_RESPONSES, tags=["authorization"])
    async def delete_connection(
        request: Request,
        _query: Annotated[EmptyQuery, Query()],
        service: Annotated[APIService, Depends(get_service)],
    ) -> SuccessEnvelope:
        return _envelope(request, await invoke(service.delete_connection))

    for path, resource in STABLE_DATE_RESOURCES.items():
        _register_date_resource(router, path, resource)
    for path, resource in CURSOR_ONLY_RESOURCES.items():
        _register_cursor_only_resource(router, path, resource)
    for path, resource in STABLE_TIME_SERIES_RESOURCES.items():
        _register_time_series_resource(router, path, resource)
    for path, resource in EXPERIMENTAL_DATE_RESOURCES.items():
        _register_date_resource(router, path, resource, experimental=True)
    for path, (resource, sample) in SAMPLE_RESOURCES.items():
        _register_sample_resource(router, path, resource, sample)
    _register_sleep_phase_samples(router)

    @router.get("/days", response_model=SuccessEnvelope, responses=PROBLEM_RESPONSES, tags=["curated"])
    async def composite_days(
        request: Request,
        query: Annotated[CompositeDaysQuery, Query()],
        service: Annotated[APIService, Depends(get_service)],
    ) -> SuccessEnvelope:
        service_query = _service_query(request, query, extra={"include": list(query.include_sections)})
        result = await invoke(service.composite_days, service_query)
        return _envelope(request, result, query=query, parameters=service_query.parameters)

    @router.get("/days/{day}", response_model=SuccessEnvelope, responses=PROBLEM_RESPONSES, tags=["curated"])
    async def composite_day(
        request: Request,
        day: date,
        query: Annotated[CompositeDayQuery, Query()],
        service: Annotated[APIService, Depends(get_service)],
    ) -> SuccessEnvelope:
        _ensure_day_is_not_future(day)
        result = await invoke(service.composite_day, day.isoformat(), query.include_sections)
        return _envelope(request, result, query=query)

    @router.get("/analytics/daily-signals", response_model=SuccessEnvelope, responses=PROBLEM_RESPONSES, tags=["analytics"])
    async def daily_signals(
        request: Request,
        query: Annotated[DateRangeQuery, Query()],
        service: Annotated[APIService, Depends(get_service)],
    ) -> SuccessEnvelope:
        service_query = _service_query(request, query)
        result = await invoke(service.daily_signals, service_query)
        return _envelope(request, result, query=query, parameters=service_query.parameters)

    @router.get(
        "/analytics/daily-signals/{day}",
        response_model=SuccessEnvelope,
        responses=PROBLEM_RESPONSES,
        tags=["analytics"],
    )
    async def daily_signal(
        request: Request,
        day: date,
        _query: Annotated[EmptyQuery, Query()],
        service: Annotated[APIService, Depends(get_service)],
    ) -> SuccessEnvelope:
        _ensure_day_is_not_future(day)
        return _envelope(request, await invoke(service.daily_signal, day.isoformat()))

    @router.get("/analytics/weekly-trends", response_model=SuccessEnvelope, responses=PROBLEM_RESPONSES, tags=["analytics"])
    async def weekly_trends(
        request: Request,
        query: Annotated[DateRangeQuery, Query()],
        service: Annotated[APIService, Depends(get_service)],
    ) -> SuccessEnvelope:
        service_query = _service_query(request, query)
        result = await invoke(service.weekly_trends, service_query)
        return _envelope(request, result, query=query, parameters=service_query.parameters)

    return router
