---
name: oura-sync
description: Synchronize and stage analysis-ready Oura daily, workout, session, audit, and provenance data from the local Oura MCP server into a configured Google Sheet. Use for Oura sync, backfill, refresh, staging migration, coverage inspection, or validation requests.
---

# Oura Sync

Synchronize the versioned Oura analysis contract into only the Oura-owned tabs
named in `references/local-config.md`. Keep Oura retrieval/Sheet mutation
separate from nutrition coaching.

Before any workbook read or write, read completely:

- `references/local-config.md`
- `references/sheet-contract.md`

Stop with setup instructions if local configuration is missing or contains a
placeholder. Never load the example as runtime configuration.

## Boundaries

- Use the local `oura` MCP server only from Codex desktop.
- Write only configured Oura-owned tabs. Never modify nutrition, target, goal,
  food, workout-log, weigh-in, or reflection tabs.
- In staging mode, never clear, rename, delete, or overwrite the current final
  `Oura Daily Metrics` tab.
- Preserve null as blank. Write zero only from an explicit source zero or a
  successfully empty endpoint.
- Never expose credentials, token values, raw authorization responses, or stack
  traces.
- Active/workout calories are context only. Never eat them back automatically
  or use them alone to rewrite nutrition targets.
- Subjective pain, soreness, illness, energy, and jump feel override device
  scores.

## Workflow

1. Read workbook metadata and resolve every configured Oura tab and numeric
   `sheetId`. Create only missing Oura staging/final structures allowed by the
   configured migration mode.
2. Read exact row-2 headers and the hidden audit sync-state cells. Stop on a
   schema mismatch; never shift fields by position after header resolution.
3. Read bounded existing bodies with formulas/effective values. Detect duplicate
   daily dates, workout IDs, session IDs, and provenance dates.
4. For status-only requests, call `get_oura_service_status` and report schema,
   scan watermark, coverage, provisional/error rows, unresolved dates,
   duplicates, and last verified sync age. Do not retrieve health data.
5. For a sync, build `existing_coverage` from curated dates/statuses plus
   confirmed no-data dates in hidden state, represented with status `No Data`.
   Add every hidden unresolved date using its latest audit status/errors,
   defaulting to `Sync Error` when no richer row exists. Attach latest
   structured retryable audit errors even to core-Complete dates so optional
   transient failures are retried. Do not send source IDs. Ordinary
   incremental runs retrieve new dates, retryable failures, and a three-day
   overlap; historical absent dates require an explicit bounded backfill.
6. Call `sync_oura_daily_data`. Preserve original arguments while following
   `plan.continuation_start_date` until `has_more` is false. Require
   `transformed.schema_version=2.0.0`; do not rebuild v2 calculations from
   legacy fields when the transformed payload is unavailable.
7. Reconcile transformed tables:
   - daily rows by `effective_date`;
   - workouts by `source_id`;
   - sessions by `source_id`;
   - audit by sync-run ID plus date;
   - provenance by sync-run ID plus date.
   Treat each successfully retrieved date/section as an authoritative
   replacement partition, not an append-only upsert. A resolved daily `No Data`
   date removes any former Provisional daily row. Successful-empty workout or
   session coverage removes stale children for that date. Never prune a child
   partition whose section is error/missing/disabled. Preserve old daily values
   only for columns owned by a failed section, using the section-column mapping
   in the Sheet contract; do not preserve unrelated blanks.
8. Write a curated daily row only when at least one core section exists, plus
   the current provisional day. Put finalized no-data and unresolved attempts
   in audit/state, never as empty analytical rows. Optional errors are warnings
   and never downgrade core-complete status.
9. Keep raw workout activity labels unchanged. Leave `Mapped Category` blank
   unless an approved deterministic mapping exists. Keep active calories
   separate from workout-calorie totals.
10. Batch coherent writes, use `=DATE(year,month,day)` for Sheet dates, and sort
    bodies by Date plus their stable ID key. Never append a duplicate key.
11. Reread row 2 and every changed row. Validate exact values, formulas, keys,
    statuses, null/zero behavior, child-to-daily count/duration/calorie
    agreement, schema versions, and that non-Oura tabs were untouched.
12. Replay the same deterministic body once if readback suggests a partial
    write. If it still differs, report exact keys and do not claim success.
13. Only after validation passes, update hidden sync state with scanned ranges,
    confirmed no-data dates, unresolved dates, and the verified timestamp.

## Migration guard

When `Migration mode` is `staging`, write only versioned staging tabs and compare
them with the legacy source. Present cutover and rollback steps, then stop for
explicit approval before any rename, clear, delete, or final-tab replacement.

## Reporting

Report request/retrieval ranges, page count, inserted/refreshed keys, confirmed
no-data dates, unresolved dates, Complete/Partial/Provisional/Sync Error dates,
optional warnings, child counts, duplicates, staging comparison results, and
whether readback validation passed. Never claim success before validation.
