"""Deterministic analysis-ready projections over canonical Oura resources."""

from .daily import (
    BASELINE_WINDOW_DAYS,
    CORE_RESOURCES,
    DEFAULT_CONTRIBUTOR_ATTENTION_THRESHOLD,
    DEVELOPING_BASELINE_N,
    SUFFICIENT_BASELINE_N,
    apply_daily_baselines,
    build_daily_coverage,
    build_daily_signals,
    classify_daily_coverage,
)
from .models import (
    API_VERSION,
    CONTRACT_VERSION,
    FEATURE_VERSION,
    BaselineStatus,
    CoverageStatus,
    DailyCoverage,
    DailySignal,
    ResourceOutcome,
    ResourceOutcomeStatus,
    WeeklyTrend,
)
from .weekly import build_weekly_trends

__all__ = [
    "API_VERSION",
    "BASELINE_WINDOW_DAYS",
    "CONTRACT_VERSION",
    "CORE_RESOURCES",
    "DEFAULT_CONTRIBUTOR_ATTENTION_THRESHOLD",
    "DEVELOPING_BASELINE_N",
    "FEATURE_VERSION",
    "SUFFICIENT_BASELINE_N",
    "BaselineStatus",
    "CoverageStatus",
    "DailyCoverage",
    "DailySignal",
    "ResourceOutcome",
    "ResourceOutcomeStatus",
    "WeeklyTrend",
    "apply_daily_baselines",
    "build_daily_coverage",
    "build_daily_signals",
    "build_weekly_trends",
    "classify_daily_coverage",
]
