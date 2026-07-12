# Oura Data API V1 — Web Nutrition Coach Handoff

Prepared: 2026-07-12
Audience: owner of the web `$will-nutrition-coach` skill

## Purpose

Update the web nutrition-coach skill to consume a compact Oura evidence contract
from a dedicated private Google workbook. Oura data is optional supporting
evidence for nutrition, recovery, and performance decisions. It is not the
nutrition system of record and must never block ordinary nutrition logging.

## Current state

- The Oura-owned tabs were removed from **Will’s Master Nutrition Log –
  Calories, Protein & Performance**.
- A separate private workbook named **Will’s Oura Recovery & Performance** now
  exists with the four exact tabs below and workbook contract `1.1.0`. Its ID
  belongs in private installed-skill configuration, never this public repo.
- The replacement `$oura-sync` skill and separate `oura-mcp` adapter are staged
  for final local validation and installed-skill cutover.
- **Oura Data API V1** is implemented and locally tested. Its public routes and
  schemas are V1; its private provider adapter uses the latest officially
  supported Oura upstream API.
- The web skill must not depend on desktop MCP or a localhost API that the web
  runtime cannot reach.

## Target architecture

```text
Oura Cloud
  -> self-hosted Oura Data API V1 (canonical JSON + deterministic analytics)
  -> separate read-only Oura MCP adapter
  -> desktop oura-sync skill (materialization only)
  -> private Oura Google workbook
  -> web will-nutrition-coach skill (read-only consumer)

Oura Data API V1
  -> separate MCP adapter for Codex/local MCP clients
```

The API owns Oura retrieval, typed normalization, units, coverage evaluation,
and deterministic features. The desktop sync skill owns only Sheet
materialization and readback validation. The web skill owns contextual
interpretation alongside nutrition and subjective data.

## Spreadsheet separation

### Master Nutrition Log

Keep as the source of truth for:

- food and nutrition logging;
- calorie and protein targets;
- body weight and goals;
- planned and completed training;
- subjective sleep/recovery notes;
- pain, soreness, illness, energy, and legs/jump feel;
- reflections and progress reviews.

Do not add Oura tabs, Oura formulas, `IMPORTRANGE`, or copied Oura rows back to
this workbook.

### Dedicated Oura workbook

Title: **Will’s Oura Recovery & Performance**.

The workbook ID is supplied privately to the installed web skill. Do not infer
it from titles or place it in public source. The accepted workbook contract is
`1.1.0`; the installed web skill should also receive the configured local
timezone (`America/Denver` for Will) and feature-logic version `1.0.0`.

The workbook contains four tabs:

1. **Daily Signals** — one row for each Oura day with usable source data.
2. **Weekly Trends** — one row per calendar week, with observed coverage counts.
3. **Events** — normalized workout and session summaries keyed by source ID.
4. **_Sync Ledger** — hidden operational audit data; not a coaching source.

Raw provider payloads and dense time-series arrays remain available through the
API and are not copied into the workbook.

## Consumer-facing contracts

### Daily Signals

Expected field groups:

- `Date`, `Status`, `Core Coverage`, `Provisional`;
- sleep score, sleep hours, sleep display, efficiency, bedtime, wake time;
- readiness and activity scores;
- average HRV, lowest sleeping heart rate, temperature deviation;
- high-stress hours, high-recovery hours, recovery-minus-stress;
- SpO2 and breathing-disturbance index when available;
- steps, workout count/minutes/types, workout calories marked context only,
  and session count/minutes/types;
- Oura contributor attention areas;
- past-only baseline medians, deltas, observation counts, and baseline state;
- structured warnings, last successful sync, API version, feature version, and
  API analytics/source contract version.

Active and workout calories, if materialized, must be explicitly labeled
**context only**. They are not nutrition expenditure targets.

Rows are omitted when no usable Oura source record exists. Missing values stay
blank/null; they are never converted to zero or filled forward.

### Weekly Trends

Expected fields:

- week start/end;
- expected days and usable observed days;
- Complete, Partial, Provisional, No Data, and Sync Error counts;
- sleep median/average plus observation count;
- readiness, HRV, and lowest-heart-rate medians plus observation counts;
- past-only baseline deltas;
- observed stress and recovery totals with coverage;
- observed steps and workout count/minutes/types;
- contributor attention frequency;
- last sync and contract versions.

Never extrapolate sparse weeks. Weekly No Data and Sync Error outcomes stay in
the hidden ledger and do not become consumer placeholders. Do not include a
weekly wearable-calorie target or net-calorie recommendation.

### Events

Use only when event detail is relevant. Expected key and fields:

- `Event Key` (`workout:<source_id>` or `session:<source_id>`);
- source ID, date, event kind, raw activity/session type, label or mood;
- start/end local time, duration minutes, intensity, distance;
- workout calories marked context-only;
- last sync and contract version.

