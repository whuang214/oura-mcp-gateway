# Oura Data API

A self-hosted, read-only JSON API for your personal Oura data.

The project exposes a stable `/api/v1` contract for sleep, readiness, activity,
stress, workouts, sessions, heart-rate data, and deterministic recovery trends.
It uses the latest officially supported Oura provider API behind an internal
adapter, so provider changes do not leak into the public project contract.

Your Oura credentials and health data stay on your machine. The API does not
write to Google Sheets or include an MCP server; those are separate optional
consumers.

## Quick start

Requirements: Python 3.11–3.14 and Git. Native ARM64 Python is recommended on
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

Open `.env` and add your own Oura application credentials and a private gateway
bearer token. Runtime configuration comes only from that file; Windows and shell
environment variables are ignored.

Create an Oura application at
[Oura API Applications](https://cloud.ouraring.com/oauth/applications), then
authorize it locally:

```powershell
oura-oauth authorize
```

Start the API:

```powershell
oura-api
```

The default local address is `http://127.0.0.1:8766`. Check liveness with:

```powershell
curl.exe http://127.0.0.1:8766/api/v1/health
```

All health-data routes require the separate gateway bearer token. Never paste
that token, Oura credentials, OAuth callback URLs, or personal health output
into source code, issues, screenshots, or chat.

## What you can query

- Granular daily sleep, readiness, activity, stress, SpO2, and heart-health
  resources
- Detailed sleep periods and explicitly requested sample series
- Heart-rate and ring-battery time series
- Workouts, sessions, enhanced tags, rest mode, and ring metadata
- Composite days
- Deterministic daily signals and coverage-aware weekly trends

Missing dates are omitted rather than replaced with zero-valued placeholders.
Active and workout calories remain context-only fields and never become a
nutrition target.

## Documentation

Read the numbered guides in order, beginning with the
[documentation index](<docs/00 - Documentation Index.md>).

The most important references are:

- [Getting started](<docs/01 - Getting Started.md>)
- [Authentication](<docs/02 - Authentication.md>)
- [Configuration](<docs/03 - Configuration.md>)
- [API V1 contract](<docs/06 - API V1 Contract.md>)
- [Data contract](<docs/07 - Data Contract.md>)

## Development

Create the virtual environment as above, then install the development extras:

```powershell
python -m pip install -e ".[dev]"
python -m pytest
python -m ruff check .
python -m mypy
```

All validation is local; this repository intentionally has no hosted CI.

## License and policies

Licensed under the [MIT License](LICENSE). Oura metrics are wellness data, not
medical advice. This project is not affiliated with or endorsed by Oura.

- [Privacy](PRIVACY.md)
- [Terms](TERMS.md)
