# Getting started

This guide takes a fresh clone to a local Oura Data API V1 process using the
standard Python `venv` module and `pip`.

## Requirements

- Python 3.11–3.14
- Git
- Native ARM64 Python on Windows ARM64
- An Oura account for live data, or the packaged fixture mode

## Clone

```powershell
git clone https://github.com/whuang214/oura-data-api.git
cd oura-data-api
```

## Create the virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Confirm that the interpreter matches the machine before continuing:

```powershell
python -c "import platform, sys; print(platform.machine()); print(sys.executable)"
```

On Windows ARM64, the architecture must report `ARM64`, not `AMD64`.

## Configure

```powershell
Copy-Item .env.example .env
```

Open `.env`. For fixture mode, set:

```dotenv
OURA_MODE=fixture
OURA_GATEWAY_TOKEN=replace-with-a-private-random-value-at-least-32-characters
OURA_HOME_TIMEZONE=America/Denver
```

For live data, add your Oura application client ID and secret, then follow
[02 - Authentication](<02 - Authentication.md>).

Runtime configuration comes only from the selected `.env` file. The API ignores
Windows, shell, service-manager, and parent-process environment variables.

## Start the API

With the virtual environment active:

```powershell
oura-api
```

The default address is `http://127.0.0.1:8766`.

In another terminal, check public liveness:

```powershell
curl.exe http://127.0.0.1:8766/api/v1/health
```

The response is JSON and contains no credential or health details.

## Make an authenticated request

Read the gateway token locally from your `.env` and send it in the
`Authorization: Bearer` header. Do not put the token in source code, shell
history that will be shared, screenshots, issues, or chat.

Example shape:

```http
GET /api/v1/status HTTP/1.1
Host: 127.0.0.1:8766
Authorization: Bearer <your-local-gateway-token>
```

Then query an explicit date range:

```http
GET /api/v1/daily/sleep?start_date=2026-07-01&end_date=2026-07-07 HTTP/1.1
Host: 127.0.0.1:8766
Authorization: Bearer <your-local-gateway-token>
```

Collections never invent placeholder dates. A successful range with no records
returns an empty `data` array.

## Development installation

Contributors install the optional development tools inside the same virtual
environment:

```powershell
python -m pip install -e ".[dev]"
python -m pytest
```

## Next documents

- [02 - Authentication](<02 - Authentication.md>)
- [03 - Configuration](<03 - Configuration.md>)
- [06 - API V1 Contract](<06 - API V1 Contract.md>)
