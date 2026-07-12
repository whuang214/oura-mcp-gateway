# Data contract

Project API schema: `1.0.0`
Feature logic: `1.0.0`

This document defines canonical model semantics shared by granular API routes,
composite days, deterministic analytics, and the dedicated Oura workbook. The
HTTP route/envelope contract is in [API V1 contract](api-contract.md).

## Canonical invariants

- Oura's returned `day` is the calendar key for daily and event attribution.
- Timestamp offsets are preserved. A missing offset is not replaced with UTC or
  the configured home timezone.
- Source IDs remain stable strings and are never exposed as Sheet array fields.
- Canonical durations are integer seconds.
- Canonical distance is meters.
- Temperature deviation is degrees Celsius.
- Heart rate is beats per minute and HRV is milliseconds.
- Oura daily scores and contributor values remain Oura-provided 0–100 values.
- Missing remains null/absent. Zero is valid only when the source returns zero
  or an explicitly documented successful-empty aggregate resolves to zero.
- The current Oura day is Provisional because the provider exposes no universal
  finalized flag.

## Resource outcome

Every requested resource has a typed outcome:

| Outcome | Meaning |
| --- | --- |
| `available` | One or more usable source records were returned |
| `empty` | Provider request succeeded authoritatively with no records |
| `not_granted` | The connected user did not grant the required capability |
| `disabled` | Local policy disabled the optional/experimental resource |
| `error` | Authentication, validation, transport, timeout, or provider failure |

Outcome is separate from the returned data. It prevents a failed child request
from being misread as an authoritative zero or deletion signal.

## Core daily status

Core daily evidence comprises daily sleep, contributing detailed sleep periods,
daily readiness, and daily activity.

- `Complete`: all core domains are usable.
- `Partial`: at least one core domain is usable and another is absent.
- `Provisional`: current Oura day contains usable data that may still change.
- `No Data`: finalized requested date has no usable core record and no core
  retrieval failure. It appears in coverage/audit only, not as an empty day.
- `Sync Error`: reliable core retrieval failed.

Stress, SpO2, resilience, cardiovascular age, VO2 max, workouts, sessions,
tags, rest mode, ring metadata, and battery are supplemental. Their failure
cannot downgrade otherwise complete core data.

## Daily resource semantics

### Activity

Preserve:

- score and contributors;
- steps;
- active/total/target calories in kcal;
- low/medium/high/resting/sedentary/non-wear durations in seconds;
- MET-minute totals;
- equivalent walking distance and targets in meters;
- dense MET/class samples only on explicit sample routes.

Calories are contextual provider estimates and do not define nutrition targets.

### Readiness

Preserve the Oura score, contributors, temperature deviation, and temperature
trend deviation. Do not create a replacement readiness score.

### Daily sleep

Preserve the Oura score and contributors. Detailed sleep duration, bedtime,
stages, heart rate, HRV, breathing, and samples belong to `sleep-periods`.

### Detailed sleep periods

Multiple records may share a day. Preserve source type/period, bedtime start and
end, time in bed, total/deep/light/REM/awake/latency seconds, efficiency,
average/lowest heart rate, average HRV, average breathing rate, and restlessness.

Primary sleep selection for curated daily signals is deterministic:

1. prefer source type `long_sleep`;
2. then longest contributing sleep duration;
3. then latest bedtime end;
4. then stable source ID.

Naps remain separate and are never silently merged into primary sleep metrics.

### Stress and resilience

Daily stress preserves high-stress seconds, high-recovery seconds, and Oura's
categorical day summary. Recovery minus stress is the signed difference of the
two durations. Experimental resilience preserves the categorical level and its
Oura contributors without inventing a numeric resilience score.

### SpO2 and heart health

Daily SpO2 preserves average percentage and breathing-disturbance index when
available. Cardiovascular age preserves vascular age and pulse-wave velocity;
VO2 max preserves the Oura estimate and source timestamp.

## Events and time series

### Workouts

Preserve source ID, Oura day, raw activity, label, localized start/end,
intensity, source, duration seconds, calories kcal, and distance meters when
present. The provider schema does not promise workout heart-rate samples.

### Sessions

Preserve source ID, day, type, mood, localized start/end, and optional sampled
heart-rate, HRV, and motion series. Default session summaries omit dense arrays;
sample subresources expose them.

### Enhanced tags and rest mode

Preserve current enhanced tag type code, custom name/comment, start/end day and
time. Legacy tag is deprecated. Rest-mode periods preserve their start/end and
tagged episodes.

### Heart rate and ring battery

Time-series responses preserve UTC timestamp, Unix milliseconds when supplied,
value, and source/status fields. They use explicit datetime bounds and bounded
pagination.

### Ring configuration

Preserve ring color, design, firmware version, hardware type, size, setup time,
and source ID. Treat these as device metadata, not coaching evidence.

## Curated DailySignal

The deterministic daily projection contains only scalar, readable facts:

- canonical date and core status/coverage;
- sleep score/hours/display/efficiency/bedtime/wake;
- readiness/activity scores;
- HRV, lowest sleeping heart rate, and temperature deviation;
- stress/recovery hours and signed balance;
- SpO2/BDI when available;
- steps;
- context-only active calories;
- workout count/minutes/types;
- Oura contributor attention names;
- prior-only baseline medians, deltas, sample counts, and baseline state;
- warnings, freshness, API version, feature version, and contract version.

It contains no JSON arrays, source-ID collections, raw payloads, AI prose,
diagnosis, nutrition prescription, or invented composite score.

## Curated WeeklyTrend

Weekly projections expose:

- calendar week bounds;
- expected and usable days;
- daily status counts;
- sleep average/median and observation count;
- readiness/HRV/lowest-HR medians and observation counts;
- deterministic baseline deltas;
- steps average and count;
- observed stress/recovery totals and coverage days;
- workout count/minutes/types;
- contributor attention frequency;
- warnings and versions.

Weekly calculations never extrapolate missing days and never expose a wearable
calorie target or net-calorie total.

## Baselines

- Prior 28 calendar days only.
- Median of valid observations.
- Exclude target day and Provisional observations.
- No future data, forward fill, interpolation, or imputation.
- `Sufficient`: at least 14 observations.
- `Developing`: 7–13 observations.
- `Unavailable`: fewer than 7; delta is null.

Daily features include:

- sleep hours delta;
- HRV percentage delta when the nonzero baseline exists;
- lowest sleeping heart-rate delta in bpm;
- recovery-high minus stress-high hours.

These are deterministic comparisons, not health conclusions.

## Presentation conversions

- Hours: seconds / 3,600, rounded half-up to two decimals.
- Sleep display: total seconds rounded half-up to the nearest minute, rendered
  `Xh Ym`.
- Event minutes: source seconds rounded half-up to a whole minute.
- Distance km: meters / 1,000, rounded half-up to two decimals.
- Temperature: signed Celsius rounded to two decimals.
- Calories: half-up whole kcal for display only.

Canonical API source routes retain raw units. Curated API/Sheet projections own
the documented display conversions so downstream consumers do not implement
competing rounding rules.

## Missing-data behavior

- A missing date is omitted, not synthesized.
- A singular day/document request with no record returns `404`.
- A successful empty collection returns `data: []` plus an `empty` outcome.
- A failed optional resource produces a warning and preserves usable data.
- A failed core resource produces `Sync Error` coverage and a retryable flag
  when appropriate.
- Missing Oura data never blocks external nutrition logging.
