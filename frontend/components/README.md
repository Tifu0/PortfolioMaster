# Components directory
This folder holds reusable React components for the PortfolioMaster frontend:
- **WatchlistTable**: Main interactive watchlist with pre-computed returns, column resizing, inline thesis editing, search, filters, and custom toolbar.
- **MetricCards**: Portfolio summary KPI cards (total positions, top gainer, top loser, average variation).
- **ManualEntryModal**: Interactive modal for registering new instruments (with hidden analysis price & auto-resolution) or editing existing ones (with explicit ticker rename sync & live Yahoo lookups).
- **ImportView**: Spreadsheet import with preview, anomaly detection, and database commit.
- **BackupExportView & BackupExportModal**: Multi-format exports (Excel, CSV, JSON), atomic SQLite snapshots, and integrity-checked restoration.
- **HeaderNav**: App top navigation bar and active runtime engine status badge.
