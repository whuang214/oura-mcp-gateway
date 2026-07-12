"""Pure provider-to-public mapping and dense-sample extraction."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from ..errors import ApiError

JsonObject = dict[str, Any]

_DENSE_FIELDS: dict[str, frozenset[str]] = {
    "daily_activity": frozenset({"met", "class_5_min"}),
    "sleep_periods": frozenset(
        {
            "heart_rate",
            "hrv",
            "movement_30_sec",
            "sleep_phase_30_sec",
            "sleep_phase_5_min",
            "app_sleep_phase_5_min",
        }
    ),
    "sessions": frozenset({"heart_rate", "hrv", "motion_count"}),
}


def _rename(record: JsonObject, old: str, new: str) -> None:
    if old in record:
        record[new] = record.pop(old)


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _duration_seconds(record: Mapping[str, Any]) -> int | None:
    start = _parse_datetime(record.get("start_datetime"))
    end = _parse_datetime(record.get("end_datetime"))
    if start is None or end is None:
        return None
    value = int((end - start).total_seconds())
    return value if value >= 0 else None


def _offset_text(value: object) -> str | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    offset = parsed.utcoffset()
    if offset is None:
        return None
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    absolute = abs(minutes)
    return f"{sign}{absolute // 60:02d}:{absolute % 60:02d}"


def canonicalize_record(resource: str, source: Mapping[str, Any]) -> JsonObject:
    """Return one stable JSON record without dense arrays or provider UUID lists."""

    dense = _DENSE_FIELDS.get(resource, frozenset())
    record = {key: value for key, value in source.items() if key not in dense}
    if resource == "profile":
        _rename(record, "id", "source_user_id")
    else:
        _rename(record, "id", "source_id")

    if resource == "daily_activity":
        for old, new in {
            "active_calories": "active_calories_kcal",
            "total_calories": "total_calories_kcal",
            "equivalent_walking_distance": "equivalent_walking_distance_meters",
            "high_activity_time": "high_activity_seconds",
            "medium_activity_time": "medium_activity_seconds",
            "low_activity_time": "low_activity_seconds",
            "sedentary_time": "sedentary_seconds",
            "resting_time": "resting_seconds",
            "non_wear_time": "non_wear_seconds",
        }.items():
            _rename(record, old, new)
    elif resource == "daily_stress":
        _rename(record, "stress_high", "stress_high_seconds")
        _rename(record, "recovery_high", "recovery_high_seconds")
    elif resource == "daily_spo2":
        percentage = record.pop("spo2_percentage", None)
        if isinstance(percentage, Mapping):
            record["spo2_average_percent"] = percentage.get("average")
    elif resource == "daily_cardiovascular_age":
        _rename(record, "vascular_age", "vascular_age_years")
        _rename(record, "vascular_age_percentage", "vascular_age_percentile")
        _rename(record, "pwc", "pulse_wave_velocity_meters_per_second")
    elif resource == "sleep_periods":
        for old, new in {
            "time_in_bed": "time_in_bed_seconds",
            "total_sleep_duration": "total_sleep_seconds",
            "awake_time": "awake_seconds",
            "light_sleep_duration": "light_sleep_seconds",
            "deep_sleep_duration": "deep_sleep_seconds",
            "rem_sleep_duration": "rem_sleep_seconds",
            "latency": "latency_seconds",
            "average_breath": "average_breaths_per_minute",
            "average_heart_rate": "average_heart_rate_bpm",
            "lowest_heart_rate": "lowest_heart_rate_bpm",
            "average_hrv": "average_hrv_ms",
            "temperature_deviation": "temperature_deviation_celsius",
        }.items():
            _rename(record, old, new)
    elif resource in {"workouts", "sessions"}:
        if resource == "workouts":
            _rename(record, "calories", "calories_kcal")
            _rename(record, "distance", "distance_meters")
        duration = _duration_seconds(record)
        if duration is not None:
            record["duration_seconds"] = duration
        offset = _offset_text(record.get("start_datetime"))
        if offset is not None:
            record["utc_offset"] = offset
    elif resource == "ring_battery":
        _rename(record, "battery_level", "level_percent")
    elif resource == "vo2_max":
        _rename(record, "vo2_max", "vo2_max_ml_per_kg_per_min")

    return record


def canonicalize_records(resource: str, records: Sequence[Mapping[str, Any]]) -> list[JsonObject]:
    return [canonicalize_record(resource, record) for record in records]


def canonical_day(resource: str, record: Mapping[str, Any]) -> str | None:
    """Return Oura's canonical day or start day without timestamp inference."""

    candidate = record.get("day")
    if not isinstance(candidate, str) and resource == "rest_mode_periods":
        candidate = record.get("start_day")
    return candidate if isinstance(candidate, str) else None


