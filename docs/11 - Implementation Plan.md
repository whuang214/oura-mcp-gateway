# Oura Data API V1 Refactor — Approval Plan

Prepared: 2026-07-12

## Intended outcome

Refactor the current repository into a reusable,
self-hosted **Oura Data API V1** that returns typed JSON. Move MCP and Google
Sheets behavior into separate consumers. Delete and recreate the installed
`oura-sync` Codex skill so its only job is to materialize curated API V1 data
into a new private Oura workbook.

No implementation begins until this plan is approved.

## Confirmed current state

- The repository is at `C:\Users\whuan\Desktop\GitHub\oura-data-api`.
- `main` is at `5d21fb5` and tracks `origin/main`.
- The user has an uncommitted file-structure refactor affecting 36 files
  (approximately 149 insertions and 2,409 deletions). Preserve it and checkpoint
  it separately before logic changes.
- The installed `oura-sync` skill still depends on the local `oura` MCP and
  targets five deleted Oura tabs in the Master Nutrition workbook.
- Those five Oura tabs have been deleted and the nine non-Oura nutrition,
  goals, training, weight, and reflection tabs were verified intact.
- Drive contains no separate Oura spreadsheet yet.
- The new project contract is V1. The private provider adapter uses the latest
  officially supported Oura upstream API and linked official OpenAPI schema.

## Scope decisions proposed for approval

1. Reframe the product and Python distribution as `oura-data-api` while keeping
   the current local folder and GitHub repository name unchanged. The user will
   rename the repository separately later.
2. Publish only `/api/v1` routes and one V1 JSON contract; do not expose a
   project V2 compatibility surface.
3. Support a self-hosted single-user instance first. Each GitHub user supplies
   their own Oura OAuth application.
4. Keep Google Sheets and MCP out of the API package.
5. Use FastAPI for the HTTP/OpenAPI surface. Dependency changes will still be
   presented for explicit approval immediately before they are added or
   installed.
6. Create a private workbook named **Will’s Oura Recovery & Performance** with
   four tabs: `Daily Signals`, `Weekly Trends`, `Events`, and `_Sync Ledger`.
7. Rebuild `oura-sync` from scratch under the same trigger name and atomically
   replace the installed skill only after staging validation.
8. Update the web nutrition-coach skill through the separate handoff contract.
9. Develop the MCP adapter as a separate project after API V1 is stable.

## Target boundaries

```text
Latest supported Oura API
  -> Oura Data API V1
      -> dedicated Google Sheets materializer (`oura-sync` skill)
      -> separate MCP adapter project
      -> other scripts/apps

Master Nutrition workbook + dedicated Oura workbook
  -> web nutrition-coach skill joins exact dates in memory
```

### Oura Data API V1 owns

- OAuth and token refresh;
- current official Oura endpoint registry and capability detection;
- bounded upstream retrieval, retries, rate-limit handling, and pagination;
- typed upstream DTOs and canonical models;
- units, date attribution, coverage/status evaluation, and error mapping;
- deterministic daily signals and weekly trend calculations;
- JSON envelopes, problem responses, OpenAPI, and freshness metadata.

### Desktop `oura-sync` skill owns

- calling the local API V1, never Oura upstream or MCP;
- rendering API responses into fixed Sheet row contracts;
- idempotent reconciliation, bounded writes, and exact readback validation;
- sync watermarks, retry records, and finalized no-data coverage;
- creating/bootstraping only the dedicated Oura workbook structure when
  explicitly enabled.

### Web nutrition-coach skill owns

- conditional, read-only consumption of the dedicated workbook;
- joining Oura and nutrition/subjective records on exact date in memory;
- contextual interpretation, conflicts, confidence, and coaching language;
- continuing ordinary nutrition behavior when Oura is missing or stale.

### Separate MCP project owns

- mapping MCP tools to API V1 requests;
- API base URL and gateway authentication only;
- no Oura OAuth, normalization, analytics, or Sheets logic.

## Phased implementation

### Phase 0 — Preserve the current work

1. Review the current file-structure diff for accidental deletions or secrets.
2. Run the tests appropriate to the current structure-only changes.
3. Commit that refactor separately on `main`, without a coauthor.
4. Tag or record the last working MCP implementation for code rollback.
5. Freeze sanitized existing fixtures and golden behavior before logic changes.

