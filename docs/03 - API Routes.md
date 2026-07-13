# API routes

Contract version: `1.0.0`

Base path: `/api/v1`

The project exposes read-only Oura data as JSON. When public docs are enabled,
the running server also provides Swagger UI at `/docs` and OpenAPI JSON at
`/openapi.json`.

## Authentication and response envelope

Only these routes are public:

- `GET /api/v1/health`
- `GET /api/v1/health/challenge`
- `GET /api/v1/auth/callback`

Every other API route requires:

```http
Authorization: Bearer <gateway-token>
```

Successful responses share one shape:

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
    "range": null,
    "next_cursor": null,
    "retrieved_at": "2026-01-15T12:00:00Z",
    "freshness": null
  },
  "warnings": []
}
```

Collections place an array in `data`. Single-document and single-day routes
place one object in `data`. `meta.next_cursor` continues a collection; clients
must treat it as opaque.

## Query rules

Date collections use required, inclusive `start_date` and `end_date` values in
`YYYY-MM-DD` form. They accept `limit` from 1–1000 and an optional `cursor`.
The maximum date range is 90 days.

Time series accept either:

- `start_datetime` and `end_datetime` as offset-aware RFC 3339 timestamps; or
- `latest=true`.

Datetime ranges are half-open and limited to seven days. Sample routes use a
default limit of 500 and maximum of 5000. Unknown query parameters, future
ranges, reversed bounds, oversized ranges, and mismatched cursors are rejected.

## Curated routes

| Method and route | What `data` returns |
| --- | --- |
| `GET /days` | Composite days for a range, with requested sections and per-section coverage |
| `GET /days/{day}` | One composite canonical Oura day |
| `GET /analytics/daily-signals` | Scalar, analysis-ready daily rows; missing dates are omitted |
| `GET /analytics/daily-signals/{day}` | One analysis-ready daily row or `404` |
| `GET /analytics/daily-coverage` | Every requested day with coverage, including `No Data` and `Sync Error` |
| `GET /analytics/weekly-trends` | Observed-only calendar-week aggregates with denominators |

`/days` and `/days/{day}` accept an optional comma-separated `include` value:
`sleep`, `readiness`, `activity`, `stress`, `spo2`, `workouts`, `sessions`,
`cardiovascular_age`, `vo2_max`, and `tags`. The default is the three core
sections: sleep, readiness, and activity.

## Status and authorization

| Method and route | What `data` returns |
| --- | --- |
| `GET /health` | Bare liveness only |
| `GET /health/challenge?nonce=...` | Process ID and nonce-bound gateway identity proof |
| `GET /status` | Sanitized mode, connection, timezone, date, and freshness state |
| `GET /capabilities` | Resource maturity, configuration, grants, and availability |
| `GET /profile` | Optional scope-controlled personal profile |
| `POST /auth/authorizations` | A state-bound Oura authorization URL |
| `GET /auth/callback` | Browser OAuth callback handling |
| `GET /auth/connection` | Sanitized Oura connection status |
| `DELETE /auth/connection` | Provider revocation attempt and local disconnect |

## Daily source resources

Each row below has both a collection route and a document route formed by
adding `/{source_id}`.

| Collection route | What each record contains |
| --- | --- |
| `/daily/activity` | Activity score and contributors, steps, durations, distance, MET totals, and context-only calories |
| `/daily/readiness` | Readiness score and contributors, temperature deviation, and trend |
| `/daily/sleep` | Daily sleep score and contributors |
| `/daily/stress` | High-stress and high-recovery seconds plus Oura's day summary |
| `/daily/spo2` | Average SpO2 and breathing-disturbance index when available |
| `/daily/cardiovascular-age` | Vascular age and pulse-wave velocity when available |

## Detailed and event resources

These also support collection and `/{source_id}` document forms.

| Collection route | What each record contains |
| --- | --- |
| `/sleep-periods` | Individual long sleeps, naps, and rests with stages, duration, timing, HR, HRV, breathing, and efficiency |
| `/sleep-times` | Oura bedtime recommendation and status |
| `/workouts` | Workout timing, activity, intensity, duration, distance, source, and context-only calories |
| `/sessions` | Guided or unguided session timing, type, and mood |
| `/enhanced-tags` | Current Oura tags, custom names, comments, and time ranges |
| `/rest-mode-periods` | Rest-mode ranges and tagged episodes |
| `/vo2-max` | Oura VO2 max estimate and timestamp |
| `/rings` | Ring hardware, firmware, design, size, setup time, and source ID |

`/rings` is cursor-paginated rather than date-filtered.

## Time series

| Route | What each record contains |
| --- | --- |
| `/heart-rate` | Timestamped beats-per-minute observations and source |
| `/ring-battery` | Timestamped ring battery level and status |

## Dense sample routes

Large arrays stay out of default documents and are requested explicitly.

| Route suffix | Returns |
| --- | --- |
| `/sleep-periods/{source_id}/samples/heart-rate` | Sleep heart-rate samples |
| `/sleep-periods/{source_id}/samples/hrv` | Sleep HRV samples |
| `/sleep-periods/{source_id}/samples/movement` | Sleep movement samples |
| `/sleep-periods/{source_id}/samples/sleep-phases` | Sleep-phase samples at `30s` or `5m` resolution |
| `/sessions/{source_id}/samples/heart-rate` | Session heart-rate samples |
| `/sessions/{source_id}/samples/hrv` | Session HRV samples |
| `/sessions/{source_id}/samples/motion` | Session motion samples |
| `/daily/activity/{source_id}/samples/met` | Activity MET samples |
| `/daily/activity/{source_id}/samples/classification` | Activity-classification samples |

Sample responses preserve source intervals, units, timestamps, and null samples.

## Experimental routes

These routes require explicit enablement and are outside the stable V1
compatibility promise:

- `/experimental/daily/resilience` and `/{source_id}`
- `/experimental/legacy-tags` and `/{source_id}`

Resilience availability varies by account. Legacy tags are deprecated in favor
of enhanced tags. An unavailable optional resource produces a warning in a
composite request and does not invalidate usable core data.

## Errors

Errors use RFC 9457-style `application/problem+json`:

```json
{
  "type": "https://github.com/whuang214/oura-data-api/problems/request-validation-failed",
  "title": "Request validation failed",
  "status": 400,
  "detail": "The request did not match the API contract.",
  "instance": "/api/v1/daily/sleep",
  "code": "request_validation_failed",
  "request_id": "01J...",
  "retryable": false,
  "retry_after_seconds": null
}
```

Common statuses are `400` invalid request, `401` gateway authentication, `403`
unavailable capability, `404` missing document, `409` disconnected Oura
account, `429` rate limit, `502` provider failure, and `504` provider timeout.
Responses never include provider bodies, OAuth codes, secrets, authorization
headers, or stack traces.

## Compatibility

V1 may add optional routes or fields. Removing or renaming public routes or
fields, changing units, changing null/zero behavior, or changing deterministic
feature definitions requires a new project API major version.
