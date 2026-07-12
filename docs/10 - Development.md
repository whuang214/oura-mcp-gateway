# Development

## Repository layout

```text
oura-data-api/
├── README.md                  # shortest user path
├── .env.example               # minimal runtime configuration template
├── PRIVACY.md, TERMS.md       # stable policy URLs for Oura app registration
├── pyproject.toml             # package metadata and dependency declarations
├── docs/                      # numbered user and design documentation
├── scripts/                   # local validation and distribution audits
├── src/oura_data_api/         # API package and sanitized fixture data
└── tests/                     # unit, contract, security, and packaging tests
```

`README.md` and `LICENSE` stay at the repository root for GitHub and package
metadata. `PRIVACY.md` and `TERMS.md` keep stable root paths because an Oura
developer application may link to them.

The API package owns Oura OAuth, provider retrieval, normalization, analytics,
and the `/api/v1` JSON contract. Google Sheets and MCP integrations are separate
consumers and are not dependencies of this package.

## Windows ARM64 setup

Use a native ARM64 Python 3.11–3.14 installation on ARM64 Windows. Verify the
interpreter before creating the virtual environment:

```powershell
python -c "import platform, sys; print(sys.version); print(platform.machine())"
```

`platform.machine()` must report `ARM64`. If it reports `AMD64`, select a native
ARM64 Python installation before continuing; do not rely on x64 emulation.

Create a standard library virtual environment and install the development
extras with pip:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

On macOS or Linux, activate with `source .venv/bin/activate` and use the same
`python -m pip install -e ".[dev]"` command.

Runtime configuration is read only from the explicit project `.env` file.
Tests use sanitized fixtures and must not call the live Oura API or read process
environment variables.

## Required local checks

Run validation from the activated virtual environment:

```powershell
python -m pytest --cov=oura_data_api --cov-report=term-missing
python -m ruff check .
python -m mypy src tests
python -m build
```

The test suite should cover strict file-only configuration, credential
protection, OAuth, pagination, retries and rate limits, provider mapping, API
contracts, transformations, missing-data semantics, and deterministic analytics.
The configured coverage floor is 75%.

Never claim a release is validated unless every applicable command was run and
its result observed. Record any skipped check and the remaining risk.

## Python version matrix

The supported range is Python 3.11–3.14. Test each installed native interpreter
in its own virtual environment before a release. On Windows ARM64, verify
`platform.machine()` inside every environment before running its suite.

Example for an explicitly selected interpreter:

```powershell
C:\Path\To\Python313-arm64\python.exe -m venv .venv-313
.\.venv-313\Scripts\python.exe -c "import platform; print(platform.machine())"
.\.venv-313\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv-313\Scripts\python.exe -m pytest -q
```

Repeat with each supported Python version available for the target platform.

## Distribution privacy audit

Build the wheel and source archive, then pass both archives to the repository's
auditor. The audit must reject private filenames, secrets, token payloads, and
personal health output.

```powershell
python -m build
$archives = Get-ChildItem dist -File | Where-Object { $_.Name -match '\.(whl|tar\.gz)$' }
python scripts\audit_distribution.py @($archives.FullName)
```

Inspect the final archive member list before publishing.

## Documentation checks

`tests/test_repository_layout.py` verifies the numbered documentation tree and
every relative Markdown link. When adding, moving, or removing a document,
update that test's expected file list and fix any links it reports.

## Publishing policy

This repository intentionally has no GitHub-hosted CI. Run the complete local
checks, review the staged diff for private data, and only then commit and push.
Never commit `.env`, `.private`, OAuth credentials, tokens, callback URLs, or
personal health output.
