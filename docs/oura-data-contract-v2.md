# Oura analysis contract v2

Schema version: `2.0.0`

This is the versioned transformation contract between the desktop Oura gateway,
the desktop `oura-sync` writer, and the read-only web Nutrition Coach consumer.
The gateway remains a thin Oura-only MCP server; Google mutation stays in the
desktop skill.

## Verified Oura facts

- Oura API V2 is the current integration surface.
- `day` is the canonical calendar attribution for daily and event records.
- Timestamps are ISO 8601 values with offsets; a missing source offset is not
  replaced with `+00:00`.
- Scores are 0–100 aggregates and durations are seconds unless an endpoint says
  otherwise.
- Sleep/readiness require a user sync, while activity and stress can update in
  the background. Current-day records can therefore be incomplete.
- `daily` covers sleep, readiness, and activity summaries; `workout`, `session`,
  and daily SpO2 use separate consent scopes.
- The OpenAPI schema exposes daily resilience but documents no separate OAuth
  scope for it. This installation receives a persistent denial, so resilience
  retrieval is disabled by default and treated as an optional availability
  warning.
- Oura documents pagination with `next_token`, date-range queries, and gaps when
  a user does not wear or sync the ring. It does not publish one universal
  historical-retention guarantee, so synchronized source evidence is retained.

Official references:

- https://cloud.ouraring.com/v2/docs
- https://cloud.ouraring.com/v2/static/json/openapi-1.35.json
- https://cloud.ouraring.com/docs/authentication
- https://cloud.ouraring.com/docs/error-handling

## Transformation rules

- Missing remains null/blank. Zero is emitted only from an explicit source zero
  or a successfully empty child endpoint.
- Hours are rounded to two decimals. Display sleep duration rounds total seconds
  to the nearest minute using half-up rounding, then renders `Xh Ym`.
- Each workout/session duration is rounded half-up from source seconds to an
  integer minute. Daily workout duration is the sum of those displayed child
  minutes so the child table and daily aggregate agree exactly. If any
  contributing duration is unknown, the aggregate is null.
- Daily active calories and workout calories remain separate. Display calories
  use half-up integer rounding. Daily workout calories are summed from
  unrounded normalized children and rounded once; each displayed child is
  rounded independently. Source precision remains in the normalized MCP
  response and in the unchanged legacy/raw source during staging, while the
  provenance tab retains stable source IDs.
- Temperature deviation is rounded to two decimals. Workout distance is meters
  divided by 1000 and rounded to two decimals.
- No recovery score, calorie prescription, rolling baseline, or opaque
  traffic-light label is invented.

## Consumer status

Core sections are `daily_sleep`, contributing `sleep`, `daily_readiness`, and
`daily_activity`.

- `Complete`: all four core sections are usable.
- `Partial`: at least one core section is usable and at least one is missing.
- `Provisional`: the current Oura day, unless a core retrieval failure makes it
  unreliable.
- `No Data`: no usable core section on a finalized historical date. This appears
  in audit storage, not as a blank curated daily row.
- `Sync Error`: a core authentication, transport, or endpoint failure prevented
  reliable ingestion.

Supplemental stress, resilience, SpO2, workouts, and sessions never downgrade a
core-complete day. Their failures are warnings.

## `Oura Daily Metrics v2`

One scalar row is written when at least one core section exists, plus one
temporary row for the current provisional day. No JSON or source UUIDs appear.

