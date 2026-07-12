# API V1 contract

Contract version: `1.0.0`
Provider reference: latest supported Oura API, verified against Oura OpenAPI
revision 1.35 on July 12, 2026.

This document defines the public JSON contract for this project. The project
API is V1 and uses the `/api/v1` prefix. Oura's provider API version is an
internal adapter concern and does not version this contract.

## Contract principles

- Data routes are read-only and return JSON.
- Every collection requires explicit date or datetime bounds.
- Oura's returned `day` is the canonical date; never derive it from UTC.
- Missing data remains absent or null. An explicit source zero remains zero.
- Collection success with no records returns `data: []`; it never fabricates a
  row for each requested date.
- Dense source arrays are excluded from default summaries and exposed through
  explicit sample subresources.
- Durations, distances, temperatures, heart rates, and calories use unit-bearing
  field names.
- Pagination uses an opaque API cursor. Provider `next_token` values are never
  exposed.
- Active and workout calories are distinct context fields. The API never
  calculates an eat-back amount or nutrition target.
- Deterministic analytics are separate from source-resource routes. The API
  does not generate AI prose or medical conclusions.

## Authentication

Oura OAuth credentials and tokens remain server-side. Callers authenticate to
the local API with a separate bearer token.

- `GET /api/v1/health` is an unprotected liveness check with no configuration
  or credential details.
- Every other `/api/v1` route requires the gateway bearer token unless an OAuth
  callback route explicitly documents otherwise.
- Default binding is loopback. A non-loopback binding requires explicit opt-in,
  gateway authentication, and HTTPS at the deployment boundary.

## Common success envelope

Single-resource routes place an object in `data`; collection routes place an
array in `data`.

```json
{
  "data": [],
  "meta": {
    "api_version": "1",
    "schema_version": "1.0.0",
    "request_id": "01J...",
    "source": {
      "provider": "oura",
      "provider_api_version": "2",
      "provider_schema_revision": "1.35"
    },
    "range": {
      "start_date": "2026-07-01",
      "end_date": "2026-07-11"
    },
    "next_cursor": null,
    "retrieved_at": "2026-07-12T18:00:00Z",
    "freshness": {
      "source": "live",
      "fetched_at": "2026-07-12T18:00:00Z",
      "stale": false
    },
    "warnings": []
  }
}
```

`meta` may add non-breaking fields during V1. Existing fields do not change
meaning within the V1 major contract.

## Collection query rules

Date-keyed collections accept:

- `start_date`: required ISO `YYYY-MM-DD`, inclusive;
- `end_date`: required ISO `YYYY-MM-DD`, inclusive;
- `limit`: optional bounded page size;
- `cursor`: optional opaque continuation cursor.

Time-series collections accept:

- `start_datetime`: required RFC 3339 timestamp with an offset;
- `end_datetime`: required RFC 3339 timestamp with an offset;
- `limit`: optional bounded page size;
- `cursor`: optional opaque continuation cursor.

Date collections allow at most 90 inclusive days. Time-series ranges allow at
most seven days and use a half-open interval. The server rejects future dates,
reversed or excessive ranges, invalid offsets, unknown parameters, and cursors
issued for a different route or query.

## Meta and authorization routes

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Bare liveness; no private diagnostics |
| `GET` | `/api/v1/health/challenge` | Nonce/HMAC proof of the configured local gateway identity |
| `GET` | `/api/v1/status` | Sanitized configuration, authorization, process identity, and freshness state |
| `GET` | `/api/v1/capabilities` | Resources and their enabled/granted/available state |
| `GET` | `/api/v1/profile` | Scope-controlled personal profile; opt-in because it is PII |
| `POST` | `/api/v1/auth/authorizations` | Create a state-bound Oura authorization URL |
| `GET` | `/api/v1/auth/callback` | Validate the browser callback and persist rotating tokens |
| `GET` | `/api/v1/auth/connection` | Sanitized Oura connection status |
| `DELETE` | `/api/v1/auth/connection` | Revoke/delete the local Oura connection |

