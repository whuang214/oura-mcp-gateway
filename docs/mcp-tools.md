# MCP tool reference

The server exposes exactly two tools. Both return JSON-serializable data and sanitize configuration,
authentication, transport, and endpoint errors — no secrets, tokens, or stack traces ever appear in a
response.

## `get_oura_service_status`

Input: none.

The result includes:

- `server_version` and `api_version`
- `mode`, `configured`, `configuration_state`, and a sanitized configuration message
- credential-source, OAuth-client, persisted-token, and token-state categories
- granted and missing scope names
- home timezone and fixture availability
- optional SpO2/resilience enablement

Call this first after installing, authorizing, or changing `.env`.

## `sync_oura_daily_data`

Retrieves and transforms a bounded set of Oura calendar dates. It is read-only: it never writes data
anywhere.

### Input

| Field | Type | Default | Meaning |
|---|---|---:|---|
| `existing_coverage` | array or null | null | Coverage records you already hold, with `effective_date`, `status`, and sanitized `errors` |
| `start_date` | `YYYY-MM-DD` or null | null | Explicit inclusive range start |
| `end_date` | `YYYY-MM-DD` or null | null | Explicit inclusive range end; future values are clamped to today |
| `continuation_start_date` | `YYYY-MM-DD` or null | null | Resume cursor from a prior bounded response |
| `initial_days` | integer | 30 | Lookback when no range or coverage is given; with only `end_date`, the range starts `initial_days − 1` days earlier |
| `overlap_days` | integer | 3 | Recent days refreshed during incremental synchronization |

Supplying either `start_date` or `end_date` makes the request explicit, and an explicit backfill scans every
requested date. Without explicit bounds, the tool plans incrementally from `existing_coverage`, or falls back
to the latest `initial_days` when no coverage is supplied.

### Paging

Each response contains at most 45 requested dates. When `plan.has_more` is true, call the tool again with the
returned `plan.continuation_start_date` and the unchanged original arguments. Underlying API calls are
separately chunked to at most `OURA_MAX_RANGE_DAYS` inclusive days (90 by default).

### Output

The top-level response contains:

- `plan` — the requested-date plan and continuation state
- `records` — normalized source-level daily records; each carries `section_coverage` and sanitized `errors`
- `summary` — requested/returned counts and per-status date collections
- `endpoint_errors` — sanitized failures that prevented an endpoint response
- `transformed` — schema `2.0.0` analysis-ready collections
- `retrieved_at`, `source_api_version`, and `source_server_version`

`transformed` includes:

- `daily_records` — one scalar row per usable day
- `workout_records` — one child per Oura workout ID
- `session_records` — one child per Oura session ID
- `audit_records` — requested-date coverage and retry evidence
- `raw_provenance` — source IDs, section coverage, errors, and retrieval metadata

`summary.confirmed_no_data_dates` lists finalized dates with no usable core data, and
`summary.unresolved_dates` lists dates that could not be reliably ingested. Neither produces a blank daily
row. The older `summary.missing_dates` is a compatibility alias for `no_data_dates`.

## Record statuses

These statuses apply to the `transformed` collections and the `summary` date lists. (The normalized `records`
carry a separate source-level `completeness_status`; see the [data contract](data-contract.md).)

- `Complete` — all core sleep, detailed sleep, readiness, and activity sections are usable.
- `Partial` — a finalized date has some but not all core sections.
- `Provisional` — the current Oura day, expected to change.
- `No Data` — a finalized date has no usable core data; recorded in audit only.
- `Sync Error` — a core retrieval, authentication, or transport failure prevented reliable ingestion.

Supplemental workout, session, stress, resilience, or SpO2 warnings never downgrade an otherwise complete
core day.

For exact fields, units, rounding, and null behavior, see the [data contract](data-contract.md).
