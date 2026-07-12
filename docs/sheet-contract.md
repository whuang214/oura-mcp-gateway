# Dedicated Oura workbook contract

Contract version: `1.0.0`
Workbook marker: `OURA_DATA_WORKBOOK_V1`

This contract is a materialized consumer view of Oura Data API V1. It belongs
in a separate private Google workbook. It must never be created inside the
Master Nutrition workbook.

## Workbook identity and layout

Proposed workbook title: **Will’s Oura Recovery & Performance**.

Every tab uses:

- row 1 for the workbook marker, random workbook instance ID, contract version,
  and a human-readable title;
- row 2 for exact headers;
- row 3 onward for data;
- real Google Sheets date values such as `=DATE(2026,7,12)`;
- frozen headers, filters on visible tables, and stable key sorting.

The writer refuses all changes when:

- the configured spreadsheet ID is protected or unexpected;
- the workbook marker is absent;
- the workbook instance ID changes unexpectedly;
- a required tab or exact header is incompatible;
- the contract major version is not `1`.

The installed local configuration must hard-deny the Master Nutrition
spreadsheet ID. The dedicated workbook is private and has no link-sharing
requirement. Hidden/protected tabs improve usability but are not treated as a
security boundary.

## Tabs

1. `Daily Signals` — one row per canonical Oura day with usable data.
2. `Weekly Trends` — one coverage-aware row per calendar week.
3. `Events` — normalized workout/session summaries.
4. `_Sync Ledger` — hidden operational audit and retry state.

Raw provider payloads and dense time-series arrays are not copied into Sheets.
They remain available through granular API routes.

## Daily Signals

Key: `Date`.

```text
Date | Status | Core Coverage | Provisional |
Sleep Score | Sleep Hours | Sleep Display | Sleep Efficiency (%) |
Bedtime Local | Wake Time Local | Readiness Score | Activity Score |
Average HRV (ms) | Lowest Sleep HR (bpm) | Temperature Deviation (°C) |
Steps | Active Calories (kcal, context only) |
High Stress (hours) | High Recovery (hours) |
Recovery Minus Stress (hours) | Stress Summary |
SpO2 Average (%) | Breathing Disturbance Index |
Workout Count | Workout Minutes | Workout Types |
Sleep Baseline Median (hours) | Sleep Delta (hours) | Sleep Baseline N |
HRV Baseline Median (ms) | HRV Delta (%) | HRV Baseline N |
Lowest HR Baseline Median (bpm) | Lowest HR Delta (bpm) |
Lowest HR Baseline N | Baseline Status | Contributor Attention |
Warnings | Last Synced At (UTC) | API Version | Feature Version |
Contract Version
```

Rules:

- Emit a row only when at least one usable core source section exists, plus a
  current Provisional row when it contains usable source data.
- Do not emit a finalized placeholder row for a requested date with no usable
  Oura data. Record authoritative no-data coverage only in `_Sync Ledger`.
- `Core Coverage` is the usable core-section fraction. Core sections are daily
  sleep, contributing sleep periods, readiness, and activity.
- `Contributor Attention` is a stable comma-separated list of Oura contributor
  names below the API's documented attention threshold. It contains no prose.
- `Warnings` is concise structured text for supplemental unavailability. It
  cannot downgrade otherwise complete core data.
- Active calories are context only and must never be used as an eat-back or
  nutrition-target field.

## Baselines

Baseline values are calculated by the API feature engine, not by the Sheet
writer or web consumer.

- prior 28 calendar days only;
- median of valid observations;
- no future/look-ahead data;
- target day and Provisional observations excluded;
- no imputation or forward fill;
- `Sufficient`: 14 or more valid observations;
- `Developing`: 7–13 observations;
- `Unavailable`: fewer than 7 observations; delta fields remain blank.

A historical source correction may change features for the corrected date and
the following 28 days. The sync planner therefore refreshes that dependent
window.

## Weekly Trends

Key: `Week Start`.

```text
Week Start | Week End | Status | Expected Days | Usable Days |
Complete Days | Partial Days | Provisional Days | No Data Days |
Sync Error Days | Sleep Average (hours) | Sleep Median (hours) | Sleep N |
Readiness Median | Readiness N | HRV Median (ms) | HRV N |
Lowest HR Median (bpm) | Lowest HR N | Sleep Baseline Delta (hours) |
HRV Baseline Delta (%) | Lowest HR Baseline Delta (bpm) |
Steps Average | Steps N | High Stress Observed (hours) |
Stress Coverage Days | High Recovery Observed (hours) |
Recovery Coverage Days | Workout Count | Workout Minutes | Workout Types |
Contributor Attention Frequency | Warnings | Last Synced At (UTC) |
API Version | Feature Version | Contract Version
```

