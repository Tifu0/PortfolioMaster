# PortfolioMaster — Inventario fuente exacto

Inventario generado desde `PortfolioMaster-main.zip` el 22-10-2026. Incluye todos los ficheros no-directorio del ZIP y, para el código, símbolos top-level que un parser puede enumerar. Las descripciones son resumen funcional, no sustituyen la lectura del fichero. Los archivos de dependencias/lock y recursos binarios no contienen lógica de dominio.

**Total de archivos:** 99 (121 entradas en ZIP incluyendo directorios).

| Archivo | Líneas | Bytes aprox. | Símbolos principales | Responsabilidad / revisión |
|---|---:|---:|---|---|
| `.env.example` | 14 | 614 | — | Plantilla de variables de entorno; hay discrepancia en variable URL y valor batch de ejemplo. |
| `.gitignore` | 64 | 718 | — | Ignora secretos, bases de datos y artefactos locales (verificar reglas al migrar). |
| `LICENSE` | 674 | 35149 | — | Licencia y términos de redistribución. |
| `README.md` | 238 | 16102 | — | Visión funcional, setup, arquitectura, endpoints, tests y declaración local-first. |
| `backend/__init__.py` | 1 | 18 | — | Marcador de paquete Python. |
| `backend/api/__init__.py` | 1 | 14 | — | Marcador de paquete API. |
| `backend/api/main.py` | 1874 | 71608 | QuietConfigFilter, _broadcast_refresh_event, background_refresh_loop, lifespan, root, _to_float, _clean_str, _clean_opt_str, _instrument_to_dict, _quote_to_dict, InstrumentCreate, InstrumentUpdate, ImportConfirmRequest, get_positions… | Aplicación FastAPI y principal orquestador de rutas, refresh, SSE, import/export y backups. |
| `backend/tests/test_api.py` | 730 | 26467 | _clean_db, TestRoot, TestGetPositions, TestListInstruments, TestGetInstrument, TestCreateInstrument, TestUpdateInstrument, TestCheckYahooTicker, TestDeleteInstrument, TestImportFlow, TestGetMetrics, TestWipeDatabase, TestYtdEndpoints, TestConfig… | Tests de rutas y flujos de API. |
| `backend/tests/test_backup_api.py` | 295 | 10583 | _clean_db, TestExportEndpoints, TestBackupAndRestoreEndpoints, teardown_module | Tests de endpoints de export/backup/restore. |
| `frontend/.gitignore` | 41 | 480 | — | Exclusiones de artefactos del frontend. |
| `frontend/AGENTS.md` | 9 | 679 | — | Instrucciones contextuales para agentes que modifiquen frontend. |
| `frontend/README.md` | 36 | 1450 | — | Setup y scripts del frontend. |
| `frontend/app/backup/loading.tsx` | 45 | 2030 | BackupLoading | UI de carga para ruta de backup. |
| `frontend/app/backup/page.tsx` | 74 | 3171 | metadata, BackupPage | Página de backup/export. |
| `frontend/app/error.tsx` | 60 | 2346 | GlobalError | Error boundary de App Router. |
| `frontend/app/favicon.ico` | 0 | 0 | — | Favicon de la aplicación. |
| `frontend/app/globals.css` | 73 | 1527 | — | Estilos globales/Tailwind. |
| `frontend/app/import/loading.tsx` | 36 | 1606 | ImportLoading | UI de carga para importación. |
| `frontend/app/import/page.tsx` | 74 | 3088 | metadata, ImportPage | Página de importación. |
| `frontend/app/layout.tsx` | 32 | 845 | metadata, RootLayout | Layout raíz, metadata, fuentes y provider global. |
| `frontend/app/loading.tsx` | 74 | 3438 | Loading | Estado global de carga. |
| `frontend/app/not-found.tsx` | 33 | 1388 | NotFound | Página 404. |
| `frontend/app/page.tsx` | 145 | 5503 | WatchlistPage | Ruta principal/dashboard watchlist y carga inicial. |
| `frontend/app/sitemap.ts` | 26 | 585 | sitemap | Generación de sitemap en Next.js. |
| `frontend/components/BackupExportModal.tsx` | 621 | 27573 | BackupExportModal | Modal de export/backup/restore, con parte de lógica duplicada respecto a la vista completa. |
| `frontend/components/BackupExportView.tsx` | 659 | 29592 | BackupExportViewProps, BackupExportView | Página principal de export/backup/restore. |
| `frontend/components/HeaderNav.tsx` | 69 | 2404 | HeaderNav | Navegación y atajos/deep links para añadir/editar. |
| `frontend/components/ImportView.tsx` | 514 | 22198 | ImportView | Carga, preview y confirmación de importación; omite campos YTD en payload final. |
| `frontend/components/ManualEntryModal.tsx` | 1308 | 59781 | ManualEntryModal | Formularios de alta/edición, chequeo Yahoo y sincronización al renombrar ticker. |
| `frontend/components/MetricCards.tsx` | 275 | 11618 | MetricCards | Tarjetas KPI de métricas de portfolio. |
| `frontend/components/README.md` | 8 | 881 | — | Documentación de componentes frontend. |
| `frontend/components/WatchlistContent.tsx` | 386 | 13962 | WatchlistContent | Composición de tabla, KPIs, modal y feedback. |
| `frontend/components/WatchlistTable.tsx` | 2510 | 103989 | MIN_ROW_HEIGHT, DEFAULT_ROW_HEIGHT, MAX_ROW_HEIGHT, ROW_HEIGHT_STORAGE_KEY, SORTING_STORAGE_KEY, ToolbarConfig, DEFAULT_TOOLBAR_CONFIG, TOOLBAR_STORAGE_KEY, WatchlistTable | Tabla TanStack principal; filtros, sort, columnas, inline edit y acciones. Componente muy grande. |
| `frontend/context/PortfolioContext.tsx` | 407 | 13419 | PortfolioContextType, PortfolioProviderProps, PortfolioProvider, usePortfolio | Estado global, fetching, polling y SSE/progreso de refresh. |
| `frontend/eslint.config.mjs` | 18 | 465 | — | Configuración lint. |
| `frontend/lib/api.ts` | 494 | 14900 | ApiError, getPositions, getPositions, getInstruments, getInstruments, getInstrument, getInstrument, createInstrument, createInstrument, updateInstrument, updateInstrument, deleteInstrument, deleteInstrument, refreshInstrument… | Cliente HTTP frontend para endpoints del backend. |
| `frontend/lib/types.ts` | 303 | 6912 | QuoteStatus, Exchange, Instrument, Quote, Position, PositionsResponse, InstrumentsResponse, InstrumentDetailResponse, InstrumentCreateRequest, InstrumentUpdateRequest, CheckYahooResponse, RefreshBatchResponse, RefreshSingleResponse, ImportPreviewResponse… | Tipos TypeScript que reflejan modelos y respuesta API. |
| `frontend/next.config.ts` | 25 | 469 | — | Rewrite/config Next.js. |
| `frontend/package-lock.json` | 7434 | 252801 | — | Lockfile de dependencias npm; generado. |
| `frontend/package.json` | 30 | 1256 | — | Scripts y dependencias frontend. |
| `frontend/public/file.svg` | 1 | 391 | — | Asset SVG genérico; comprobar si se usa. |
| `frontend/public/globe.svg` | 1 | 1035 | — | Asset SVG genérico; comprobar si se usa. |
| `frontend/public/llms.txt` | 24 | 1597 | — | Documento de instrucciones/descubrimiento para crawlers LLM. |
| `frontend/public/next.svg` | 1 | 1375 | — | Logo boilerplate de Next.js; comprobar uso. |
| `frontend/public/robots.txt` | 8 | 208 | — | Directivas de indexación. |
| `frontend/public/sitemap.xml` | 8 | 229 | — | Sitemap estático; comprobar duplicación con app/sitemap.ts. |
| `frontend/public/vercel.svg` | 1 | 128 | — | Logo boilerplate Vercel; comprobar uso. |
| `frontend/public/window.svg` | 1 | 385 | — | Asset SVG genérico; comprobar uso. |
| `frontend/scripts/verify_analysis_date_column.mts` | 95 | 5065 | — | Verificación source-based de columna fecha de análisis. |
| `frontend/scripts/verify_api_cache.mts` | 37 | 1586 | — | Verificación source-based de comportamiento de cache del cliente API. |
| `frontend/scripts/verify_api_client.mts` | 33 | 744 | — | Verificación source-based del cliente API. |
| `frontend/scripts/verify_backup_export.mts` | 58 | 1648 | — | Verificación source-based de backup/export. |
| `frontend/scripts/verify_batch_auto_sync.mts` | 64 | 2458 | — | Verificación source-based de sincronización tras batch refresh. |
| `frontend/scripts/verify_phase3.mts` | 64 | 1664 | — | Verificaciones source-based agrupadas de fase 3. |
| `frontend/scripts/verify_phase4.mts` | 165 | 4757 | — | Verificaciones source-based agrupadas de fase 4. |
| `frontend/scripts/verify_phase5.mts` | 79 | 2374 | — | Verificaciones source-based agrupadas de fase 5. |
| `frontend/scripts/verify_phase6.mts` | 137 | 4792 | — | Verificaciones source-based agrupadas de fase 6. |
| `frontend/scripts/verify_phase7.mts` | 136 | 6027 | — | Verificaciones source-based agrupadas de fase 7. |
| `frontend/scripts/verify_portfolio_context.mts` | 73 | 2680 | — | Verificación source-based del contexto global. |
| `frontend/scripts/verify_responsive_headers_and_row_height.mts` | 151 | 6469 | — | Verificación de headers responsivos y altura de fila. |
| `frontend/scripts/verify_save_and_update_analysis_date.mts` | 157 | 6583 | — | Verificación source-based de guardar y actualizar fecha de análisis. |
| `frontend/scripts/verify_toolbar_and_backup_tab.mts` | 91 | 3691 | — | Verificación de toolbar y pestaña backup. |
| `frontend/scripts/verify_watchlist_fixes.mts` | 70 | 3324 | — | Verificación source-based de correcciones de la watchlist. |
| `frontend/tsconfig.json` | 34 | 666 | — | Configuración TS. |
| `pyproject.toml` | 26 | 547 | — | Configuración/empaquetado del proyecto Python y dependencias. |
| `pytest.ini` | 6 | 190 | — | Configuración de pytest; exige pytest-timeout para --timeout. |
| `requirements.txt` | 17 | 283 | — | Dependencias Python runtime y tests. |
| `run.bat` | 42 | 1429 | — | Lanzador de desarrollo Windows para API y frontend. |
| `src/portfoliomaster/__init__.py` | 0 | 0 | — | Marcador/metadata del paquete principal. |
| `src/portfoliomaster/backup/__init__.py` | 35 | 810 | — | Marcador del subpaquete de backup. |
| `src/portfoliomaster/backup/exporters.py` | 415 | 15807 | _serialize_date, _serialize_decimal, get_export_records, export_to_csv, export_to_excel, export_to_json, restore_from_json | Exportadores CSV/XLSX/JSON y restauración JSON; contiene varios hallazgos P0/P1. |
| `src/portfoliomaster/backup/sqlite_backup.py` | 236 | 8259 | get_backup_dir, get_target_db_path, create_sqlite_backup, rotate_backups, create_automatic_safety_backup, validate_sqlite_backup, restore_sqlite_backup, list_automatic_backups, restore_automatic_backup | Snapshot, validación, rotación y restauración SQLite. |
| `src/portfoliomaster/core/__init__.py` | 0 | 0 | — | Marcador del paquete de dominio. |
| `src/portfoliomaster/core/calculations.py` | 207 | 6647 | _to_decimal, _safe_div, _round, daily_variation, variation_since_analysis, ytd_variation, decline_to_target, is_target_reached, _is_valid_price | Fórmulas financieras con Decimal y flags de validez. |
| `src/portfoliomaster/core/config.py` | 460 | 14120 | get_refresh_interval, get_batch_size, get_yahoo_suffix | Configuración, mercados, suffixes, refresh/freshness. |
| `src/portfoliomaster/core/models.py` | 269 | 9132 | QuoteStatus, Exchange, Instrument, Quote, CalculationResult, RefreshRun, FreshnessConfig, ImportSummary | Modelos y enums Instrument/Quote/Exchange/QuoteStatus/Freshness. |
| `src/portfoliomaster/db/__init__.py` | 0 | 0 | — | Marcador del paquete DB. |
| `src/portfoliomaster/db/connection.py` | 71 | 2684 | get_connection, init_db | Conexiones SQLite y esquema manual. |
| `src/portfoliomaster/db/repository.py` | 310 | 10519 | _exchange_value, _sql_value, wipe_database, upsert_instrument, update_instrument_by_id, upsert_quote, get_all_instruments, get_instrument_by_ticker, get_quote_by_instrument_id, delete_instrument, _parse_date, _safe_decimal, _row_to_instrument | Persistencia CRUD/upsert/parse de datos; timestamp y null-clearing issues. |
| `src/portfoliomaster/ingest/__init__.py` | 0 | 0 | — | Marcador del paquete import. |
| `src/portfoliomaster/ingest/columns.py` | 91 | 2669 | normalize_header, map_columns | Mapeo/normalización de cabeceras de hojas. |
| `src/portfoliomaster/ingest/import_session.py` | 148 | 4996 | _is_blank, _cell_str, _cell_bool, _cell_date, import_spreadsheet | Orquestación parser, normalizador y rows de instrumentos. |
| `src/portfoliomaster/ingest/normalizer.py` | 45 | 1628 | normalize | Normalización ticker → provider symbol/mercado. |
| `src/portfoliomaster/ingest/parser.py` | 83 | 2870 | _detect_delimiter, _read_csv, parse_spreadsheet | Parser CSV y Excel. |
| `src/portfoliomaster/ingest/validator.py` | 21 | 704 | validate_row, detect_duplicates | Validación mínima de ticker/duplicados. |
| `src/portfoliomaster/providers/__init__.py` | 0 | 0 | — | Marcador de paquete de proveedores. |
| `src/portfoliomaster/providers/base.py` | 25 | 654 | MarketDataProvider | Interfaz abstracta MarketDataProvider. |
| `src/portfoliomaster/providers/mock_provider.py` | 31 | 1011 | MockProvider | Proveedor de datos mock para tests deterministas. |
| `src/portfoliomaster/providers/yahoo_adapter.py` | 383 | 15422 | _fi_get, YahooAdapter | Adaptador Yahoo/yfinance con lote, fallback e histórico. |
| `src/portfoliomaster/refresh/__init__.py` | 0 | 0 | — | Marcador de paquete refresh. |
| `src/portfoliomaster/refresh/batch_runner.py` | 68 | 2662 | BatchRunner | Ejecución en batches, retries y callbacks. |
| `tests/conftest.py` | 11 | 375 | test_db_isolation | Fixtures de pytest y configuración de import path/DB. |
| `tests/test_backup.py` | 290 | 10916 | isolated_env, TestSqliteBackup, TestExporters | Tests de backup, export/restore. |
| `tests/test_batch_runner.py` | 77 | 2593 | test_batch_runner_chunking, test_batch_runner_env_batch_size, test_refresh_interval_env, test_batch_runner_on_batch_complete_callback | Tests de batch runner. |
| `tests/test_calculations.py` | 86 | 3843 | test_daily_variation, test_variation_since_analysis, test_ytd_variation, test_decline_to_target, test_is_target_reached | Tests de cálculos financieros. |
| `tests/test_db.py` | 45 | 1472 | test_db_init_and_upsert | Tests repositorio SQLite. |
| `tests/test_ingest.py` | 128 | 4646 | _write_csv, test_spanish_decimal_parsing, test_comma_separated_user_sheet_columns, test_import_user_csv_does_not_report_missing_ticker, test_duplicate_tickers_are_warnings_not_errors, test_normalizer | Tests parser/import/normalización. |
| `tests/test_providers.py` | 28 | 1018 | test_mock_provider_batch, test_mock_provider_partial_failure | Tests de providers/MockProvider. |
| `tests/test_refresh_functionality.py` | 191 | 6475 | _reset_db, _dump_quote, test_refresh_functionality_with_mock_data, test_refresh_with_yfinance_prints_quote, test_epa_rms_normalizes_to_paris_suffix, test_bme_vis_normalizes_to_madrid_suffix, test_us_symbols_have_no_suffix, test_already_suffixed_symbol_is_respected, test_unknown_prefix_falls_back_to_bare_ticker, test_lon_azn_normalizes_to_london_l_suffix, test_she_normalizes_to_shenzhen_suffix, test_get_yahoo_suffix_and_normalize_with_currency | Tests refresh/YahooAdapter; necesita yfinance. |
