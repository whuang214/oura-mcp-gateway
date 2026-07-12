# MCP tool reference

The stdio server exposes exactly two tools. Both return JSON-serializable data and sanitize configuration,
authentication, transport, and endpoint errors.

## `get_oura_service_status`

Input: none.

The result includes:

- `server_version` and `api_version`;
- `mode`, `configured`, `configuration_state`, and a sanitized configuration message;
- credential-source, OAuth-client, persisted-token, and token-state categories;
- granted and missing scope names;
- home timezone and fixture availability; and
- optional SpO2/resilience enablement.

It never returns client secrets, access or refresh tokens, token paths, callback state, raw configuration, or stack
traces.

Call this first after installing, authorizing, or changing `.env`.

## `sync_oura_daily_data`

The tool retrieves and transforms a bounded set of Oura calendar dates. It never writes external data.

### Input

| Field | Type | Default | Meaning |
|---|---|---:|---|
| `existing_coverage` | array or null | null | Destination coverage records with `effective_date`, `status`, and sanitized `errors` |
| `start_date` | `YYYY-MM-DD` or null | null | Explicit inclusive range start |
| `end_date` | `YYYY-MM-DD` or null | null | Explicit inclusive range end; future values are clamped to today |
| `continuation_start_date` | `YYYY-MM-DD` or null | null | Resume cursor from a prior bounded response |
| `initial_days` | integer | 30 | Initial lookback when no explicit range or coverage exists |
| `overlap_days` | integer | 3 | Recent days refreshed during incremental synchronization |

Supplying either start or end makes the request explicit. An explicit bounded backfill scans every requested date.

### Paging

Each response contains at most 45 requested dates. When `plan.has_more` is true, call the tool again with the returned
`plan.continuation_start_date` and the unchanged original arguments.

API calls are separately chunked to at most `OURA_MAX_RANGE_DAYS` inclusive days (90 by default).

### Output

The top-level response contains:

- `plan` — the pure requested-date plan and continuation state;
- `records` — normalized source-level daily records retained for compatibility; each record carries
  `section_coverage` and sanitized `errors`;
- `summary` — requested/returned counts and status-specific date collections;
- `endpoint_errors` — sanitized failures that prevented an endpoint response;
- `transformed` — schema `2.0.0` analysis-ready collections;
- `retrieved_at`, `source_api_version`, and `source_server_version`.

`transformed` includes:

- `daily_records` — scalar one-row-per-usable-day records;
- `workout_records` — one child per Oura workout ID;
- `session_records` — one useful child per Oura session ID;
- `audit_records` — requested-date coverage and retry evidence; and
- `raw_provenance` — source IDs, section coverage, errors, and retrieval metadata.

`summary.confirmed_no_data_dates` records finalized dates with no usable core data. `summary.unresolved_dates` records
dates that could not be reliably ingested. Neither creates a blank curated daily row.

The older `summary.missing_dates` is a compatibility alias for `no_data_dates`.

## Consumer statuses

- `Complete` — all core sleep, detailed sleep, readiness, and activity sections are usable.
- `Partial` — a finalized date has some but not all core sections.
- `Provisional` — the current Oura day and expected to change.
- `No Data` — a finalized date has no usable core data; audit-only.
- `Sync Error` — a core retrieval, authentication, or transport failure prevented reliable ingestion.

Supplemental workout, session, stress, resilience, or SpO2 warnings do not downgrade an otherwise complete core day.

For exact fields, units, rounding, and null behavior, use the [data contract](data-contract-v2.md).
