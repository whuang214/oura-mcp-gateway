"""Strict request and response models for the public HTTP contract."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

API_VERSION: Literal["1"] = "1"
SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
PROVIDER_API_VERSION: Literal["2"] = "2"
PROVIDER_SCHEMA_REVISION = "1.35"

MAX_DATE_RANGE_DAYS = 90
MAX_DATETIME_RANGE = timedelta(days=7)
MAX_CURSOR_LENGTH = 4096

DEFAULT_INCLUDE_SECTIONS = ("sleep", "readiness", "activity")
ALLOWED_INCLUDE_SECTIONS = frozenset(
    {
        "sleep",
        "readiness",
        "activity",
        "stress",
        "spo2",
        "workouts",
        "sessions",
        "cardiovascular_age",
        "vo2_max",
        "tags",
    }
)


class StrictModel(BaseModel):
    """Base model that makes additions intentional at every API boundary."""

    model_config = ConfigDict(extra="forbid")


class EmptyQuery(StrictModel):
    """Reject query parameters on routes that do not define any."""


class HealthChallengeQuery(StrictModel):
    nonce: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class PaginatedQuery(StrictModel):
    limit: int = Field(default=100, ge=1, le=1000)
    cursor: str | None = Field(default=None, min_length=1, max_length=MAX_CURSOR_LENGTH)

    def cursor_binding(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"cursor"})


class CursorOnlyQuery(PaginatedQuery):
    """Collection pagination for provider resources with no date filter."""


class DateRangeQuery(PaginatedQuery):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_range(self) -> DateRangeQuery:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if (self.end_date - self.start_date).days + 1 > MAX_DATE_RANGE_DAYS:
            raise ValueError(f"date ranges may include at most {MAX_DATE_RANGE_DAYS} days")
        return self


class DateTimeRangeQuery(PaginatedQuery):
    start_datetime: datetime | None = None
    end_datetime: datetime | None = None
    latest: bool = False

    @field_validator("start_datetime", "end_datetime")
    @classmethod
    def require_offset(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include a UTC offset")
        return value

    @model_validator(mode="after")
    def validate_range(self) -> DateTimeRangeQuery:
        has_start = self.start_datetime is not None
        has_end = self.end_datetime is not None
        if self.latest:
            if has_start or has_end:
                raise ValueError("latest cannot be combined with datetime bounds")
            return self
        if not has_start or not has_end:
            raise ValueError("provide latest=true or both datetime bounds")
        assert self.start_datetime is not None and self.end_datetime is not None
        if self.end_datetime <= self.start_datetime:
            raise ValueError("end_datetime must be after start_datetime")
        if self.end_datetime - self.start_datetime > MAX_DATETIME_RANGE:
            raise ValueError("time-series ranges may span at most seven days")
        if self.end_datetime.astimezone(UTC) > datetime.now(UTC):
            raise ValueError("future timestamps are not allowed")
        return self


class SampleQuery(PaginatedQuery):
    limit: int = Field(default=500, ge=1, le=5000)


class SleepPhaseSampleQuery(SampleQuery):
    resolution: Literal["30s", "5m"] = "30s"


def _parse_include(value: str | None) -> tuple[str, ...]:
    if value is None or not value.strip():
        return DEFAULT_INCLUDE_SECTIONS
    sections = tuple(dict.fromkeys(part.strip().lower().replace("-", "_") for part in value.split(",") if part.strip()))
    unknown = sorted(set(sections) - ALLOWED_INCLUDE_SECTIONS)
    if unknown:
        raise ValueError(f"unknown include section: {', '.join(unknown)}")
    return sections


class CompositeDaysQuery(DateRangeQuery):
    include: str | None = None

    @property
    def include_sections(self) -> tuple[str, ...]:
        return _parse_include(self.include)

    @field_validator("include")
    @classmethod
    def validate_include(cls, value: str | None) -> str | None:
        _parse_include(value)
        return value


class CompositeDayQuery(StrictModel):
    include: str | None = None

    @property
    def include_sections(self) -> tuple[str, ...]:
        return _parse_include(self.include)

    @field_validator("include")
    @classmethod
    def validate_include(cls, value: str | None) -> str | None:
        _parse_include(value)
        return value


class OAuthCallbackQuery(StrictModel):
    code: str | None = Field(default=None, min_length=1, max_length=4096)
    state: str = Field(min_length=16, max_length=4096)
    scope: str | None = Field(default=None, min_length=1, max_length=4096)
    error: str | None = Field(default=None, min_length=1, max_length=256)
    error_description: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def require_code_or_error(self) -> OAuthCallbackQuery:
        if (self.code is None) == (self.error is None):
            raise ValueError("provide exactly one of code or error")
        if self.error_description is not None and self.error is None:
            raise ValueError("error_description requires error")
        return self


class EmptyBody(StrictModel):
    """The authorization endpoint currently accepts no caller-controlled fields."""


class WarningItem(StrictModel):
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=1024)
    resource: str | None = Field(default=None, max_length=128)
    retryable: bool = False


class SourceMeta(StrictModel):
    provider: Literal["oura"] = "oura"
    provider_api_version: Literal["2"] = PROVIDER_API_VERSION
    provider_schema_revision: str = PROVIDER_SCHEMA_REVISION


class DateRangeMeta(StrictModel):
    start_date: date
    end_date: date


class DateTimeRangeMeta(StrictModel):
    start_datetime: AwareDatetime
    end_datetime: AwareDatetime


RangeMeta = DateRangeMeta | DateTimeRangeMeta


class FreshnessMeta(StrictModel):
    source: Literal["live", "cache"] = "live"
    fetched_at: AwareDatetime
    stale: bool = False


class ResponseMeta(StrictModel):
    api_version: Literal["1"] = API_VERSION
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    request_id: str
    source: SourceMeta = Field(default_factory=SourceMeta)
    range: RangeMeta | None = None
    next_cursor: str | None = None
    retrieved_at: AwareDatetime
    freshness: FreshnessMeta


class SuccessEnvelope(StrictModel):
    data: Any
    meta: ResponseMeta
    warnings: list[WarningItem] = Field(default_factory=list)


class ProblemDetails(StrictModel):
    type: str
    title: str
    status: int = Field(ge=400, le=599)
    detail: str
    instance: str
    code: str
    request_id: str
    retryable: bool = False
    retry_after_seconds: int | None = Field(default=None, ge=0)
