# Data contract

Schema version: `2.0.0`

This document defines the shape and semantics of the data returned by `sync_oura_daily_data`: the normalized
`records` collection and the analysis-ready `transformed` collections. Downstream tools can rely on these
rules across releases of the same schema version.

## Invariants

- Oura's returned `day` is the canonical calendar attribution for daily and event records.
- ISO 8601 source offsets are preserved; a missing offset is never replaced with `+00:00`.
- Scores are 0–100 aggregates and durations are seconds unless a field states otherwise.
- Current-day records may be incomplete and are treated as provisional.
- Missing or unsynchronized source dates are valid and never become zero-valued placeholders.
- Supplemental resilience and SpO2 values are optional capabilities.

See [Architecture](architecture.md) for the dated Oura API research behind these decisions.

## Normalized source records (`records`)

The `records` collection preserves source-level detail before the curated transformation. `effective_date` is
Oura's returned `day`, never derived from UTC. Each record carries a renderable `timezone_offset` (for
example `-06:00`) and `timezone_offset_minutes` derived from primary sleep, with daily timestamps as
fallback — this supports travel without pretending every offset equals your home timezone.

| Field | Unit or meaning |
|---|---|
| `sleep_score`, `readiness_score`, `activity_score` | Oura score, unitless |
| `sleep_duration_seconds` | Contributing long-sleep, sleep, and late-nap seconds; excludes rest and deleted records |
| `sleep_efficiency_percent` | Primary long sleep, falling back to the longest contributing sleep |
| `steps` | count |
| `active_calories_kcal` | kcal; context only |
| `lowest_sleep_heart_rate_bpm` | primary-sleep lowest heart rate |
| `average_hrv_ms` | primary-sleep average HRV |
| `temperature_deviation_celsius` | degrees Celsius relative to Oura's baseline |
| `stress_high_seconds`, `recovery_high_seconds` | seconds from daily stress |
| `resilience_level` | Oura categorical value when available |
| `spo2_average_percent`, `breathing_disturbance_index` | optional daily SpO2 values |
| `workout_count`, `session_count` | zero only after a successful empty endpoint; null after an endpoint failure |
| `source_ids` | returned IDs by endpoint, including excluded rest/deleted sleep IDs |
| `retrieved_at` | timezone-aware UTC retrieval time |

The table lists the analytically significant fields; records also carry `has_source_records`, sleep window
timestamps, derived hour/minute variants of the duration fields, and structured `workouts` and `sessions`
arrays.

Primary sleep selection is deterministic: prefer `long_sleep`, then duration, then latest `bedtime_end`, then
source ID. Workouts and sessions are structured arrays sorted by start time, then source ID.

Missing numeric data stays null. `section_coverage` distinguishes available, successful-empty, missing, and
error states, and expected upstream failures become sanitized section errors.

Each record also carries `completeness_status`, a source-level state with its own vocabulary: `Sync Error`
(a core section failed), `Provisional` (the current day), `Missing` (a finalized day where not every core
section is available), `Partial` (all core sections available but an optional section failed), and
`Complete`. The consumer-facing statuses below apply to the `transformed` collections and `summary`, not to
this field.

## Transformation rules

- Missing remains null. Zero is emitted only from an explicit source zero or a successfully empty child
  endpoint.
- Hours are rounded to two decimals. Display sleep duration rounds total seconds to the nearest minute using
  half-up rounding, then renders `Xh Ym`.
- Each workout/session duration rounds half-up from source seconds to whole minutes. The daily workout
  duration is the sum of those displayed child minutes, so the children and the daily aggregate agree
  exactly; if any contributing duration is unknown, the aggregate is null.
- Daily active calories and workout calories stay separate. Daily workout calories are summed from unrounded
  children and rounded once; each displayed child is rounded independently.
- Temperature deviation rounds to two decimals. Workout distance is meters divided by 1,000, rounded to two
  decimals.
- No recovery score, calorie prescription, rolling baseline, or opaque traffic-light label is invented.

