# Oura Sheet Contract v2

Read before every Oura workbook inspection or write. Schema version is `2.0.0`.

## Shared layout

- Row 1: title. It may remain unmerged when frozen columns would make a merge
  invalid.
- Row 2: exact headers.
- Row 3 onward: data.
- Use real `=DATE(y,m,d)` values for every Date cell.
- Resolve every live `sheetId`; never hardcode numeric IDs.

## `Oura Daily Metrics v2`

One scalar row per day with at least one core section, plus the current
provisional day. No JSON or source IDs.

```text
Date | Status | Core Coverage | UTC Offset | Sleep Score |
Sleep Duration (hours) | Sleep Duration (display) |
Primary Sleep (hours) | Nap Duration (min) | Time in Bed (hours) |
Sleep Efficiency (%) | Readiness Score | Activity Score | Steps |
Active Calories (kcal) | Lowest Sleep Heart Rate (bpm) |
Average HRV (ms) | Temperature Deviation (°C) | Bedtime Local |
Wake Time Local | SpO2 Average (%) | Breathing Disturbance Index |
High Stress (hours) | High Recovery (hours) |
Recovery Minus Stress (hours) | Stress Summary | Resilience Level |
Workout Count | Workout Duration (min) | Workout Calories (kcal) |
Workout Types | Workout Summary | Session Count | Sync Warnings |
Last Synced At (UTC) | Schema Version
```

Core sections are `daily_sleep`, contributing `sleep`, `daily_readiness`, and
`daily_activity`.

- `Complete`: all four core sections usable.
- `Partial`: at least one core usable and at least one missing.
- `Provisional`: current Oura day unless core retrieval failed.
- `No Data`: no usable historical core data; audit only, not a daily row.
- `Sync Error`: a core auth/transport/retrieval failure prevented reliability.

Stress, resilience, SpO2, workouts, and sessions are supplemental. Their errors
are warnings and cannot downgrade `Complete`.

## `Oura Workouts v2`

Key: `Oura Workout ID`.

```text
Oura Workout ID | Date | Raw Activity | Mapped Category | Label |
Start Local | End Local | Duration (min) | Calories (kcal) |
Distance (km) | Intensity | UTC Offset | Last Synced At (UTC) |
Schema Version
```

Preserve Raw Activity exactly. Keep Mapped Category blank unless a documented
mapping is explicitly approved.

## `Oura Sessions v2`

Key: `Oura Session ID`.

```text
Oura Session ID | Date | Session Type | Mood | Start Local | End Local |
Duration (min) | UTC Offset | Last Synced At (UTC) | Schema Version
```

## `Oura Sync Audit v2`

Key: `Sync Run ID` plus `Date`.

```text
Sync Run ID | Requested Start | Requested End | Date | Core Status |
Missing Core Sections | Optional Warnings | Error Code | Error Message |
Retryable | Retrieved At (UTC) | Last Synced At (UTC) | API Version |
Source Record Counts (JSON) | Raw Provenance Reference |
Confirmed No Data | Unresolved | Schema Version
```

JSON is permitted in audit/provenance, never in the curated daily table.
Reserve hidden cells `T1:T2` for `Oura Sync State` and compact state JSON:

```json
{"schema_version":"2.0.0","scanned_ranges":[],"confirmed_no_data_dates":[],"unresolved_dates":[],"last_verified_sync_at":null}
```

Update state only after full write/readback validation succeeds.

## `Oura Raw Provenance v2`

Key: `Sync Run ID` plus `Date`. Each sync retains an immutable provenance
snapshot so older audit rows never point at overwritten evidence.

```text
Sync Run ID | Date | Oura Source IDs (JSON) | Section Coverage (JSON) |
Section Errors (JSON) | Retrieved At (UTC) | API Version |
Server Version | Schema Version
```

## Units and nulls

- Hours: seconds / 3600, rounded to 2 decimals.
- Sleep display: seconds rounded half-up to a minute, rendered `Xh Ym`.
- Child duration: source interval rounded half-up to an integer minute; daily
  total is the sum of known child durations.
- Calories: half-up integer display. Active and workout calories are separate.
  The daily workout total rounds the unrounded child sum once; child rows round
  independently. Their displayed-sum tolerance is
  `0.5 × child count + 0.5 kcal`.
- Distance: meters / 1000, rounded to 2 decimals.
- Temperature deviation: signed, 2 decimals.
- Missing is blank. Zero is valid only from a source zero or successful empty
  endpoint.
- Use Oura `day` for Date. Local timestamp strings preserve the source wall time,
  and UTC Offset is blank when no source timestamp supports one.

## Reconciliation and validation

- Upsert daily by Date, provenance by Sync Run ID plus Date, and children by
  source ID.
- For a successfully resolved daily date, replace that date's daily partition;
  an audit-only `No Data` result therefore removes a stale Provisional row.
- For workouts/sessions, replace a date partition only when provenance coverage
  for that section is `available` or `empty`. An empty successful partition
  deletes stale children; an error/missing/disabled partition preserves them.
- On a failed section, preserve blanks only in that section's columns:
  `daily_sleep` → Sleep Score; `sleep` → sleep duration/display/primary/nap/time
  in bed/efficiency/HR/HRV/bedtime/wake/offset; `daily_readiness` → readiness and
  temperature; `daily_activity` → activity/steps/active calories;
  `daily_stress` → stress/recovery fields; `daily_resilience` → resilience;
  `daily_spo2` → SpO2/BDI; `workout` → workout aggregates; `session` → session
  count. Never preserve unrelated blanks.
- Ordinary sync uses scan state, newer dates, retryable failures, and a three-day
  overlap. Historical absent dates require explicit backfill.
- Pass hidden confirmed-no-data dates to the MCP planning input with status
  `No Data`; this is covered state and is not a retry signal.
- Pass hidden unresolved dates and latest structured audit errors too. Any
  retryable error is a retry signal even when core status is Complete.
- Preserve an existing real row if a failed refresh returns no replacement.
- Validate unique/sorted keys, exact headers, allowed statuses, schema version,
  date formulas, null/zero behavior, and child-to-daily aggregates.
- `Workout Count`, duration, and calories must match `Oura Workouts v2` for the
  same date within documented rounding.
- A staging run must not modify the final legacy tab or any non-Oura tab.
