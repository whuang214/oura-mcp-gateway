"""Numeric and parsing primitives shared by analytics projections."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence

TWO_PLACES = Decimal("0.01")
ONE_PLACE = Decimal("0.1")
WHOLE = Decimal("1")


def as_decimal(value: object) -> Decimal | None:
    """Return a finite decimal while rejecting bools and malformed values."""

    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def as_float(value: object) -> float | None:
    number = as_decimal(value)
    return float(number) if number is not None else None


def as_int(value: object) -> int | None:
    number = as_decimal(value)
    if number is None:
        return None
    return int(number.to_integral_value(rounding=ROUND_HALF_UP))


def nonnegative_int(value: object) -> int | None:
    number = as_int(value)
    return number if number is not None and number >= 0 else None


def round_half_up(value: object, quantum: Decimal = TWO_PLACES) -> float | None:
    number = as_decimal(value)
    if number is None:
        return None
    return float(number.quantize(quantum, rounding=ROUND_HALF_UP))


def round_whole(value: object) -> int | None:
    number = as_decimal(value)
    if number is None:
        return None
    return int(number.quantize(WHOLE, rounding=ROUND_HALF_UP))


def seconds_to_hours(seconds: object) -> float | None:
    value = nonnegative_int(seconds)
    if value is None:
        return None
    return round_half_up(Decimal(value) / Decimal(3600))


def seconds_to_display(seconds: object) -> str | None:
    value = nonnegative_int(seconds)
    if value is None:
        return None
    minutes = int((Decimal(value) / Decimal(60)).quantize(WHOLE, rounding=ROUND_HALF_UP))
    hours, remaining = divmod(minutes, 60)
    return f"{hours}h {remaining}m"


def seconds_to_minutes(seconds: object) -> int | None:
    value = nonnegative_int(seconds)
    if value is None:
        return None
    return int((Decimal(value) / Decimal(60)).quantize(WHOLE, rounding=ROUND_HALF_UP))


def mean(values: Sequence[float | int], quantum: Decimal = TWO_PLACES) -> float | None:
    if not values:
        return None
    decimals = [Decimal(str(value)) for value in values if isfinite(float(value))]
    if not decimals:
        return None
    return round_half_up(sum(decimals, Decimal(0)) / Decimal(len(decimals)), quantum)


def median(values: Sequence[float | int], quantum: Decimal = TWO_PLACES) -> float | None:
    if not values:
        return None
    ordered = sorted(Decimal(str(value)) for value in values if isfinite(float(value)))
    if not ordered:
        return None
    middle = len(ordered) // 2
    value = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / Decimal(2)
    return round_half_up(value, quantum)


def observed_sum(values: Sequence[float | int], quantum: Decimal = TWO_PLACES) -> float | None:
    if not values:
        return None
    return round_half_up(sum((Decimal(str(value)) for value in values), Decimal(0)), quantum)


def parse_day(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_aware_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def elapsed_seconds(record: Mapping[str, Any]) -> int | None:
    direct = nonnegative_int(record.get("duration_seconds"))
    if direct is not None:
        return direct
    start = parse_aware_datetime(record.get("start_datetime"))
    end = parse_aware_datetime(record.get("end_datetime"))
    if start is None or end is None:
        return None
    value = int((end - start).total_seconds())
    return value if value >= 0 else None


def ensure_utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("last_synced_at_utc must include a UTC offset")
    return value.astimezone(timezone.utc)


def display_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    collapsed = " ".join(value.replace("_", " ").split())
    return collapsed.title() if collapsed else None


def counted_summary(values: Iterable[str]) -> str | None:
    counts = Counter(value for value in values if value)
    if not counts:
        return None
    return ", ".join(f"{name} ({counts[name]})" for name in sorted(counts, key=str.casefold))


def frequency_summary(values: Iterable[str]) -> str | None:
    counts = Counter(value for value in values if value)
    if not counts:
        return None
    ordered = sorted(counts, key=lambda name: (-counts[name], name.casefold(), name))
    return ", ".join(f"{name} ({counts[name]})" for name in ordered)


def compact_warnings(values: Iterable[str]) -> str | None:
    warnings = sorted({value.strip() for value in values if value and value.strip()}, key=str.casefold)
    return "; ".join(warnings) if warnings else None
