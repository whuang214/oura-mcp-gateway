# Development

## Repository layout

```text
oura-mcp-gateway/
├── README.md            # shortest user path
├── .env.example         # minimal configuration template
├── PRIVACY.md, TERMS.md # stable policy URLs referenced by Oura app registrations
├── pyproject.toml
├── uv.lock
├── docs/                # user guides and reference documentation
├── scripts/             # distribution privacy audit entry point
├── src/oura_mcp/        # Python package and packaged fixture data
└── tests/               # unit, contract, security, and packaging tests
```

`README.md` and `LICENSE` stay at the root for GitHub and package metadata. `PRIVACY.md` and `TERMS.md` must
keep their exact root paths: existing Oura developer application registrations link to them.

The `src` layout, adjacent packaged fixtures, and separate `tests` tree follow standard Python packaging
conventions.

## Set up a development environment

```bash
cp .env.example .env    # PowerShell: Copy-Item .env.example .env
uv sync --frozen
```

Tests never call the live Oura API; add `OURA_MODE=fixture` to `.env` if you want to run the server itself
without credentials.

## Required checks

```bash
uv run pytest --cov=oura_mcp --cov-report=term-missing
uv run ruff check .
uv run mypy --platform win32
uv run mypy --platform linux
uv build
```

The configured coverage floor is 75%. Tests cover configuration isolation, credential protection, OAuth,
pagination, retry and rate-limit behavior, fixture and MCP contracts, transformation, missing-data handling,
and sync planning.

The project pins `mcp==1.28.1`. Do not change the pin without an explicit SDK migration and a contract-test
pass.

## Python version matrix

The supported range is Python 3.11–3.14. Before a release, run the suite against each:

```bash
uv run --isolated --python 3.11 --frozen pytest -q
uv run --isolated --python 3.12 --frozen pytest -q
uv run --isolated --python 3.13 --frozen pytest -q
uv run --isolated --python 3.14 --frozen pytest -q
```

## Distribution privacy audit

Build first, then pass the wheel and source archive to the auditor, which rejects private filenames, secrets,
and token payloads:

```bash
uv build
uv run python scripts/audit_distribution.py dist/*.whl dist/*.tar.gz
```

On PowerShell:

```powershell
$archives = Get-ChildItem dist -File | Where-Object { $_.Name -match '\.(whl|tar\.gz)$' }
uv run python scripts\audit_distribution.py @($archives.FullName)
```

Inspect the final archive member list before publishing.

## Documentation checks

`tests/test_repository_layout.py` verifies the docs tree and every relative Markdown link. When adding,
moving, or removing a document, update that test's expected file list and fix any links it reports.

## Publishing policy

This repository intentionally has no GitHub-hosted CI. Run the complete local checks, review the staged diff
for private data, and only then commit and push. Never commit `.env`, `.private`, OAuth credentials, tokens,
callback URLs, or personal health output.
