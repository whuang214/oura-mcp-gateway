"""Verified registry of official Oura API V2 user-collection resources."""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from .models import FilterKind, ResourceMaturity, ResourceSpec

_USER_COLLECTION = "/v2/usercollection"


def _resource(
    key: str,
    provider_name: str,
    filter_kind: FilterKind,
    capability_key: str,
    *,
    scopes: tuple[str, ...] = (),
    document_lookup: bool = False,
    maturity: ResourceMaturity = ResourceMaturity.STABLE,
    fields: bool = True,
) -> ResourceSpec:
    return ResourceSpec(
        key=key,
        provider_path=f"{_USER_COLLECTION}/{provider_name}",
        filter_kind=filter_kind,
        maturity=maturity,
        capability_key=capability_key,
        oauth_scopes=scopes,
        supports_document_lookup=document_lookup,
        supports_fields=fields,
    )


# Scope tuples are populated only where the official documentation provides a
# safe mapping. Newer portal permission categories are represented by distinct
# capability keys rather than guessed OAuth scope strings.
_RESOURCE_SPECS = {
    "profile": _resource(
        "profile",
        "personal_info",
        FilterKind.SINGLETON,
        "profile",
        scopes=("email", "personal"),
        fields=False,
    ),
    "daily_activity": _resource(
        "daily_activity",
        "daily_activity",
        FilterKind.DATE,
        "daily_activity",
        scopes=("daily",),
        document_lookup=True,
    ),
    "daily_cardiovascular_age": _resource(
        "daily_cardiovascular_age",
        "daily_cardiovascular_age",
        FilterKind.DATE,
        "cardiovascular_age",
        document_lookup=True,
    ),
    "daily_readiness": _resource(
        "daily_readiness",
        "daily_readiness",
        FilterKind.DATE,
        "daily_readiness",
        scopes=("daily",),
        document_lookup=True,
    ),
    "daily_resilience": _resource(
        "daily_resilience",
        "daily_resilience",
        FilterKind.DATE,
        "daily_resilience",
        document_lookup=True,
        maturity=ResourceMaturity.EXPERIMENTAL,
        fields=False,
    ),
    "daily_sleep": _resource(
        "daily_sleep",
        "daily_sleep",
        FilterKind.DATE,
        "daily_sleep",
        scopes=("daily",),
        document_lookup=True,
    ),
    "daily_spo2": _resource(
        "daily_spo2",
        "daily_spo2",
        FilterKind.DATE,
        "daily_spo2",
        scopes=("spo2Daily", "spo2"),
        document_lookup=True,
    ),
    "daily_stress": _resource(
        "daily_stress",
        "daily_stress",
        FilterKind.DATE,
        "daily_stress",
        document_lookup=True,
    ),
    "enhanced_tags": _resource(
        "enhanced_tags",
        "enhanced_tag",
        FilterKind.DATE,
        "enhanced_tags",
        scopes=("tag",),
        document_lookup=True,
        fields=False,
    ),
    "heart_rate": _resource(
        "heart_rate",
        "heartrate",
        FilterKind.DATETIME,
        "heart_rate",
        scopes=("heartrate",),
        fields=True,
    ),
    "rest_mode_periods": _resource(
        "rest_mode_periods",
        "rest_mode_period",
        FilterKind.DATE,
        "rest_mode",
        document_lookup=True,
    ),
    "ring_battery": _resource(
        "ring_battery",
        "ring_battery_level",
        FilterKind.DATETIME,
        "ring_battery",
    ),
    "rings": _resource(
        "rings",
        "ring_configuration",
        FilterKind.CURSOR_ONLY,
        "ring_configuration",
        document_lookup=True,
    ),
    "sessions": _resource(
        "sessions",
        "session",
        FilterKind.DATE,
        "sessions",
        scopes=("session",),
        document_lookup=True,
    ),
    "sleep_periods": _resource(
        "sleep_periods",
        "sleep",
        FilterKind.DATE,
        "sleep_periods",
        scopes=("daily",),
        document_lookup=True,
    ),
    "sleep_times": _resource(
        "sleep_times",
        "sleep_time",
        FilterKind.DATE,
        "sleep_times",
        scopes=("daily",),
        document_lookup=True,
    ),
    "legacy_tags": _resource(
        "legacy_tags",
        "tag",
        FilterKind.DATE,
        "legacy_tags",
        scopes=("tag",),
        document_lookup=True,
        maturity=ResourceMaturity.EXPERIMENTAL,
        fields=False,
    ),
    "vo2_max": _resource(
        "vo2_max",
        "vO2_max",
        FilterKind.DATE,
        "vo2_max",
        document_lookup=True,
    ),
    "workouts": _resource(
        "workouts",
        "workout",
        FilterKind.DATE,
        "workouts",
        scopes=("workout",),
        document_lookup=True,
    ),
}

RESOURCE_SPECS: Final = MappingProxyType(_RESOURCE_SPECS)

_PROVIDER_NAME_ALIASES: Final = MappingProxyType(
    {
        "enhanced_tag": "enhanced_tags",
        "heartrate": "heart_rate",
        "rest_mode_period": "rest_mode_periods",
        "ring_battery_level": "ring_battery",
        "ring_configuration": "rings",
        "session": "sessions",
        "sleep": "sleep_periods",
        "sleep_time": "sleep_times",
        "tag": "legacy_tags",
        "workout": "workouts",
    }
)


def get_resource_spec(resource: str | ResourceSpec) -> ResourceSpec:
    """Resolve a registry key while accepting an already-resolved spec."""

    if isinstance(resource, ResourceSpec):
        return resource
    try:
        return RESOURCE_SPECS[_PROVIDER_NAME_ALIASES.get(resource, resource)]
    except KeyError as exc:
        raise ValueError(f"Unsupported Oura resource: {resource}") from exc