The existing local OAuth CLI may remain as a convenience wrapper around the
same application service. It does not define a second token implementation.

## Stable daily routes

Each collection route supports the date query rules above. Each
`/{source_id}` route returns one Oura source document or `404` when it does not
exist. To retrieve one calendar date, set `start_date` equal to `end_date`; use
`/api/v1/days/{day}` for the ergonomic composite-day route.

| Collection | Single source document | Content |
| --- | --- | --- |
| `/api/v1/daily/activity` | `/api/v1/daily/activity/{source_id}` | Activity score, contributors, steps, activity/rest/non-wear durations, MET-minute totals, distances, and context-only calories |
| `/api/v1/daily/readiness` | `/api/v1/daily/readiness/{source_id}` | Readiness score, contributors, and temperature deviation/trend |
| `/api/v1/daily/sleep` | `/api/v1/daily/sleep/{source_id}` | Daily sleep score and contributors |
| `/api/v1/daily/stress` | `/api/v1/daily/stress/{source_id}` | High-stress/high-recovery seconds and Oura day summary |
| `/api/v1/daily/spo2` | `/api/v1/daily/spo2/{source_id}` | Average SpO2 and breathing-disturbance index when supported |
| `/api/v1/daily/cardiovascular-age` | `/api/v1/daily/cardiovascular-age/{source_id}` | Vascular age and pulse-wave velocity when available |

## Stable detailed and event routes

| Collection | Single document | Content |
| --- | --- | --- |
| `/api/v1/sleep-periods` | `/api/v1/sleep-periods/{source_id}` | Individual long sleep, nap, rest, and deleted-source periods with duration and summary vitals |
| `/api/v1/sleep-times` | `/api/v1/sleep-times/{source_id}` | Oura optimal-bedtime recommendation and status |
| `/api/v1/workouts` | `/api/v1/workouts/{source_id}` | Oura workout summaries; no invented workout-heart-rate payload |
| `/api/v1/sessions` | `/api/v1/sessions/{source_id}` | Guided/unguided session summary |
| `/api/v1/enhanced-tags` | `/api/v1/enhanced-tags/{source_id}` | Current Oura tag model and user comments |
| `/api/v1/rest-mode-periods` | `/api/v1/rest-mode-periods/{source_id}` | Rest-mode ranges and tagged episodes |
| `/api/v1/rings` | `/api/v1/rings/{source_id}` | Ring hardware, firmware, size, design, and setup metadata |
| `/api/v1/vo2-max` | `/api/v1/vo2-max/{source_id}` | Oura VO2 max estimate |

Time-series routes:

- `GET /api/v1/heart-rate`
- `GET /api/v1/ring-battery`

These use datetime bounds and return timestamped samples.

## Dense sample subresources

Default sleep/session/activity records contain no large sample arrays. Callers
request them explicitly:

- `GET /api/v1/sleep-periods/{source_id}/samples/heart-rate`
- `GET /api/v1/sleep-periods/{source_id}/samples/hrv`
- `GET /api/v1/sleep-periods/{source_id}/samples/movement`
- `GET /api/v1/sleep-periods/{source_id}/samples/stages`
- `GET /api/v1/sessions/{source_id}/samples/heart-rate`
- `GET /api/v1/sessions/{source_id}/samples/hrv`
- `GET /api/v1/sessions/{source_id}/samples/motion`
- `GET /api/v1/daily/activity/{source_id}/samples/met`
- `GET /api/v1/daily/activity/{source_id}/samples/classification`

Sample responses preserve timestamps, intervals, null samples, and source units.
They are independently bounded and paginated.

## Experimental and excluded provider resources

Experimental routes are not part of the stable V1 compatibility promise:

- `GET /api/v1/experimental/daily/resilience`
- `GET /api/v1/experimental/daily/resilience/{source_id}`
- `GET /api/v1/experimental/legacy-tags`
- `GET /api/v1/experimental/legacy-tags/{source_id}`

