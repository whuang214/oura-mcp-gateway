# Repository layout, testing, and release checks

## Layout

```text
oura-mcp-gateway/
├── README.md                 # shortest user path
├── .env.example              # safe configuration template
├── pyproject.toml
├── uv.lock
├── docs/
│   ├── guides/               # user setup and integrations
│   ├── reference/            # MCP, architecture, and schema contracts
│   ├── operations/           # controlled migration runbooks
│   └── development/          # maintainer documentation
├── integrations/
│   └── codex/oura-sync/      # installable desktop Sheet-sync skill
├── scripts/                  # protected export and distribution audit entry points
├── src/oura_mcp/             # Python package and packaged fixture data
└── tests/                    # unit, contract, security, and packaging tests
```

`README.md` and `LICENSE` stay at the root for GitHub and package metadata. `PRIVACY.md`, `SECURITY.md`, and `TERMS.md`
remain stable public policy endpoints used by the existing Oura developer application. All technical and operational
guidance belongs under `docs/`.

The `src` layout, adjacent packaged fixtures, and separate `tests` tree follow normal Python packaging conventions.
`integrations/codex/oura-sync` stays self-contained because users copy that directory into their local Codex skills.

## Install development dependencies

```powershell
Copy-Item .env.example .env
uv sync --frozen
```

The template starts in fixture mode. Tests never write Google Sheets or call the live Oura API.

## Required checks

```powershell
uv run pytest --cov=oura_mcp --cov-report=term-missing
uv run ruff check .
uv run mypy --platform win32
uv run mypy --platform linux
uv build
```

The configured coverage floor is 75%. Tests cover configuration isolation, protected credentials, OAuth, pagination,
retry/rate behavior, fixture and MCP contracts, transformations, missing data, planning, and Sheet reconciliation.

## Python version matrix

The supported range is Python 3.11–3.14. Run isolated local suites before a public release:

```powershell
uv run --isolated --python 3.11 --frozen pytest -q
uv run --isolated --python 3.12 --frozen pytest -q
uv run --isolated --python 3.13 --frozen pytest -q
uv run --isolated --python 3.14 --frozen pytest -q
```

## Distribution privacy audit

Build first, then pass only the wheel and source archive to the auditor:

```powershell
$archives = Get-ChildItem dist -File |
  Where-Object { $_.Name -match '\.(whl|tar\.gz)$' }
uv run python scripts\audit_distribution.py @($archives.FullName)
```

The audit rejects private filenames, secrets, token payloads, Sheet links, local config, and identifiable verification
artifacts. Inspect the final archive member list before publishing.

## Documentation checks

`tests/test_repository_layout.py` verifies the public docs tree and every relative Markdown link. When moving a
document:

1. update all repository links;
2. preserve external compatibility URLs or coordinate their update;
3. rebuild both distributions; and
4. rerun the privacy audit.

## Publishing policy

This repository intentionally has no GitHub-hosted CI. The maintainer runs the complete local checks, reviews the
staged diff for private data, and only then commits and pushes. Never commit `.env`, `.private`, live Sheet identifiers,
OAuth credentials, tokens, callback URLs, or personal health output.