| Column | Source / calculation |
|---|---|
| Date | Oura `day`; Sheet `=DATE(y,m,d)` |
| Status | Consumer status above |
| Core Coverage | Available core count as `N/4` |
| UTC Offset | Primary sleep/timestamp source offset only |
| Sleep Score | `daily_sleep.score` |
| Sleep Duration (hours) | contributing sleep seconds / 3600 |
| Sleep Duration (display) | rounded minutes rendered `Xh Ym` |
| Primary Sleep (hours) | primary sleep seconds / 3600 |
| Nap Duration (min) | summed `late_nap` seconds / 60 |
| Time in Bed (hours) | primary bedtime interval |
| Sleep Efficiency (%) | primary sleep efficiency |
| Readiness Score | `daily_readiness.score` |
| Activity Score | `daily_activity.score` |
| Steps | `daily_activity.steps` |
| Active Calories (kcal) | daily activity active calories; context only |
| Lowest Sleep Heart Rate (bpm) | primary sleep lowest HR |
| Average HRV (ms) | primary sleep average HRV |
| Temperature Deviation (°C) | readiness deviation |
| Bedtime Local | source-local `YYYY-MM-DD HH:MM` |
| Wake Time Local | source-local `YYYY-MM-DD HH:MM` |
| SpO2 Average (%) | daily SpO2 average |
| Breathing Disturbance Index | daily SpO2 BDI |
| High Stress (hours) | stress seconds / 3600 |
| High Recovery (hours) | recovery seconds / 3600 |
| Recovery Minus Stress (hours) | recovery hours minus stress hours |
| Stress Summary | Oura daily stress category |
| Resilience Level | optional Oura value when available |
| Workout Count | returned workout child count; zero only on successful empty |
| Workout Duration (min) | sum of known child durations |
| Workout Calories (kcal) | sum of known child calories, kept separate from active calories |
| Workout Types | exact raw activities counted, e.g. `dance (2), walking (4)` |
| Workout Summary | labels counted; raw activities are never silently relabeled |
| Session Count | returned session child count |
| Sync Warnings | concise supplemental warning text |
| Last Synced At (UTC) | gateway retrieval timestamp used for this synchronized row |
| Schema Version | `2.0.0` |

## Child and audit tables

### `Oura Workouts v2`

Key: `Oura Workout ID`. Columns: ID, Date, Raw Activity, Mapped Category,
Label, Start Local, End Local, Duration (min), Calories (kcal), Distance (km),
Intensity, UTC Offset, Last Synced At (UTC), Schema Version. `Mapped Category`
stays blank until a deterministic mapping is explicitly approved.

### `Oura Sessions v2`

Key: `Oura Session ID`. Columns: ID, Date, Session Type, Mood, Start Local,
End Local, Duration (min), UTC Offset, Last Synced At (UTC), Schema Version.

### `Oura Sync Audit v2`

One row per requested date and sync run. It stores core status, missing core
sections, supplemental warnings, sanitized errors, retryability, source record
counts, timestamps, and a provenance reference. Confirmed no-data and unresolved
dates live here instead of becoming curated placeholders.

A hidden state cell stores scanned ranges, finalized no-core dates, unresolved
dates, and the last
verified sync timestamp. It is committed only after write readback succeeds.

### `Oura Raw Provenance v2`

One row per sync run plus requested date with source IDs, section coverage,
sanitized errors, retrieval/API/server versions, and schema version. JSON is allowed here because
this is audit storage, not a consumer table. The current Sheet implementation
persists durable source IDs and retrieval metadata rather than duplicating every
health payload; the normalized MCP response and preserved legacy tab remain the
raw-value comparison sources during staging.

Audit references use the same sync-run ID plus date key, so a later sync cannot
overwrite evidence referenced by an older audit row.

For displayed workout-calorie reconciliation, round the unrounded daily child
sum once and allow at most `0.5 × child count + 0.5 kcal` difference from the
sum of individually rounded child rows. Counts and displayed duration minutes
must match exactly.

## Web Nutrition Coach rules

- Read `Oura Daily Metrics` after approved cutover; during staging use
  `Oura Daily Metrics v2` only for validation.
- Treat Oura as supporting evidence. Missing/stale data never blocks nutrition
  logging or `close_day`.
- Never automatically eat back active or workout calories and never derive a
  target solely from wearable energy estimates.
- Subjective pain, soreness, illness, energy, and jump feel override device
  scores.
- Join detailed workouts by Date only when event detail is needed; preserve the
  raw Oura activity label.