def _sample_object(value: object) -> tuple[int | None, list[Any]]:
    if not isinstance(value, Mapping):
        return None, []
    interval = value.get("interval")
    items = value.get("items")
    safe_interval = int(interval) if isinstance(interval, (int, float)) and interval > 0 else None
    safe_items = list(items) if isinstance(items, Sequence) and not isinstance(items, (str, bytes)) else []
    return safe_interval, safe_items


def extract_sample(
    resource: str,
    source: Mapping[str, Any],
    sample: str,
    *,
    resolution: str | None = None,
) -> JsonObject:
    """Extract a requested dense series without returning the whole provider document."""

    source_id = source.get("id")
    start = source.get("bedtime_start", source.get("start_datetime", source.get("timestamp")))

    field: str
    unit: str
    legend: dict[str, str] | None = None
    if resource == "daily_activity" and sample == "met":
        field, unit = "met", "MET"
    elif resource == "daily_activity" and sample == "classification":
        raw = source.get("class_5_min")
        if not isinstance(raw, str):
            raise ApiError("The requested activity classification sample is unavailable", status_code=404)
        values = list(raw)
        legend = {code: f"provider_class_{code}" for code in sorted(set(values))}
        return {
            "source_id": source_id,
            "sample": sample,
            "start_datetime": start,
            "interval_seconds": 300,
            "unit": "provider_classification",
            "values": [legend[value] for value in values],
            "source_legend": legend,
        }
    elif resource in {"sleep_periods", "sessions"} and sample in {"heart_rate", "hrv"}:
        field = sample
        unit = "bpm" if sample == "heart_rate" else "ms"
    elif resource == "sessions" and sample == "motion":
        field, unit = "motion_count", "count"
    elif resource == "sleep_periods" and sample == "movement":
        raw = source.get("movement_30_sec")
        if not isinstance(raw, str):
            raise ApiError("The requested movement sample is unavailable", status_code=404)
        values = list(raw)
        legend = {code: f"provider_movement_{code}" for code in sorted(set(values))}
        return {
            "source_id": source_id,
            "sample": sample,
            "start_datetime": start,
            "interval_seconds": 30,
            "unit": "provider_movement_class",
            "values": [legend[value] for value in values],
            "source_legend": legend,
        }
    elif resource == "sleep_periods" and sample == "sleep_phases":
        selected_resolution = resolution or "5m"
        field = "sleep_phase_30_sec" if selected_resolution == "30s" else "sleep_phase_5_min"
        raw = source.get(field)
        if not isinstance(raw, str):
            raise ApiError(
                f"Sleep phases at {selected_resolution} resolution are unavailable",
                status_code=404,
            )
        phase_names = {"1": "deep", "2": "light", "3": "rem", "4": "awake"}
        values = [phase_names.get(code, f"provider_phase_{code}") for code in raw]
        return {
            "source_id": source_id,
            "sample": sample,
            "resolution": selected_resolution,
            "start_datetime": start,
            "interval_seconds": 30 if selected_resolution == "30s" else 300,
            "unit": "sleep_phase",
            "values": values,
            "source_legend": phase_names,
        }
    else:
        raise ApiError("The requested sample is unsupported", status_code=404)

    interval, values = _sample_object(source.get(field))
    if not values:
        raise ApiError("The requested sample is unavailable", status_code=404)
    return {
        "source_id": source_id,
        "sample": sample,
        "start_datetime": start,
        "interval_seconds": interval,
        "unit": unit,
        "values": values,
    }
