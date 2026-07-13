# Oura Data API

A self-hosted, read-only JSON API for personal Oura data and deterministic
recovery analytics.

The project turns Oura API v2 into a stable `/api/v1` contract with
strict validation, explicit units, coverage-aware analytics, and predictable
missing-data behavior. It is built with FastAPI and works as a standalone API
for scripts, applications, dashboards, or AI integrations.

## What it provides

- Granular sleep, readiness, activity, stress, SpO2, workout, session, heart
  rate, and ring resources
- Analysis-ready daily signals and observed-only weekly trends
- Local Oura OAuth, refresh-token rotation, and a separate API bearer token
- Sanitized fixture data for development without an Oura account
- A versioned response envelope, bounded pagination, and structured errors

Missing data is never converted to zero or synthesized into placeholder days.
Oura calorie estimates remain context-only and never become nutrition targets.

## How it fits together

```text
Oura API -> provider adapter -> canonical models + analytics -> FastAPI -> your client
```

Oura provider details stay behind the adapter, so this project's V1 contract is
independent of Oura's provider version. Google Sheets and MCP are optional
consumers and are not part of this repository.

## Quick start

Requirements: Python 3.11–3.14 and Git. Use a native ARM64 Python build on
Windows ARM64.

```powershell
git clone https://github.com/whuang214/oura-data-api.git
cd oura-data-api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item .env.example .env
```

On macOS or Linux, activate with `source .venv/bin/activate`.

For an offline demo, set `OURA_MODE=fixture` and add a private
`OURA_GATEWAY_TOKEN` of at least 32 characters. For live data, add your Oura
application credentials and run:

```powershell
oura-oauth authorize
oura-api
```

The API starts at `http://127.0.0.1:8766`. OpenAPI is available at
`http://127.0.0.1:8766/docs` when enabled.

```powershell
curl.exe http://127.0.0.1:8766/api/v1/health
```

See [Setup and authentication](<docs/01 - Setup and Authentication.md>) for
the complete live-data flow.

## Endpoint overview

| Route family | What `data` returns |
| --- | --- |
| `/health`, `/status`, `/capabilities` | Liveness, sanitized runtime state, and available Oura resources |
| `/auth/*`, `/profile` | Local OAuth connection operations and optional profile data |
| `/days`, `/days/{day}` | Composite Oura days with requested sections and coverage |
| `/analytics/daily-signals*` | Readable daily sleep, recovery, activity, stress, workout, and baseline fields |
| `/analytics/daily-coverage` | One audit row for every requested date, including gaps and errors |
| `/analytics/weekly-trends` | Observed weekly aggregates with counts and coverage denominators |
| `/daily/*` | Granular daily activity, readiness, sleep, stress, SpO2, and heart-health records |
| `/sleep-periods`, `/workouts`, `/sessions`, and related routes | Detailed sleep and event records |
| `/heart-rate`, `/ring-battery` | Timestamped time-series samples |
| `*/samples/*` | Explicitly requested dense source samples |

All routes use the `/api/v1` prefix. Collections return arrays; document and
single-day routes return one object. See the [full route reference](<docs/03 - API Routes.md>).

## Response shape

```json
{
  "data": [],
  "meta": {
    "api_version": "1",
    "schema_version": "1.0.0",
    "request_id": "01J...",
    "next_cursor": null
  },
  "warnings": []
}
```

Protected routes require `Authorization: Bearer <gateway-token>`. Date ranges
are inclusive and limited to 90 days; time-series ranges are limited to seven
days. Errors use `application/problem+json`.

## Project structure

```text
src/oura_data_api/
|-- api/          FastAPI routes, validation, envelopes, and errors
|-- provider/     Oura transport and resource registry
|-- services/     Request orchestration and canonical mapping
|-- analytics/    Deterministic daily and weekly features
|-- fixtures/     Sanitized offline sample data
|-- auth.py       OAuth and protected token storage
`-- config.py     Strict .env-only configuration
scripts/          Distribution and privacy checks
tests/            Unit, contract, security, and runtime tests
docs/             Setup, design, route, and contributor guides
```

## Documentation

Start with the [documentation map](docs/README.md), then use:

- [Setup and authentication](<docs/01 - Setup and Authentication.md>)
- [System design](<docs/02 - System Design.md>)
- [API routes](<docs/03 - API Routes.md>)
- [Data model](<docs/04 - Data Model.md>)
- [Configuration and security](<docs/05 - Configuration and Security.md>)
- [Development](<docs/06 - Development.md>)

## Development

```powershell
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m mypy
```

## Related project

[Oura MCP](https://github.com/whuang214/oura-mcp) exposes this API to MCP
clients and includes an optional Google Sheets sync skill.

## License

[MIT](LICENSE). See [Privacy](PRIVACY.md) and [Terms](TERMS.md). Oura metrics
are wellness data, not medical advice. This project is not affiliated with or
endorsed by Oura.
