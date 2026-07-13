# Setup and authentication

This guide takes a fresh clone to either an offline demo or a live Oura-backed
API. The project uses Python's standard `venv` module and `pip`.

## Requirements

- Python 3.11–3.14
- Git
- An Oura account and developer application only for live data

On Windows ARM64, use a native ARM64 Python build. The project is otherwise
platform-independent.

## Install

Windows PowerShell:

```powershell
git clone https://github.com/whuang214/oura-data-api.git
cd oura-data-api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item .env.example .env
```

macOS or Linux:

```bash
git clone https://github.com/whuang214/oura-data-api.git
cd oura-data-api
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cp .env.example .env
```

## Offline fixture mode

Fixture mode uses packaged, synthetic JSON records and makes no Oura request.
It is the quickest way to explore the API.

Generate a private gateway token:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Set these values in `.env`:

```dotenv
OURA_MODE=fixture
OURA_GATEWAY_TOKEN=paste-the-generated-value-here
OURA_HOME_TIMEZONE=Etc/UTC
```

Start the server:

```powershell
oura-api
```

Open `http://127.0.0.1:8766/docs` to use Swagger UI, or call the public health
route:

```powershell
curl.exe http://127.0.0.1:8766/api/v1/health
```

## Live Oura setup

### 1. Create an Oura application

Create an application at
[Oura API Applications](https://cloud.ouraring.com/oauth/applications).

| Oura field | Recommended value |
| --- | --- |
| Display name | `Oura Data API` or a name for your installation |
| Description | `Self-hosted, read-only JSON API for my personal Oura data.` |
| Contact email | An address you monitor |
| Website | Your repository or project website |
| Privacy policy | Your published privacy-policy URL |
| Terms of service | Your published terms URL |
| Redirect URI | `http://localhost:8765/callback` |

Oura permits plain HTTP for this local flow only with the literal `localhost`
host. Do not register `127.0.0.1` as the callback host.

Choose only the permissions your client needs. Daily sleep, readiness, and
activity form this project's core daily contract; other resources are
supplemental.

### 2. Configure credentials

Set the following in `.env`:

```dotenv
OURA_MODE=live
OURA_CLIENT_ID=paste-your-client-id
OURA_CLIENT_SECRET=paste-your-client-secret
OURA_GATEWAY_TOKEN=paste-a-separate-random-token
OURA_HOME_TIMEZONE=Etc/UTC
```

Never reuse an Oura credential as the gateway token. Runtime configuration
comes only from this file; process and operating-system environment variables
are ignored.

### 3. Authorize locally

```powershell
oura-oauth authorize
```

The helper opens Oura's consent page, validates the localhost callback, and
stores refreshable tokens in `.private/tokens.json`. Restart a running API
after authorization.

If automatic callback handling is unavailable, use:

```powershell
oura-oauth url
oura-oauth exchange
```

Paste the full callback URL only into the local prompt. It contains temporary
credentials and must not be shared.

### 4. Start and query

```powershell
oura-api
```

Protected routes require the separate gateway bearer token:

```http
GET /api/v1/analytics/daily-signals?start_date=2026-07-01&end_date=2026-07-07 HTTP/1.1
Host: 127.0.0.1:8766
Authorization: Bearer <your-gateway-token>
```

The default address is `http://127.0.0.1:8766`. Dates are examples; request an
inclusive range that exists in your Oura history.

## Disconnect

Use the CLI:

```powershell
oura-oauth logout
```

Or call `DELETE /api/v1/auth/connection` with the gateway bearer token. The
service attempts provider revocation before deleting its local token file.

## Next steps

- [API routes](<03 - API Routes.md>)
- [Configuration and security](<05 - Configuration and Security.md>)
