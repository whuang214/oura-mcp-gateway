# Local Oura Sheet Configuration

Copy this file to `local-config.md` and replace every placeholder.
`local-config.md` is intentionally ignored by Git.

- Spreadsheet ID: `<YOUR_GOOGLE_SHEET_ID>`
- Spreadsheet display name: `<YOUR_SPREADSHEET_NAME>`
- Migration mode: `staging`
- Final daily tab: `Oura Daily Metrics`
- Final workouts tab: `Oura Workouts`
- Final sessions tab: `Oura Sessions`
- Final audit tab: `Oura Sync Audit`
- Final provenance tab: `Oura Raw Provenance`
- Staging daily tab: `Oura Daily Metrics v2`
- Staging workouts tab: `Oura Workouts v2`
- Staging sessions tab: `Oura Sessions v2`
- Staging audit tab: `Oura Sync Audit v2`
- Staging provenance tab: `Oura Raw Provenance v2`

Use `staging` until an explicitly approved cutover. Never place OAuth
credentials or tokens in this file.