### _Sync Ledger

The web nutrition coach must not read this tab during ordinary coaching. It is
reserved for troubleshooting stale data, sync failures, contract mismatches,
and retrieval coverage.

## Web skill read strategy

1. Complete normal nutrition writes and reads against the Master Nutrition Log
   whether or not Oura data is available.
2. Read Oura only when the user asks about sleep, stress, recovery, readiness,
   workout context, performance trends, or a progress review where it is
   materially relevant.
3. For a daily question, read the smallest bounded `Daily Signals` range that
   covers the requested dates and recent comparison window.
4. For weekly/progress-review questions, prefer `Weekly Trends`; use Daily
   Signals only to explain a specific week or anomaly.
5. Read `Events` only when a workout or session must be identified or explained.
6. Join Oura and nutrition/subjective data in memory on exact calendar `Date`.
   Do not create cross-workbook formulas or persist the joined result.
7. Validate the marker-row workbook contract and row-level API/feature/source
   versions before using Oura data. On an unknown version, ignore Oura, report
   the incompatibility, and continue the nutrition task normally.

## Baseline contract

Prefer the deterministic baseline fields supplied by the API and workbook. Do
not silently implement a second trend engine in the web skill.

- Use the prior 28 calendar days only; never look ahead.
- Use medians for daily baseline comparisons.
- Exclude the target day and Provisional observations.
- Expose the valid observation count.
- `Sufficient`: at least 14 valid observations.
- `Developing`: 7–13 valid observations.
- `Unavailable`: fewer than 7; suppress delta claims.
- Weekly values are observed values with coverage counts, never seven-day
  extrapolations from a sparse week.

## Interpretation order

Structure Oura-assisted reasoning as:

1. Observed device facts.
2. Deterministic comparisons and coverage/sample counts.
3. Subjective context from the nutrition log or user.
4. Interpretation and conflicts.
5. Confidence and reasons.
6. Conservative actions or questions.

Do not persist AI prose, inferred diagnoses, or coaching conclusions into the
Oura workbook.

Use this evidence priority when sources disagree:

1. Subjective pain, soreness, illness, energy, legs, and jump feel.
2. Explicit training and performance observations.
3. Nutrition, target, weight, and goal records.
4. Curated Oura signals and deterministic comparisons.
5. Supplemental Oura details such as workouts, sessions, SpO2, stress, or
   resilience.

## Non-negotiable safety rules

- Missing Oura data is never zero and never evidence of poor recovery.
- Current-day data marked Provisional is not final.
- Partial or sparse coverage lowers confidence; expose the observation count.
- Stale data must be labeled stale rather than presented as current.
- Subjective pain, soreness, illness, unusual fatigue, poor energy, or poor
  jump/leg feel overrides favorable device scores.
- Active calories and workout calories are not automatically eaten back.
- Wearable calorie estimates cannot directly set or rewrite nutrition targets.
- Do not invent a new readiness, recovery, strain, or health score.
- Do not diagnose medical conditions from wearable data.
- A missing, inaccessible, stale, or incompatible Oura workbook must never
  block food logging, target lookup, weigh-ins, goals, or reflections.

## Required web-skill changes

- Add a non-secret configuration reference for the dedicated Oura spreadsheet
  ID, exact allowed tab names, and accepted contract version.
- Remove references to Oura tabs inside the Master Nutrition Log.
- Add the conditional read strategy above instead of loading Oura for every
  nutrition interaction.
- Add exact-date join and bounded-read instructions.
- Add explicit status, freshness, missing-data, and subjective-override rules.
- Add calorie-safety language and prohibit automatic target changes.
- Add a concise user-facing explanation for missing/stale/incompatible Oura.
- Keep troubleshooting reads of `_Sync Ledger` outside ordinary coaching.

## Acceptance scenarios

The updated web skill must behave correctly when:

1. The Oura workbook is missing or inaccessible.
2. The requested date has no Oura row.
3. A value is null while another value is an explicit zero.
4. The current date is Provisional.
5. Core coverage is Partial or a supplemental endpoint failed.
6. The last sync is stale.
7. The Sheet contract version is unknown.
8. Oura scores are favorable but subjective pain, illness, soreness, energy, or
   jump feel is adverse.
9. A sparse week has too few observations for a baseline delta.
10. Active/workout calorie values are present.
11. The user performs ordinary food logging with no Oura data at all.

## Inputs the web agent must receive after implementation

- Dedicated Oura spreadsheet URL and ID.
- Final exact tab names and headers.
- Workbook marker/layout contract, row-level API/feature/source versions, and
  compatibility rules.
- Freshness/staleness threshold.
- Example sanitized Daily Signals, Weekly Trends, and Events rows.
- Verification report for the staged lifetime backfill.

Do not finalize or publish the web-skill update using guessed values for these
inputs.