Exit gate: clean, recoverable baseline; structure and logic changes are not
mixed in one commit.

### Phase 1 — Lock the contracts before coding

1. Write the API V1 route matrix and OpenAPI response schemas.
2. Record the exact latest official Oura resource inventory, filters, units,
   fields, scopes/capability uncertainty, and provider version.
3. Mark deprecated legacy tags and undocumented interbeat intervals outside the
   initial stable contract; treat resilience as capability-gated until verified.
4. Define the common success envelope, opaque cursors, freshness metadata, and
   RFC problem-error contract.
5. Define Sheet contract V1 and web consumer contract V1.
6. Add sanitized contract examples and snapshot tests.

Exit gate: route, JSON, Sheet, and web contracts are reviewable without reading
implementation code.

### Phase 2 — Extract the framework-neutral API core

1. Rename the Python package from `oura_mcp` to `oura_data_api`; keep the
   repository/folder name unchanged during this refactor.
2. Create one typed resource registry for provider path, filters, capabilities,
   date semantics, and stable/experimental status.
3. Replace overlapping normalization/transformation/status logic with:
   - tolerant typed upstream DTOs;
   - strict canonical domain models;
   - one mapper;
   - one coverage evaluator;
   - one deterministic feature engine.
4. Preserve Oura canonical `day`, nulls, explicit zeroes, source IDs, and raw
   units internally. Round only at a declared output boundary.
5. Remove spreadsheet manual-row and destination-gap policy from the API core.
6. Keep runtime configuration strict file-only through explicit `--env-file`;
   ignore Windows/process environment variables.

Exit gate: pure unit-tested core with no MCP or Google imports.

### Phase 3 — Implement the JSON HTTP API

1. Add an app factory, CLI, authentication boundary, and protected status.
2. Implement meta/auth routes: health, status, capabilities, profile opt-in,
   connection status, and disconnect.
3. Implement granular source routes for daily summaries, detailed sleep,
   heart-rate samples, workouts, sessions, enhanced tags, rest mode, ring
   configuration/battery, sleep time, cardiovascular age, SpO2, and VO2 max.
4. Put dense sleep/session/activity arrays behind explicit sample subresources
   instead of including them in default summaries.
5. Implement `/days`, deterministic `/analytics/daily-signals`, and
   `/analytics/weekly-trends`.
6. Add bounded ranges, opaque cursors, ETags/read-through cache metadata,
   rate-limit propagation, and sanitized problem JSON.
7. Keep data routes JSON-only. OAuth browser redirects are the only allowed
   transport exception.

Exit gate: local startup smoke test, OpenAPI snapshot, full unit/integration
tests, type checking, linting, secret-leak tests, and Windows ARM64 validation.

### Phase 4 — Create the dedicated Oura workbook

1. Create a new private native Google workbook only after explicit approval.
2. Add workbook marker `OURA_DATA_WORKBOOK_V1`, a random workbook instance ID,
   contract/logic versions, and exact headers.
3. Create:
   - `Daily Signals`, keyed by Date;
   - `Weekly Trends`, keyed by Week Start;
   - `Events`, keyed by `workout:<id>` or `session:<id>`;
   - `_Sync Ledger`, hidden/protected and keyed by ledger/run key.
4. Do not add formulas or `IMPORTRANGE` to the Master Nutrition workbook.
5. Keep raw payloads and dense time series out of Sheets.

Exit gate: empty workbook structure passes metadata/header/marker/version checks
and the Master Nutrition workbook is unchanged.

### Phase 5 — Delete and recreate the installed `oura-sync` skill

Build the replacement in a staging directory with the official skill
initializer, then swap it into `$CODEX_HOME/skills/oura-sync` after validation.
Do not modify the installed skill incrementally.

Proposed skill package:

```text
oura-sync/
├── SKILL.md
├── agents/openai.yaml
├── scripts/
│   ├── oura_api_client.py
│   ├── render_sheet_rows.py
│   └── validate_contract.py
└── references/
    ├── configuration.md
    ├── api-contract.md
    ├── sheet-contract.md
    └── reconciliation.md
```

Key behavior:

- No `oura` MCP dependency in `agents/openai.yaml`.
- The API bearer token stays only in the API project's explicit `.env`; helper
  code reads it without printing it. Codex instructions never open or echo the
  secret file.
