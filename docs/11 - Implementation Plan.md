# Implementation status and cutover plan

Updated: 2026-07-12

## Intended outcome

Provide two reusable projects with one clear boundary:

1. `oura-data-api` owns Oura authentication, retrieval, canonical JSON, and
   deterministic analytics.
2. `oura-mcp` owns a thin read-only MCP adapter plus the deployable
   `$oura-sync` skill.

The skill materializes curated rows into a dedicated private Oura workbook.
The Master Nutrition workbook remains the nutrition system of record and never
receives Oura tabs or cross-workbook formulas.

## Completed API work

- The repository, distribution, module, CLI, and public links use
  `oura-data-api`.
- Standard-library `venv` and `pip` are the documented environment workflow.
- FastAPI exposes the versioned `/api/v1` JSON contract and OpenAPI document.
- Strict `.env`-only configuration ignores process environment variables.
- OAuth/token storage, gateway authentication, local binding, sanitized RFC
  problem responses, opaque cursors, retries, caching, and capability gates are
  implemented.
- The current official Oura API v2 resource registry is isolated behind the
  provider boundary.
- Curated daily signals and weekly trends are deterministic, scalar, null-safe,
  timezone-safe, and baseline-aware.
- The API package contains no MCP or Google dependency.
- Local tests, linting, strict typing, coverage, wheel build, and distribution
  privacy checks pass on native Windows ARM64.

## Completed workbook work

The private workbook **Will’s Oura Recovery & Performance** exists separately
from the Master Nutrition workbook. Its ID remains private configuration.

Workbook contract `1.1.0` is staged and verified:

- `Daily Signals`: 46 columns, one row per usable canonical Oura day;
- `Weekly Trends`: 37 columns, observed calendar-week summaries;
- `Events`: 17 columns, keyed by `workout:<id>` or `session:<id>`;
- `_Sync Ledger`: 22 columns, hidden and protected.

All tabs have the exact marker, instance ID, contract version, headers, two
frozen rows, filters, and date formatting. The workbook remains empty until the
new end-to-end path passes validation. The Master Nutrition workbook is
unchanged.

## Staged MCP and skill work

The separate `oura-mcp` project is staged locally with:

- strict file-only configuration and no Codex `env_vars` dependency;
- authenticated API identity checks before reusing a listener;
- optional owned API child-process management;
- bounded HTTP requests, cursor traversal, and sanitized problem mapping;
- read-only status, capability, day, analytics, event, stable-resource, and
  sync-bundle tools;
- event enrichment and per-resource outcomes for retry-safe partial sync;
- an official-initializer `$oura-sync` skill package;
- fail-closed workbook validation and scalar row rendering;
- RAW numeric-date writes, null/zero preservation, and formula-injection safety;
- deterministic reconciliation planning, hashing, and readback comparison;
- no consumer placeholders for finalized no-data dates or weeks.

The MCP owns no Oura provider logic, OAuth flow, analytics formula, workbook
identity, or Google Sheets writer. The skill owns no direct Oura/API client and
retrieves data only through MCP tools.

## Remaining cutover gates

### 1. Package and protocol validation

1. Create a fresh native ARM64 MCP `venv`.
2. Install the pinned runtime and development dependencies.
3. Run the complete unit suite, coverage, lint, strict typing, wheel build, and
   privacy audit.
4. Run the official skill quick validator.
5. Run in-memory MCP inventory/schema/unknown-argument tests.
6. Run a fixture-mode managed-child end-to-end smoke test.

### 2. Installed skill and Codex configuration

1. Create the ignored private `local-config.md` with the dedicated workbook
   identity, protected nutrition workbook ID, history start, timezone, and MCP
   server name.
2. Validate a staged installed copy.
3. Atomically replace the old `$oura-sync` directory; retain a
   non-discoverable rollback copy only through the observation window.
4. Configure Codex with the MCP venv interpreter, module, working directory,
   and timeouts only. Do not add `env` or `env_vars`.
5. Restart Codex and run status/capabilities before any Sheet write.

### 3. Staged lifetime backfill

1. Discover the earliest usable Oura day without fabricating empty dates.
2. Dry-run bounded ranges of at most 90 days.
3. Retrieve daily, weekly, workout, and session partitions through
   `oura_sync_bundle`.
4. Preserve `error`, `not_granted`, `disabled`, transport, and incomplete
   partitions; only successful complete partitions are authoritative.
5. Write only the four exact dedicated tabs and row 3 onward.
6. Read back exact values, formats, stable keys, versions, blanks versus zeros,
   and response hashes before advancing ledger state.
7. Replay the same ranges and require zero mutations.
8. Validate the June 28, July 4, July 10, and July 11 scenarios when those
   source dates exist.

### 4. Web consumer update

Give the owner of `$will-nutrition-coach` the private workbook identity and
[web consumer handoff](<09 - Web Consumer Handoff.md>). The web skill must:

- read the Master Nutrition and Oura workbooks independently;
- join exact dates only in memory;
- read Oura conditionally when recovery/performance context is relevant;
- prefer curated daily/weekly values instead of recreating calculations;
- keep ordinary nutrition logging functional when Oura is missing or stale;
- honor subjective pain, soreness, illness, energy, and jump feel over device
  scores;
- never use wearable calories to set or automatically eat back nutrition
  targets.

## Cutover and rollback

No destructive migration of the Master Nutrition workbook is required.

- **API rollback:** stop the local API; no Sheet mutation occurs while stopped.
- **MCP rollback:** disable the Codex MCP entry; the API remains independently
  usable.
- **Skill rollback:** disable the staged writer or restore the temporary backup;
  never restore a version that writes into the nutrition workbook.
- **Sheets rollback:** keep the dedicated workbook intact for diagnosis and
  restore rows only from verified readback/audit state.
- **Web rollback:** disable the optional Oura workbook reference; nutrition
  behavior continues normally.

## Completion criteria

- Both public projects are locally tested and published without coauthor
  metadata or required CI/PR workflow.
- The API stays JSON-only and reusable; MCP and Google remain separate clients.
- The installed skill can perform bounded incremental and lifetime syncs into
  only the dedicated workbook.
- Repeating an identical sync produces no consumer-row mutations.
- Missing data is blank/omitted, never zero or a placeholder.
- Active and workout calories stay separate and context only.
- The web consumer treats Oura as optional supporting evidence and honors
  subjective overrides.