## Statuses (transformed collections and summary)

These statuses appear on `transformed` records, `audit_records`, and the `summary` date collections. Core
sections are `daily_sleep`, contributing `sleep`, `daily_readiness`, and `daily_activity`.

- `Complete` — all four core sections are usable.
- `Partial` — at least one core section is usable and at least one is missing.
- `Provisional` — the current Oura day, unless a core retrieval failure makes it unreliable.
- `No Data` — no usable core section on a finalized date; appears in audit records, never as a blank daily
  row.
- `Sync Error` — a core authentication, transport, or endpoint failure prevented reliable ingestion.

Supplemental stress, resilience, SpO2, workout, and session issues never downgrade a core-complete day; they
surface as warnings.

## `transformed.daily_records`

One scalar record per day with at least one usable core section, plus one for the current provisional day.

| Field | Meaning |
|---|---|
| `effective_date` | Oura `day` |
| `status` | Status above |
| `core_coverage` | Usable core count as `N/4` |
| `timezone_offset` | Primary sleep/timestamp source offset |
| `sleep_score`, `readiness_score`, `activity_score` | Oura daily scores |
| `sleep_duration_hours` | Contributing sleep seconds / 3600 |
| `sleep_duration_display` | Rounded minutes rendered `Xh Ym` |
| `primary_sleep_duration_hours` | Primary sleep seconds / 3600 |
| `nap_duration_minutes` | Summed `late_nap` seconds / 60 |
| `time_in_bed_hours` | Primary bedtime interval |
| `sleep_efficiency_percent` | Primary sleep efficiency |
| `steps` | Daily step count |
| `active_calories_kcal` | Daily active calories; context only |
| `lowest_sleep_heart_rate_bpm`, `average_hrv_ms` | Primary-sleep vitals |
| `temperature_deviation_celsius` | Readiness temperature deviation |
| `bedtime_local`, `wake_time_local` | Source-local `YYYY-MM-DD HH:MM` |
| `spo2_average_percent`, `breathing_disturbance_index` | Optional daily SpO2 |
| `stress_high_hours`, `recovery_high_hours`, `recovery_minus_stress_hours` | Daily stress summary in hours |
| `stress_summary` | Oura daily stress category |
| `resilience_level` | Optional Oura value |
| `workout_count`, `workout_duration_minutes`, `workout_calories_kcal` | Aggregates of the workout children |
| `workout_types` | Exact raw activities counted, e.g. `dance (2), walking (4)` |
| `workout_summary` | Labels counted; raw activities are never silently relabeled |
| `session_count` | Returned session child count |
| `sync_warnings` | Concise supplemental warning text |
| `retrieved_at_utc` | Retrieval timestamp for this record |
| `schema_version` | `2.0.0` |

## Child records

**`workout_records`** — keyed by `source_id` (the Oura workout ID). Fields: `effective_date`, `raw_activity`,
`mapped_category` (blank until a deterministic mapping is explicitly approved), `label`, `start_local`,
`end_local`, `duration_minutes`, `calories_kcal`, `distance_km`, `intensity`, `timezone_offset`,
`retrieved_at_utc`, `schema_version`.

**`session_records`** — keyed by `source_id` (the Oura session ID). Fields: `effective_date`, `session_type`,
`mood`, `start_local`, `end_local`, `duration_minutes`, `timezone_offset`, `retrieved_at_utc`,
`schema_version`.

## Audit and provenance records

**`audit_records`** — one per requested date and sync run. Each stores the core status, missing core
sections, supplemental warnings, sanitized errors and their retryability, source record counts,
`confirmed_no_data` and `unresolved` flags, timestamps, and a `raw_provenance_reference`. Confirmed no-data
and unresolved dates live here instead of becoming placeholder daily rows.

**`raw_provenance`** — one per requested date, with source IDs by endpoint, section coverage, sanitized
errors, and retrieval/API/server versions. Each audit record's `raw_provenance_reference` combines the API
version and the effective date, matching the provenance record for that date in the same response.
