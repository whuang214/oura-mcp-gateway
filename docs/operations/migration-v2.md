# Oura v2 staging, cutover, and rollback

No live cutover occurs without explicit user approval.

The first staged backfill and private live comparison are complete. Personal
health metrics and workbook identifiers are intentionally excluded from this
public repository and its distributions.

## Non-destructive staging

1. Leave `Oura Daily Metrics` unchanged as the legacy/raw comparison source.
2. Create `Oura Daily Metrics v2`, `Oura Workouts v2`, `Oura Sessions v2`,
   `Oura Sync Audit v2`, and `Oura Raw Provenance v2`.
3. Backfill the approved range through the versioned MCP transformation.
4. Upsert daily rows by Date and children by Oura source ID.
5. Reread and verify dates, statuses, units, null/zero distinctions, child
   aggregates, duplicates, and source references.
6. Compare every private acceptance case named in the implementation handoff
   with the legacy source; do not copy personal metrics into source control.

For a local staging artifact, the exporter requires an ignored, protected JSON
destination and never prints health rows to stdout:

```powershell
uv run python scripts/export_v2_staging.py --start YYYY-MM-DD --end YYYY-MM-DD `
  --output .private/staging-v2.json
```

It refuses output outside the project `.private` directory.

## Proposed cutover after approval

1. Pause the desktop sync writer.
2. Create a private rollback bundle containing the exact repository tree,
   installed `oura-sync` skill/local config, and workbook tab metadata. Record
   its SHA-256 and require either a clean Git commit or that verified bundle
   before continuing.
3. Rerun a final recent overlap into staging and validate readback.
4. Rename legacy `Oura Daily Metrics` to
   `Oura Raw Export Legacy 2026-07` without deleting it.
5. Apply the exact staging-to-final mapping:
   - `Oura Daily Metrics v2` → `Oura Daily Metrics`
   - `Oura Workouts v2` → `Oura Workouts`
   - `Oura Sessions v2` → `Oura Sessions`
   - `Oura Sync Audit v2` → `Oura Sync Audit`
   - `Oura Raw Provenance v2` → `Oura Raw Provenance`
6. Change `Migration mode` to `final` in the installed local config and retain
   both final and staging names there for rollback.
7. Update the installed desktop contract and web-consumer handoff to the final
   names, restart Codex, run one bounded sync, and validate again.

## Rollback

1. Pause the writer.
2. Rename the failed curated tab to `Oura Daily Metrics v2 Failed`.
3. Rename `Oura Raw Export Legacy 2026-07` back to `Oura Daily Metrics`.
4. Restore the installed skill and local config from the verified private
   rollback bundle, set `Migration mode` back to `staging`, and restart Codex.
5. No source tab is deleted until the curated contract has operated and been
   verified for an agreed retention period.
