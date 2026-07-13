# Development

The codebase is organized so transport, application logic, analytics, and HTTP
concerns can be tested independently.

## Install development tools

Create and activate a standard virtual environment, then install the declared
development extras:

```powershell
python -m pip install -e ".[dev]"
```

## Repository layout

```text
src/oura_data_api/
|-- api/          HTTP boundary and public contract
|-- provider/     Oura resource registry and transport
|-- services/     Mapping and orchestration
|-- analytics/    Pure daily and weekly transformations
|-- fixtures/     Synthetic offline data
|-- auth.py       OAuth and rotating-token storage
|-- config.py     Strict settings parser
`-- errors.py     Shared domain errors
scripts/          Distribution audit entry points
tests/            Unit, contract, security, and integration-style tests
docs/             Public technical documentation
```

## Local checks

Run the full suite before committing:

```powershell
python -m pytest
python -m ruff check .
python -m mypy
```

After generating a wheel or source archive, pass each artifact to the public
distribution audit:

```powershell
python scripts/audit_distribution.py path\to\oura_data_api.whl
```

All validation runs locally; the repository does not depend on hosted CI.

## Test strategy

- Pure transformation tests cover units, rounding, baselines, and missing data.
- Provider tests cover retries, paging, capability behavior, and safe failures.
- API contract tests cover strict query parsing, auth, envelopes, cursors, and
  problem responses.
- Security tests cover `.env` permissions, token rotation, redaction, and
  release-content scanning.
- Fixture-mode tests exercise the application without an Oura account.

Fixtures must be clearly synthetic and must not reproduce personal health
records. Never add real credentials, callback URLs, workbook identifiers, or
raw wearable exports to tests, issues, screenshots, or commits.

## Change rules

- Keep Oura provider changes inside `provider/` and mapping code.
- Keep deterministic analytics pure and free of framework dependencies.
- Preserve `day`, units, null/zero behavior, coverage vocabulary, and error
  semantics within V1.
- Add or update contract tests for any public route or field.
- A breaking public change requires a new project API major version.

## Packaging

The package uses Hatchling through the standard Python build interface. Release
artifacts exclude `.env`, token stores, logs, private results, and verification
reports. Inspect any generated archive before publishing it.

## Useful references

- [System design](<02 - System Design.md>)
- [API routes](<03 - API Routes.md>)
- [Data model](<04 - Data Model.md>)
- [Oura API documentation](https://cloud.ouraring.com/docs/)
- [Oura OpenAPI specification](https://cloud.ouraring.com/v2/docs)