Rules:

- Aggregate only observed valid values and expose each denominator.
- Do not extrapolate a partial week to seven days.
- Stress/recovery totals are explicitly observed totals with coverage days.
- Do not include a weekly wearable-calorie total or net-calorie value.
- Refresh complete affected weeks when a daily source or feature changes.

## Events

Key: `Event Key`.

```text
Event Key | Event Type | Source ID | Date | Raw Activity or Session Type |
Label | Mood | Start Local | End Local | Duration (min) |
Workout Calories (kcal, context only) | Distance (km) | Intensity |
UTC Offset | Last Synced At (UTC) | API Version | Contract Version
```

Rules:

- `Event Key` is `workout:<source_id>` or `session:<source_id>`, preventing
  cross-resource ID collisions.
- Preserve Oura's raw activity/session label. Do not silently remap it.
- Session-only and workout-only fields remain blank when not applicable.
- Replace a date/resource partition only after that granular endpoint completed
  successfully. A successful empty partition deletes stale events; an error,
  disabled, absent, or not-granted partition preserves prior verified rows.
- Calories remain context only.

## _Sync Ledger

The tab is hidden and protected. It is not part of the normal coaching
contract. JSON is allowed here only for compact operational state.

Key: `Ledger Key`, derived from run ID, date/range, and resource.

```text
Ledger Key | Run ID | Requested Start | Requested End | Date | Resource |
Outcome | Record Count | Error Code | Error Message | Retryable |
Request ID | Response Hash | Provider API Revision | API Version |
Feature Version | Contract Version | Started At (UTC) | Completed At (UTC) |
Verified At (UTC) | Confirmed No Data | State JSON
```

Allowed `Outcome` values:

- `available`
- `empty`
- `not_granted`
- `disabled`
- `error`

The ledger stores finalized no-data and unresolved/retryable coverage so missing
dates are not fabricated in consumer tabs or endlessly rescanned. Errors and
request IDs are sanitized. Raw provider bodies, credentials, tokens, OAuth
codes, authorization headers, and stack traces are forbidden.

## Units and rounding

- Canonical API durations are seconds.
- Sheet hours are seconds divided by 3,600 and rounded half-up to two decimals.
- Sleep display rounds half-up to the nearest minute and renders `Xh Ym`.
- Event duration rounds half-up to a whole minute.
- Distance is meters divided by 1,000 and rounded half-up to two decimals.
- Temperature deviation is signed Celsius rounded to two decimals.
- Calories are displayed as half-up whole kcal and remain context only.
- Missing is blank. Zero is written only from an explicit source zero or a
  documented successful-empty aggregate.

The deterministic row renderer owns these conversions. The Sheet skill does
not reimplement provider calculations or AI inference.

## Reconciliation

- Upsert `Daily Signals` by Date, `Weekly Trends` by Week Start, and `Events` by
  Event Key.
- Treat each successfully retrieved date/resource partition as authoritative.
- A finalized successful no-data result removes a stale Daily Signals row and
  appears only in the ledger.
- A failed refresh never replaces a prior verified value with a blank.
- Sort every body by its stable key and reject duplicate keys.
- Write coherent bounded batches, then reread exact changed rows and headers.
- Compare values, keys, versions, null/zero behavior, and a deterministic
  response/body hash.
- Replay the identical batch once after an apparent partial write. If readback
  still differs, report the exact keys and do not advance verified state.
- Advance watermarks and `Verified At` only after validation succeeds.

## Sync windows

- Ordinary incremental sync: new dates, current retryable failures, and a
  three-day overlap.
- Historical backfill: explicit bounded ranges or an explicit lifetime run.
- Historical correction: corrected dates plus the following 28 days and all
  affected complete weeks.
- Current-day records remain Provisional and are refreshed until finalized.

## Consumer boundary

The web nutrition coach reads `Daily Signals` and `Weekly Trends` by default and
`Events` only when event details are relevant. It never reads `_Sync Ledger`
during ordinary coaching, never writes Oura data, and never creates
cross-workbook formulas. See [Web consumer handoff](web-consumer-handoff.md).