Resilience is documented upstream but capability/scoping is inconsistent across
accounts. Legacy tags remain documented but are explicitly deprecated in favor
of enhanced tags. Both require explicit enablement and capability reporting.

The deprecated provider `tag` route is not exposed in stable V1; use enhanced
tags. Sandbox routes and webhook administration are not user-data routes and
are excluded. Interbeat intervals and app-only metrics absent from the linked
official provider contract are not promised in V1, including menstrual/cycle
data, continuous temperature, continuous daytime stress, sleep debt, or
workout heart rate.

## Curated convenience routes

| Route | Purpose |
| --- | --- |
| `GET /api/v1/days` | Bounded composite days with requested sections and explicit per-section coverage |
| `GET /api/v1/days/{day}` | One composite canonical day |
| `GET /api/v1/analytics/daily-signals` | Deterministic daily facts plus prior-only baseline features |
| `GET /api/v1/analytics/daily-coverage` | Audit-only status row for every requested day, including No Data and Sync Error |
| `GET /api/v1/analytics/daily-signals/{day}` | One deterministic daily signal record |
| `GET /api/v1/analytics/weekly-trends` | Coverage-aware observed weekly summaries |

`/days` accepts an `include` allowlist. A failed supplemental section produces
a structured warning while usable sections remain available. A direct request
to an unavailable or ungranted granular resource returns a normal error.

Analytics rules:

- prior 28 calendar days only;
- median baselines and no look-ahead;
- target/current Provisional day excluded from its baseline;
- sample count exposed;
- `Sufficient` at 14 or more observations;
- `Developing` at 7–13 observations;
- `Unavailable` below 7, with delta claims suppressed;
- weekly values are observed with coverage counts, never extrapolated.

## Coverage vocabulary

Every requested section resolves to one of:

- `available`: at least one usable source record;
- `empty`: successful authoritative response with no records;
- `not_granted`: the user did not grant the required capability;
- `disabled`: local policy disabled an experimental/optional resource;
- `error`: authentication, transport, provider, timeout, or validation failure.

Composite daily core statuses are:

- `Complete`: sleep summary, contributing sleep periods, readiness, and
  activity are usable;
- `Partial`: at least one core domain is usable and another is missing;
- `Provisional`: current Oura day may still change;
- `No Data`: finalized requested date has no usable core data; reported in
  coverage/audit, not fabricated as a daily record;
- `Sync Error`: reliable core retrieval failed.

Stress, SpO2, workouts, sessions, resilience, and other supplemental resources
do not downgrade otherwise complete core data.

## Problem response

Errors use `application/problem+json` and RFC 9457-compatible fields:

```json
{
  "type": "https://example.invalid/problems/oura-scope-not-granted",
  "title": "Oura capability not granted",
  "status": 403,
  "detail": "The requested Oura resource is not available to this connection.",
  "instance": "/api/v1/daily/spo2",
  "code": "oura_scope_not_granted",
  "request_id": "01J...",
  "retryable": false,
  "retry_after_seconds": null
}
```

Status mapping:

- `401`: invalid/missing gateway bearer token;
- `403`: requested Oura capability is not granted or locally permitted;
- `404`: requested resource/document does not exist;
- `409`: Oura is not connected or reauthorization is required;
- `422`: request validation failure;
- `429`: provider/gateway rate limit, with `Retry-After` when available;
- `502`: invalid/unavailable provider response;
- `504`: bounded provider timeout;
- `500`: unexpected internal failure with a correlation ID and no stack trace.

Raw provider response bodies, OAuth codes, tokens, authorization headers,
client secrets, and stack traces must never appear in responses or normal logs.

## Compatibility

Non-breaking additions may occur within V1. Removing or renaming routes/fields,
changing null/zero semantics, changing units, or changing baseline definitions
requires a new project API major version. Updating the private Oura provider
adapter to a newer official upstream revision does not by itself change the
project API major version.