- Non-secret local configuration holds API base URL, explicit env-file path,
  spreadsheet ID, tab names, versions, overlap/chunk settings, and protected
  spreadsheet IDs.
- Hard-deny the Master Nutrition spreadsheet ID.
- Require the target workbook marker, instance ID, exact headers, and compatible
  major version before any write.
- Incremental sync refreshes new dates, retryable failures, and a three-day
  overlap. Historical backfill is explicit and bounded.
- A historical correction recomputes affected 28-day future baseline windows
  and complete affected weeks.
- Successful-empty partitions can remove stale rows; failed, disabled, absent,
  or not-granted partitions preserve prior verified rows.
- No placeholder dates, imputation, AI prose, or nutrition decisions.
- Advance `_Sync Ledger` verified state only after readback succeeds.

Validation:

- `quick_validate.py`;
- script unit tests using sanitized fixtures;
- API unavailable/401/403/429/5xx/timeout/cursor cases;
- null versus zero versus successful-empty;
- no-data, provisional, sparse-week, and no-lookahead baselines;
- composite event-key collision tests;
- deterministic replay and partial-write detection;
- hard-deny test against the Master Nutrition workbook;
- marker/header/instance/version mismatch tests;
- fresh-agent status, incremental, bounded backfill, lifetime dry-run, and
  failure-mode forward tests against a sandbox workbook.

Exit gate: replacement skill passes validation without touching the live
workbooks.

### Phase 6 — Staged lifetime backfill and skill cutover

1. Dry-run the lifetime API paging and planned Sheet operations.
2. Backfill the dedicated workbook in bounded chunks.
3. Validate dates, source/event counts, hashes, statuses, nulls, explicit zeros,
   baseline sample counts, weekly denominators, and readback.
4. Replay the same range and require an idempotent no-op/equivalent result.
5. Update the new skill's local config with the final workbook ID.
6. Replace the installed old skill atomically, restart Codex, run status-only,
   then run a three-day sync.
7. Retain a non-discoverable rollback copy for a defined observation window.
   Rollback disables the new writer for diagnosis; it never recreates Oura tabs
   in the nutrition workbook.

Exit gate: API-to-Sheets sync is verified and the old MCP-based skill is no
longer active.

### Phase 7 — Web consumer update

1. Give the web skill owner the separate handoff document.
2. Fill in the final workbook ID, exact headers, contract version, feature
   version, freshness threshold, and sanitized examples.
3. Update `$will-nutrition-coach` to read the two workbooks independently and
   join exact dates in memory.
4. Run its missing/stale/provisional/partial/conflict/calorie-safety acceptance
   tests.

Exit gate: Oura is optional supporting evidence and ordinary nutrition logging
works without it.

### Phase 8 — Separate MCP adapter

1. Create a new `oura-data-mcp` project after API V1 stabilizes.
2. Expose granular tools that map directly to stable API routes.
3. Configure only API base URL and gateway token.
4. Validate tool schemas, pagination, error mapping, and absence of Oura/Google
   credentials or domain logic.

Exit gate: Codex can use Oura through MCP without coupling the API repository to
MCP.

## Rollback

- Code: return to the tagged/pre-refactor MCP implementation for diagnosis.
- API: stop the V1 process; no Sheet mutation occurs while stopped.
- Skill: disable or restore the non-discoverable backup, but do not target the
  nutrition workbook.
- Sheets: keep the new dedicated workbook intact for diagnosis; no destructive
  cutover is required in the Master Nutrition workbook.
- Web: remove/disable the optional Oura workbook configuration; nutrition
  behavior continues normally.

## Completion criteria

- One documented and tested API V1 JSON contract.
- Latest official Oura upstream details are represented behind one provider
  registry.
- API package contains no MCP or Google dependency.
- New skill contains no Oura MCP dependency and cannot write to the nutrition
  workbook.
- Dedicated workbook is private, compact, idempotent, and verified.
- Missing data is never zero or a placeholder.
- Active/workout calories never rewrite nutrition targets.
- Web skill uses Oura only when relevant and honors subjective overrides.
- Separate MCP adapter consumes API V1.
- All checks are run locally; no CI or pull request is required.
- Commits contain no coauthor metadata.
