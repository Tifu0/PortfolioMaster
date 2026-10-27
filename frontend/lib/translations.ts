export type Language = 'en' | 'es';

export const translations = {
  en: {
    // Navigation & Header
    watchlist: 'Watchlist',
    addInstrument: 'Add Instrument',
    import: 'Import',
    backupExport: 'Backup & Export',
    fastApiStatus: 'FastAPI',
    signIn: 'Sign In',
    signOut: 'Sign Out',
    guestUser: 'Guest User',
    switchAccount: 'Switch Account',

    // Watchlist Content
    mainWatchlist: 'Main Watchlist',
    mainWatchlistSubtitle: 'Monitored instruments, real-time market quotes, and server-calculated variations.',
    updatingBatch: 'Updating batch...',
    startingUpdate: 'Starting update...',
    autoSync: 'Auto',
    batch: 'Batch',
    refreshInProgress: 'Batch update in progress on server...',
    autoRefreshEvery: 'Automatic refresh every {seconds}s in batches of {size} tickers',

    // Metric Cards
    totalPortfolioValue: 'Total Portfolio Value',
    totalInvested: 'Total Invested',
    totalGainLoss: 'Total Gain / Loss',
    overallReturn: 'Overall Return',
    topPerformer: 'Top Performer',
    worstPerformer: 'Worst Performer',
    allTimePnL: 'All-time unrealized P&L',
    basedOnCost: 'Based on purchase cost',
    bestDailyVar: 'Best daily variation',
    worstDailyVar: 'Worst daily variation',
    noInstruments: 'No instruments',
    noData: 'No data',

    // Watchlist Table Columns
    colAnalysisDate: 'Analysis Date',
    colTicker: 'Ticker',
    colCompany: 'Company',
    colPrice: 'Price',
    colCurrency: 'Currency',
    colExchange: 'Exchange',
    colDayVar: 'Day Var. %',
    colYtdVar: 'YTD Var. %',
    colAnalysisPrice: 'Analysis Ref. Price',
    colAnalysisVar: 'Var. vs Analysis %',
    colTargetPrice: 'Target Price',
    colTargetDist: 'Target Dist. %',
    colActions: 'Actions',

    // Table Toolbar
    searchPlaceholder: 'Search ticker or company...',
    filterCurrency: 'Filter currency',
    allCurrencies: 'All currencies',
    rowHeight: 'Row Height',
    columns: 'Columns',
    resetDefaults: 'Reset to defaults',
    importValues: 'Import values',
    refreshQuotes: 'Refresh quotes',
    refreshingQuotes: 'Refreshing...',
    addTicker: 'Add',

    // Row Height Popover
    rowHeightController: 'Row Height Controller',
    rowHeightInPixels: 'Row height in pixels',
    minHeightReached: 'Minimum height reached',
    preview: 'Preview',
    apply: 'Apply',

    // Columns Visibility Popover
    visibleColumns: 'Visible Columns',
    columnsDesc: 'Toggle columns to display in table',

    // Table states
    emptyWatchlistTitle: 'No instruments found',
    emptyWatchlistDesc: 'Add your first instrument or import from Excel/CSV to start tracking.',
    loadingQuotes: 'Loading quotes and metrics...',
    signInPrompt: 'Sign in to view your portfolio',

    // Actions & Tooltips
    editTooltip: 'Edit instrument',
    refreshTooltip: 'Refresh quote',
    deleteTooltip: 'Delete instrument',
    deleteConfirmTitle: 'Delete instrument?',
    deleteConfirmDesc: 'Are you sure you want to delete {ticker}? This action cannot be undone.',
    confirmDelete: 'Delete',
    cancel: 'Cancel',

    // Manual Entry Modal
    modalAddTitle: 'Add Instrument',
    modalEditTitle: 'Edit Instrument',
    tickerSymbol: 'Ticker Symbol',
    companyName: 'Company Name',
    exchange: 'Exchange',
    currency: 'Currency',
    currentPrice: 'Current Price',
    analysisDate: 'Analysis Date',
    analysisRefPrice: 'Analysis Ref. Price',
    targetPrice: 'Target Price',
    saveChanges: 'Save Changes',
    saveAndUpdateDate: 'Save + Update Date',
    confirmTickerChange: 'Confirm change and update data',
    addInstrumentBtn: 'Add Instrument',
    saving: 'Saving...',
    fetchingQuote: 'Fetching market quote...',
    tickerChangeWarning: 'Changing the ticker symbol will fetch new market data from Yahoo Finance and replace existing quote history.',

    // Backup & Export View
    backupTitle: 'Backup & Export',
    backupSubtitle: 'Export your watchlist to Excel, CSV, or JSON and manage database backups.',
    exportWatchlist: 'Export Watchlist',
    downloadDatabase: 'Download Database Backup',
    restoreDatabase: 'Restore Database',
    restoreConfirmTitle: 'Restore database?',
    restoreConfirmDesc: 'This will replace the current database with the selected backup file.',
    exportExcel: 'Export to Excel (.xlsx)',
    exportCsv: 'Export to CSV',
    exportJson: 'Export to JSON',
    backupSnapshots: 'Database Snapshots',
    createBackup: 'Create Backup Snapshot',
    restoreLocalFile: 'Restore from Local File',

    // Import View
    importTitle: 'Import Watchlist',
    importSubtitle: 'Upload your portfolio data from an Excel (.xlsx) or CSV file.',
    uploadFile: 'Upload File',
    dragDropFile: 'Drag & drop your file here or click to browse',
    previewTable: 'Preview Data',
    confirmImportBtn: 'Confirm and Import',
    downloadTemplate: 'Download Example Template',

    // Auth Modal
    authTitle: 'Welcome to PortfolioMaster',
    authSubtitle: 'Sign in or create an account to sync your watchlist across devices.',
    email: 'Email address',
    password: 'Password',
    loginBtn: 'Sign In',
    signupBtn: 'Create Account',
    magicLinkBtn: 'Send Magic Link',

    // Error Page
    errorTitle: 'An unexpected error occurred',
    errorDefaultMsg: 'An error occurred while rendering portfolio data.',
    retry: 'Retry',
    backHome: 'Back to Home',
    translationErrorTitle: 'Possible browser translation interference (Google Translate):',
    translationErrorDesc: 'Google Translate directly mutates text elements on the page, conflicting with real-time quote and metric updates.',
    translationErrorHint: 'Tip: Disable auto-translate for this site in your browser address bar and click Retry.',
  },
  es: {
    // Navigation & Header
    watchlist: 'Cartera',
    addInstrument: 'Añadir Valor',
    import: 'Importar',
    backupExport: 'Copia & Exportación',
    fastApiStatus: 'FastAPI',
    signIn: 'Iniciar Sesión',
    signOut: 'Cerrar Sesión',
    guestUser: 'Usuario Invitado',
    switchAccount: 'Cambiar de Cuenta',

    // Watchlist Content
    mainWatchlist: 'Cartera Principal',
    mainWatchlistSubtitle: 'Valores registrados, cotizaciones en tiempo real y variaciones calculadas en el servidor.',
    updatingBatch: 'Actualizando lote...',
    startingUpdate: 'Iniciando actualización...',
    autoSync: 'Auto',
    batch: 'Batch',
    refreshInProgress: 'Actualización en lote en progreso en el servidor...',
    autoRefreshEvery: 'Actualización automática cada {seconds}s en lotes de {size} tickers',

    // Metric Cards
    totalPortfolioValue: 'Valor Total Cartera',
    totalInvested: 'Inversión Total',
    totalGainLoss: 'Ganancia / Pérdida Total',
    overallReturn: 'Rendimiento Global',
    topPerformer: 'Mejor Valor',
    worstPerformer: 'Peor Valor',
    allTimePnL: 'P&L no realizado acumulado',
    basedOnCost: 'Basado en coste de adquisición',
    bestDailyVar: 'Mayor variación diaria',
    worstDailyVar: 'Menor variación diaria',
    noInstruments: 'Sin valores',
    noData: 'Sin datos',

    // Watchlist Table Columns
    colAnalysisDate: 'Fecha Análisis',
    colTicker: 'Ticker',
    colCompany: 'Nombre Empresa',
    colPrice: 'Precio',
    colCurrency: 'Divisa',
    colExchange: 'Bolsa',
    colDayVar: 'Var. Día %',
    colYtdVar: 'Var. YTD %',
    colAnalysisPrice: 'Precio Ref. Análisis',
    colAnalysisVar: 'Var. vs Análisis %',
    colTargetPrice: 'Objetivo / Target',
    colTargetDist: 'Distancia Target %',
    colActions: 'Acciones',

    // Table Toolbar
    searchPlaceholder: 'Buscar ticker o empresa...',
    filterCurrency: 'Filtrar divisa',
    allCurrencies: 'Todas las divisas',
    rowHeight: 'Altura filas',
    columns: 'Columnas',
    resetDefaults: 'Restaurar vista por defecto',
    importValues: 'Importar valores',
    refreshQuotes: 'Refrescar cotizaciones',
    refreshingQuotes: 'Refrescando...',
    addTicker: 'Añadir',

    // Row Height Popover
    rowHeightController: 'Controlador de Altura de Filas',
    rowHeightInPixels: 'Altura de fila en píxeles',
    minHeightReached: 'Altura mínima alcanzada',
    preview: 'Vista previa',
    apply: 'Aplicar',

    // Columns Visibility Popover
    visibleColumns: 'Columnas Visibles',
    columnsDesc: 'Selecciona las columnas que deseas mostrar',

    // Table states
    emptyWatchlistTitle: 'No se encontraron valores',
    emptyWatchlistDesc: 'Añade tu primer valor o importa desde Excel/CSV para empezar el seguimiento.',
    loadingQuotes: 'Cargando cotizaciones y métricas...',
    signInPrompt: 'Inicia sesión para ver tu cartera',

    // Actions & Tooltips
    editTooltip: 'Editar instrumento',
    refreshTooltip: 'Refrescar cotización',
    deleteTooltip: 'Eliminar instrumento',
    deleteConfirmTitle: '¿Eliminar instrumento?',
    deleteConfirmDesc: '¿Estás seguro de que deseas eliminar {ticker}? Esta acción no se puede deshacer.',
    confirmDelete: 'Eliminar',
    cancel: 'Cancelar',

    // Manual Entry Modal
    modalAddTitle: 'Añadir Instrumento',
    modalEditTitle: 'Editar Instrumento',
    tickerSymbol: 'Símbolo Ticker',
    companyName: 'Nombre de Empresa',
    exchange: 'Bolsa / Mercado',
    currency: 'Divisa',
    currentPrice: 'Precio Actual',
    analysisDate: 'Fecha de Análisis',
    analysisRefPrice: 'Precio Ref. Análisis',
    targetPrice: 'Precio Objetivo / Target',
    saveChanges: 'Guardar Cambios',
    saveAndUpdateDate: 'Guardar + Actualizar Fecha',
    confirmTickerChange: 'Confirmar cambio y actualizar datos',
    addInstrumentBtn: 'Añadir Instrumento',
    saving: 'Guardando...',
    fetchingQuote: 'Obteniendo cotización de Yahoo Finance...',
    tickerChangeWarning: 'Cambiar el símbolo ticker obtendrá nuevos datos de Yahoo Finance y reemplazará el historial existente.',

    // Backup & Export View
    backupTitle: 'Copias de Seguridad y Exportación',
    backupSubtitle: 'Exporta tu cartera a Excel, CSV o JSON y gestiona copias de seguridad de la base de datos.',
    exportWatchlist: 'Exportar Cartera',
    downloadDatabase: 'Descargar Base de Datos',
    restoreDatabase: 'Restaurar Base de Datos',
    restoreConfirmTitle: '¿Restaurar base de datos?',
    restoreConfirmDesc: 'Esto reemplazará la base de datos actual con el archivo seleccionado.',
    exportExcel: 'Exportar a Excel (.xlsx)',
    exportCsv: 'Exportar a CSV',
    exportJson: 'Exportar a JSON',
    backupSnapshots: 'Instantáneas de la Base de Datos',
    createBackup: 'Crear Copia de Seguridad',
    restoreLocalFile: 'Restaurar desde archivo local',

    // Import View
    importTitle: 'Importar Cartera',
    importSubtitle: 'Sube tus datos de cartera desde un archivo Excel (.xlsx) o CSV.',
    uploadFile: 'Subir Archivo',
    dragDropFile: 'Arrastra y suelta tu archivo aquí o haz clic para seleccionarlo',
    previewTable: 'Previsualizar Datos',
    confirmImportBtn: 'Confirmar e Importar',
    downloadTemplate: 'Descargar plantilla de ejemplo',

    // Auth Modal
    authTitle: 'Bienvenido a PortfolioMaster',
    authSubtitle: 'Inicia sesión o regístrate para sincronizar tu cartera en todos tus dispositivos.',
    email: 'Correo electrónico',
    password: 'Contraseña',
    loginBtn: 'Iniciar Sesión',
    signupBtn: 'Crear Cuenta',
    magicLinkBtn: 'Enviar Enlace Mágico',

    // Error Page
    errorTitle: 'Ha ocurrido un error inesperado',
    errorDefaultMsg: 'Se produjo un fallo al renderizar los datos del portfolio.',
    retry: 'Reintentar',
    backHome: 'Volver al inicio',
    translationErrorTitle: 'Posible interferencia del traductor del navegador (Google Traductor):',
    translationErrorDesc: 'El traductor automático de Google modifica directamente los elementos de texto en la pantalla, lo que genera conflictos con las actualizaciones en vivo de cotizaciones y métricas.',
    translationErrorHint: '💡 Solución: Desactiva la traducción automática para esta página desde la barra de direcciones de Chrome y pulsa Reintentar.',
  },
} as const;

export type TranslationKey = keyof typeof translations.en;
