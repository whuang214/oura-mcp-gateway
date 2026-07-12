# Oura upstream resource map

Last verified: July 12, 2026

Official provider API: Oura API V2

Linked provider schema: OpenAPI revision 1.35

This is an internal provider-reference document. It does not version the public
project API, which remains Oura Data API V1.

Authoritative references:

- [Oura API documentation](https://cloud.ouraring.com/v2/docs)
- [Oura OpenAPI 1.35](https://cloud.ouraring.com/v2/static/json/openapi-1.35.json)
- [Oura authentication](https://cloud.ouraring.com/docs/authentication)
- [Oura error handling](https://cloud.ouraring.com/docs/error-handling)

Context7 can supplement field explanations but is not authoritative for the
route inventory. Its Oura corpus produced incomplete and occasionally shortened
paths during this audit.

## Production resources

| Canonical resource | Official provider collection path | Filters | Single document |
| --- | --- | --- | --- |
| profile | `/v2/usercollection/personal_info` | none | no separate ID route |
| daily activity | `/v2/usercollection/daily_activity` | date range, token, fields | `/{document_id}` |
| cardiovascular age | `/v2/usercollection/daily_cardiovascular_age` | date range, token, fields | `/{document_id}` |
| daily readiness | `/v2/usercollection/daily_readiness` | date range, token, fields | `/{document_id}` |
| daily resilience | `/v2/usercollection/daily_resilience` | date range, token; fields ignored | `/{document_id}` |
| daily sleep | `/v2/usercollection/daily_sleep` | date range, token, fields | `/{document_id}` |
| daily SpO2 | `/v2/usercollection/daily_spo2` | date range, token, fields | `/{document_id}` |
| daily stress | `/v2/usercollection/daily_stress` | date range, token, fields | `/{document_id}` |
| enhanced tags | `/v2/usercollection/enhanced_tag` | date range, token; fields ignored | `/{document_id}` |
| heart rate | `/v2/usercollection/heartrate` | datetime range or latest, token, fields | none |
| rest mode | `/v2/usercollection/rest_mode_period` | date range, token, fields | `/{document_id}` |
| ring battery | `/v2/usercollection/ring_battery_level` | datetime range or latest, token, fields | none |
| ring configuration | `/v2/usercollection/ring_configuration` | token, fields | `/{document_id}` |
| sessions | `/v2/usercollection/session` | date range, token, fields | `/{document_id}` |
| detailed sleep | `/v2/usercollection/sleep` | date range, token, fields | `/{document_id}` |
| sleep time | `/v2/usercollection/sleep_time` | date range, token, fields | `/{document_id}` |
| legacy tags | `/v2/usercollection/tag` | date range, token; fields ignored | `/{document_id}` |
| VO2 max | `/v2/usercollection/vO2_max` | date range, token, fields | `/{document_id}` |
| workouts | `/v2/usercollection/workout` | date range, token, fields | `/{document_id}` |

The provider path `vO2_max` has unusual case and must be preserved exactly in
the adapter. Sandbox duplicates and webhook-subscription administration are not
part of the initial public data API.

## Filter semantics

- Document collections use `start_date`, `end_date`, and `next_token`.
- Provider date filters accept date or datetime strings, but the public V1 API
  exposes strict ISO dates for document collections.
- Heart rate and ring battery use `start_datetime`, `end_datetime`,
  `next_token`, and `latest`.
- `fields` is a provider optimization only. Public V1 schemas are fixed and do
  not pass through arbitrary field selections.
- Provider `next_token` values remain private and are wrapped in tamper-evident
  project cursors.
- Collection responses use `{ "data": [...], "next_token": ... }`.
- Provider timestamps are ISO 8601. Source `day` remains the canonical daily
  attribution.

## Scope and capability caveat

The linked OpenAPI/authentication documents list these traditional scope names:

- `email`
- `personal`
- `daily`
- `heartrate`
- `workout`
- `tag`
- `session`
- `spo2Daily`, with `spo2` accepted as a known alias

The current developer portal displays additional permission categories, while
the OpenAPI operations do not encode reliable endpoint-specific scope arrays
for newer resources. The adapter must not guess raw scope strings for stress,
resilience, heart health, ring configuration/battery, or rest mode.

Known safe mappings:

- `daily`: daily activity/readiness/sleep, detailed sleep, sleep time;
- `heartrate`: heart-rate time series;
- `workout`: workouts;
- `session`: sessions;
- `tag`: enhanced and deprecated legacy tags;
- `spo2Daily`/`spo2`: daily SpO2;
- `email`: profile email;
- `personal`: profile demographic/body fields.

Every public capability therefore has independent configured, authorization,
availability, maturity, reason, and retryability state. A provider `403` is
ambiguous: it may indicate missing permission or unavailable membership. Report
`not_granted` only when the stored grant proves that fact; otherwise report a
sanitized provider-forbidden state.

## Resource field summary

### Daily activity

Score, six contributors, active/total/target kcal, steps, activity/rest/
sedentary/non-wear seconds, MET-minute totals, distances/targets in meters,
inactivity alerts, and dense MET/classification series.

### Daily readiness

Score, nine contributor values, temperature deviation, temperature-trend
deviation, day, and timestamp.

### Daily sleep and detailed sleep

Daily sleep provides the score and seven contributors. Detailed sleep provides
period type, bedtime/wake timestamps, total/deep/light/REM/awake/time-in-bed/
latency seconds, efficiency, breathing rate, average/lowest heart rate, average
HRV, restlessness, readiness details, and dense heart-rate/HRV/movement/stage
samples. Multiple detailed periods may share one day.

The provider marks `app_sleep_phase_5_min` for future removal. Do not put it in
the stable public projection.

### Stress and resilience

Daily stress contains `stress_high` and `recovery_high` seconds plus a
restored/normal/stressful summary. The official provider exposes no continuous
daytime-stress route. Resilience contains a categorical level and sleep
recovery/daytime recovery/stress contributors, but is experimental locally
because account availability is inconsistent.

### SpO2 and heart health

Daily SpO2 contains average percentage and breathing-disturbance index.
Cardiovascular age contains vascular age and pulse-wave velocity. VO2 max
contains the Oura estimate, day, and timestamp.

### Workouts and sessions

Workouts contain activity, label, localized start/end, intensity, source,
optional kcal, and optional distance meters. The public provider schema does
not include workout heart-rate samples. Sessions contain type, mood,
start/end, and optional sampled heart-rate, HRV, and motion arrays.

### Tags, rest mode, and sleep time

Enhanced tags contain a type code, custom name/comment, and start/end day/time.
Legacy tags are deprecated. Rest-mode periods contain start/end day/time and
tagged episodes. Sleep-time documents contain an optimal-bedtime window,
recommendation, and status.

### Heart rate, rings, and battery

Heart rate provides timestamped BPM and source, commonly at five-minute
increments. Ring configuration provides color, design, firmware, hardware type,
size, setup timestamp, and ID. Ring battery provides timestamped level percent,
charging, and in-charger state.

## Intentionally unsupported in stable V1

- Interbeat intervals until they appear in the linked official schema.
- Continuous temperature.
- Continuous daytime-stress samples.
- Menstrual/cycle data.
- Sleep debt.
- Workout heart-rate samples.
- Any private/app-only route not documented in the official provider contract.

Adding a provider resource requires official-source verification, typed DTOs,
canonical mapping, capability policy, fixture coverage, public-contract review,
and secret-safe error tests.
