'use client';

import React, { useCallback, useEffect, useState, useRef } from 'react';
import {
  Download,
  Database,
  FileSpreadsheet,
  FileText,
  FileJson,
  Upload,
  History,
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  Loader2,
  ShieldCheck,
  FileDown,
  Check,
  Info,
  X,
} from 'lucide-react';
import {
  exportWatchlist,
  downloadDatabaseBackup,
  getBackupList,
  restoreBackupFile,
  restoreLocalBackup,
} from '@/lib/api';
import type { BackupItem } from '@/lib/types';

interface ToastData {
  id: number;
  type: 'success' | 'error' | 'info';
  message: string;
}

function ToastItem({ toast, onDismiss }: { toast: ToastData; onDismiss: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, 5000);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  const styles = {
    success: 'bg-emerald-950/90 border-emerald-500/30 text-emerald-200',
    error: 'bg-rose-950/90 border-rose-500/30 text-rose-200',
    info: 'bg-blue-950/90 border-blue-500/30 text-blue-200',
  };

  const icons = {
    success: <Check className="w-4 h-4 text-emerald-400 shrink-0" />,
    error: <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />,
    info: <Info className="w-4 h-4 text-blue-400 shrink-0" />,
  };

  return (
    <div
      className={`flex items-center gap-3 px-4 py-3 rounded-xl border text-xs shadow-2xl backdrop-blur-md transition-all animate-in slide-in-from-top-2 ${styles[toast.type]}`}
    >
      {icons[toast.type]}
      <span className="flex-1 font-medium">{toast.message}</span>
      <button
        onClick={onDismiss}
        className="text-zinc-400 hover:text-zinc-200 p-1 rounded transition-colors"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

export interface BackupExportViewProps {
  onSuccess?: (message: string) => void;
  onError?: (message: string) => void;
  onDataRestored?: () => void;
}

export function BackupExportView({
  onSuccess: propOnSuccess,
  onError: propOnError,
  onDataRestored: propOnDataRestored,
}: BackupExportViewProps = {}) {
  const [activeTab, setActiveTab] = useState<'export' | 'backup'>('export');

  // Export loading states
  const [exportingFormat, setExportingFormat] = useState<string | null>(null);
  const [downloadingDb, setDownloadingDb] = useState(false);

  // Backup list state
  const [backups, setBackups] = useState<BackupItem[]>([]);
  const [loadingBackups, setLoadingBackups] = useState(false);

  // File restore state
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [restoringFile, setRestoringFile] = useState(false);
  const [confirmFileRestore, setConfirmFileRestore] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Local backup restore state
  const [backupToRestore, setBackupToRestore] = useState<BackupItem | null>(null);
  const [restoringLocal, setRestoringLocal] = useState(false);

  // Internal toast notification state
  const [toasts, setToasts] = useState<ToastData[]>([]);
  const toastIdRef = useRef(0);

  const addToast = useCallback(
    (type: ToastData['type'], message: string) => {
      const id = ++toastIdRef.current;
      setToasts((prev) => [...prev, { id, type, message }]);
      if (type === 'success' && propOnSuccess) propOnSuccess(message);
      if (type === 'error' && propOnError) propOnError(message);
    },
    [propOnSuccess, propOnError]
  );

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // Load local backups when switching to backup tab
  const fetchBackups = useCallback(async () => {
    setLoadingBackups(true);
    try {
      const res = await getBackupList();
      setBackups(res.backups || []);
    } catch (err: unknown) {
      console.warn('Could not load local backups:', err);
    } finally {
      setLoadingBackups(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'backup') {
      fetchBackups();
    }
  }, [activeTab, fetchBackups]);

  // 1. Export Handlers
  const handleExport = async (format: 'csv' | 'excel' | 'json') => {
    setExportingFormat(format);
    try {
      await exportWatchlist(format);
      addToast('success', `Exportación a ${format.toUpperCase()} descargada correctamente.`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      addToast('error', `Error al exportar a ${format.toUpperCase()}: ${msg}`);
    } finally {
      setExportingFormat(null);
    }
  };

  const handleDownloadDbSnapshot = async () => {
    setDownloadingDb(true);
    try {
      await downloadDatabaseBackup();
      addToast('success', 'Copia atómica de la base de datos SQLite (.db) descargada correctamente.');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      addToast('error', `Error al descargar la base de datos: ${msg}`);
    } finally {
      setDownloadingDb(false);
    }
  };

  // 2. Upload / Restore File Handlers
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setSelectedFile(e.target.files[0]);
      setConfirmFileRestore(false);
    }
  };

  const handleExecuteFileRestore = async () => {
    if (!selectedFile) return;
    setRestoringFile(true);
    try {
      const res = await restoreBackupFile(selectedFile);
      addToast(
        'success',
        `Restauración completada con éxito. Se restauraron ${res.restored_instruments ?? 'todos los'} instrumentos.`
      );
      setSelectedFile(null);
      setConfirmFileRestore(false);
      await fetchBackups();
      propOnDataRestored?.();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      addToast('error', `Fallo en la restauración: ${msg}`);
    } finally {
      setRestoringFile(false);
    }
  };

  // 3. Local Backup Restore Handlers
  const handleExecuteLocalRestore = async () => {
    if (!backupToRestore) return;
    setRestoringLocal(true);
    try {
      const res = await restoreLocalBackup(backupToRestore.filename);
      addToast(
        'success',
        `Base de datos restaurada correctamente desde "${backupToRestore.filename}" (${res.restored_instruments ?? 0} instrumentos).`
      );
      setBackupToRestore(null);
      await fetchBackups();
      propOnDataRestored?.();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      addToast('error', `Fallo al restaurar la copia de seguridad: ${msg}`);
    } finally {
      setRestoringLocal(false);
    }
  };

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

  const formatDate = (isoString: string): string => {
    try {
      const d = new Date(isoString);
      return d.toLocaleString('es-ES', {
        year: 'numeric',
        month: 'short',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      });
    } catch {
      return isoString;
    }
  };

  return (
    <div className="space-y-6">
      {/* Toast Notification Container */}
      {toasts.length > 0 && (
        <div className="fixed top-20 right-4 z-[200] flex flex-col gap-2 max-w-sm w-full pointer-events-auto">
          {toasts.map((t) => (
            <ToastItem key={t.id} toast={t} onDismiss={() => dismissToast(t.id)} />
          ))}
        </div>
      )}

      {/* Tabs Switcher Card */}
      <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 backdrop-blur shadow-xl overflow-hidden">
        <div className="flex border-b border-zinc-800 px-6 bg-zinc-950/60">
          <button
            onClick={() => setActiveTab('export')}
            className={`py-4 px-5 text-sm font-medium border-b-2 transition-all flex items-center gap-2 cursor-pointer ${
              activeTab === 'export'
                ? 'border-emerald-500 text-emerald-400 bg-emerald-500/[0.04]'
                : 'border-transparent text-zinc-400 hover:text-zinc-200 hover:border-zinc-700'
            }`}
          >
            <FileDown className="w-4 h-4" />
            <span>Exportar Cartera (.xlsx, .csv, .json)</span>
          </button>
          <button
            onClick={() => setActiveTab('backup')}
            className={`py-4 px-5 text-sm font-medium border-b-2 transition-all flex items-center gap-2 cursor-pointer ${
              activeTab === 'backup'
                ? 'border-blue-500 text-blue-400 bg-blue-500/[0.04]'
                : 'border-transparent text-zinc-400 hover:text-zinc-200 hover:border-zinc-700'
            }`}
          >
            <Database className="w-4 h-4" />
            <span>Base de Datos y Restauración (.db)</span>
          </button>
        </div>

        {/* View Content Body */}
        <div className="p-6 sm:p-8">
          {activeTab === 'export' ? (
            /* TAB 1: EXPORT WATCHLIST */
            <div className="space-y-6 max-w-5xl">
              <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-xs sm:text-sm flex items-start gap-3">
                <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
                <span className="leading-relaxed">
                  Los formatos <strong>Excel</strong> y <strong>CSV</strong> son 100% compatibles con el importador de PortfolioMaster.
                  Puedes exportar tu cartera completa y volver a importarla en cualquier momento conservando instrumentos, precios objetivos y notas de análisis.
                </span>
              </div>

              {/* Action Cards Grid */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                {/* Excel .xlsx */}
                <div className="rounded-2xl border border-zinc-800 bg-zinc-950/70 p-6 flex flex-col justify-between hover:border-emerald-500/40 transition-all group">
                  <div>
                    <div className="w-12 h-12 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 mb-4 group-hover:scale-105 transition-transform">
                      <FileSpreadsheet className="w-6 h-6" />
                    </div>
                    <h3 className="text-base font-semibold text-white">Excel (.xlsx)</h3>
                    <p className="text-xs text-zinc-400 mt-2 leading-relaxed">
                      Hoja de cálculo estructurada con formato profesional, cotizaciones activas, variaciones porcentuales calculadas y notas de análisis.
                    </p>
                  </div>
                  <button
                    onClick={() => handleExport('excel')}
                    disabled={exportingFormat !== null}
                    className="mt-6 w-full h-10 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs sm:text-sm font-medium flex items-center justify-center gap-2 transition-colors disabled:opacity-50 cursor-pointer"
                  >
                    {exportingFormat === 'excel' ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>Generando Excel...</span>
                      </>
                    ) : (
                      <>
                        <Download className="w-4 h-4" />
                        <span>Descargar Excel</span>
                      </>
                    )}
                  </button>
                </div>

                {/* CSV */}
                <div className="rounded-2xl border border-zinc-800 bg-zinc-950/70 p-6 flex flex-col justify-between hover:border-blue-500/40 transition-all group">
                  <div>
                    <div className="w-12 h-12 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 mb-4 group-hover:scale-105 transition-transform">
                      <FileText className="w-6 h-6" />
                    </div>
                    <h3 className="text-base font-semibold text-white">CSV (.csv)</h3>
                    <p className="text-xs text-zinc-400 mt-2 leading-relaxed">
                      Texto plano estándar codificado en UTF-8 con delimitador por comas. Compatible universalmente con Excel, Google Sheets y scripts automatizados.
                    </p>
                  </div>
                  <button
                    onClick={() => handleExport('csv')}
                    disabled={exportingFormat !== null}
                    className="mt-6 w-full h-10 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs sm:text-sm font-medium flex items-center justify-center gap-2 transition-colors disabled:opacity-50 cursor-pointer"
                  >
                    {exportingFormat === 'csv' ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>Generando CSV...</span>
                      </>
                    ) : (
                      <>
                        <Download className="w-4 h-4" />
                        <span>Descargar CSV</span>
                      </>
                    )}
                  </button>
                </div>

                {/* JSON */}
                <div className="rounded-2xl border border-zinc-800 bg-zinc-950/70 p-6 flex flex-col justify-between hover:border-purple-500/40 transition-all group">
                  <div>
                    <div className="w-12 h-12 rounded-xl bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400 mb-4 group-hover:scale-105 transition-transform">
                      <FileJson className="w-6 h-6" />
                    </div>
                    <h3 className="text-base font-semibold text-white">JSON (.json)</h3>
                    <p className="text-xs text-zinc-400 mt-2 leading-relaxed">
                      Volcado estructurado completo con esquema versionado, metadatos, cotizaciones en crudo y todas las propiedades de cada instrumento.
                    </p>
                  </div>
                  <button
                    onClick={() => handleExport('json')}
                    disabled={exportingFormat !== null}
                    className="mt-6 w-full h-10 rounded-xl bg-purple-600 hover:bg-purple-500 text-white text-xs sm:text-sm font-medium flex items-center justify-center gap-2 transition-colors disabled:opacity-50 cursor-pointer"
                  >
                    {exportingFormat === 'json' ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>Generando JSON...</span>
                      </>
                    ) : (
                      <>
                        <Download className="w-4 h-4" />
                        <span>Descargar JSON</span>
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>
          ) : (
            /* TAB 2: DATABASE BACKUP & RESTORE */
            <div className="space-y-6 max-w-5xl">
              {/* Snapshot Download Card */}
              <div className="rounded-2xl border border-zinc-800 bg-zinc-950/70 p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-6">
                <div className="flex items-start gap-4">
                  <div className="w-12 h-12 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 shrink-0 mt-0.5">
                    <ShieldCheck className="w-6 h-6" />
                  </div>
                  <div>
                    <h3 className="text-base font-semibold text-white">
                      Instantánea SQLite Atómica (.db)
                    </h3>
                    <p className="text-xs sm:text-sm text-zinc-400 mt-1 leading-relaxed max-w-2xl">
                      Descarga una copia thread-safe y coherente de la base de datos activa mediante la API de backup de SQLite. No bloquea lecturas ni interrumpe las actualizaciones automáticas de cotizaciones.
                    </p>
                  </div>
                </div>
                <button
                  onClick={handleDownloadDbSnapshot}
                  disabled={downloadingDb}
                  className="h-10 px-5 rounded-xl bg-zinc-800 hover:bg-zinc-700 text-zinc-100 border border-zinc-700 text-xs sm:text-sm font-medium flex items-center justify-center gap-2 shrink-0 transition-colors disabled:opacity-50 cursor-pointer"
                >
                  {downloadingDb ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin text-emerald-400" />
                      <span>Descargando base de datos...</span>
                    </>
                  ) : (
                    <>
                      <Download className="w-4 h-4 text-emerald-400" />
                      <span>Descargar archivo .db</span>
                    </>
                  )}
                </button>
              </div>

              {/* Restore From Uploaded File */}
              <div className="rounded-2xl border border-zinc-800 bg-zinc-950/70 p-6 space-y-4">
                <div className="flex items-center gap-2.5">
                  <Upload className="w-5 h-5 text-blue-400" />
                  <h3 className="text-base font-semibold text-white">
                    Restaurar desde archivo (.db o .json)
                  </h3>
                </div>
                <p className="text-xs sm:text-sm text-zinc-400 leading-relaxed">
                  Carga un archivo de respaldo previo para reemplazar y restaurar por completo la base de datos de PortfolioMaster.
                </p>

                <input
                  type="file"
                  ref={fileInputRef}
                  accept=".db,.sqlite,.sqlite3,.json"
                  onChange={handleFileChange}
                  className="hidden"
                />

                {!selectedFile ? (
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    className="w-full py-8 border-2 border-dashed border-zinc-800 hover:border-blue-500/50 rounded-2xl flex flex-col items-center justify-center gap-3 text-zinc-400 hover:text-zinc-200 transition-colors cursor-pointer bg-zinc-900/30"
                  >
                    <Upload className="w-8 h-8 text-zinc-500" />
                    <span className="text-xs sm:text-sm font-medium">Haz clic aquí para seleccionar un archivo .db o .json</span>
                    <span className="text-xs text-zinc-500">Se validará el esquema y la integridad del archivo antes de aplicar cambios</span>
                  </button>
                ) : (
                  <div className="p-4 rounded-xl border border-blue-500/30 bg-blue-500/5 space-y-4">
                    <div className="flex items-center justify-between text-xs sm:text-sm">
                      <span className="font-mono text-zinc-200 font-medium truncate max-w-md sm:max-w-xl">
                        {selectedFile.name}
                      </span>
                      <span className="text-zinc-400 text-xs font-mono">
                        {formatFileSize(selectedFile.size)}
                      </span>
                    </div>

                    {!confirmFileRestore ? (
                      <div className="flex items-center justify-end gap-3 pt-1">
                        <button
                          onClick={() => setSelectedFile(null)}
                          className="px-4 py-2 rounded-lg text-xs font-medium text-zinc-400 hover:text-zinc-200 transition-colors cursor-pointer"
                        >
                          Cancelar
                        </button>
                        <button
                          onClick={() => setConfirmFileRestore(true)}
                          className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium flex items-center gap-1.5 transition-colors cursor-pointer"
                        >
                          <Upload className="w-3.5 h-3.5" />
                          <span>Restaurar Archivo</span>
                        </button>
                      </div>
                    ) : (
                      <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs sm:text-sm space-y-4">
                        <div className="flex items-start gap-3">
                          <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
                          <span className="leading-relaxed">
                            <strong>¿Confirmar restauración?</strong> Se reemplazará la base de datos actual con los datos del archivo seleccionado.
                            PortfolioMaster creará automáticamente una copia de seguridad preventiva antes de proceder.
                          </span>
                        </div>
                        <div className="flex items-center justify-end gap-3">
                          <button
                            onClick={() => setConfirmFileRestore(false)}
                            disabled={restoringFile}
                            className="px-4 py-2 rounded-lg text-xs text-zinc-400 hover:text-zinc-200 cursor-pointer"
                          >
                            Volver
                          </button>
                          <button
                            onClick={handleExecuteFileRestore}
                            disabled={restoringFile}
                            className="px-4 py-2 rounded-lg bg-rose-600 hover:bg-rose-500 text-white text-xs font-medium flex items-center gap-2 disabled:opacity-50 cursor-pointer"
                          >
                            {restoringFile ? (
                              <>
                                <Loader2 className="w-4 h-4 animate-spin" />
                                <span>Restaurando base de datos...</span>
                              </>
                            ) : (
                              <span>Sí, confirmar restauración</span>
                            )}
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Automatic Local Backups List */}
              <div className="rounded-2xl border border-zinc-800 bg-zinc-950/70 p-6 space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <History className="w-5 h-5 text-zinc-400" />
                    <h3 className="text-base font-semibold text-white">
                      Copias de Seguridad Automáticas Locales
                    </h3>
                  </div>
                  <button
                    onClick={fetchBackups}
                    disabled={loadingBackups}
                    className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors cursor-pointer"
                    title="Recargar lista de copias locales"
                  >
                    <RefreshCw className={`w-4 h-4 ${loadingBackups ? 'animate-spin text-blue-400' : ''}`} />
                  </button>
                </div>

                <p className="text-xs sm:text-sm text-zinc-400 leading-relaxed">
                  Instantáneas generadas automáticamente por el servidor antes de cualquier acción destructiva (borrado completo, importación o restauración). El sistema retiene una rotación continua de las últimas 10 copias de seguridad en el directorio <code className="text-zinc-300 font-mono text-xs">backups/</code>.
                </p>

                {loadingBackups ? (
                  <div className="py-8 flex items-center justify-center text-xs text-zinc-500 gap-2">
                    <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
                    <span>Cargando copias de seguridad...</span>
                  </div>
                ) : backups.length === 0 ? (
                  <div className="py-8 text-center text-xs sm:text-sm text-zinc-500 border border-zinc-800/80 rounded-xl bg-zinc-900/20">
                    No hay copias de seguridad automáticas registradas aún.
                  </div>
                ) : (
                  <div className="space-y-2.5 max-h-72 overflow-y-auto pr-1">
                    {backups.map((bkp) => (
                      <div
                        key={bkp.filename}
                        className="flex items-center justify-between p-3 rounded-xl border border-zinc-800/80 bg-zinc-900/60 hover:bg-zinc-900 transition-colors text-xs sm:text-sm"
                      >
                        <div className="min-w-0 pr-4">
                          <p className="font-mono text-zinc-200 font-medium truncate" title={bkp.filename}>
                            {bkp.filename}
                          </p>
                          <div className="flex items-center gap-2 text-xs text-zinc-400 mt-1">
                            <span>{formatDate(bkp.created_at)}</span>
                            <span>·</span>
                            <span className="font-mono">{formatFileSize(bkp.size_bytes)}</span>
                          </div>
                        </div>

                        <button
                          onClick={() => setBackupToRestore(bkp)}
                          className="px-3.5 py-1.5 rounded-lg bg-zinc-800 hover:bg-blue-600 hover:text-white text-zinc-300 border border-zinc-700 text-xs font-medium transition-colors shrink-0 cursor-pointer"
                        >
                          Restaurar
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Confirmation Modal for Local Backup Restore */}
      {backupToRestore && (
        <div className="fixed inset-0 z-[160] flex items-center justify-center p-4 bg-zinc-950/80 backdrop-blur-sm animate-in fade-in duration-150">
          <div className="w-full max-w-md bg-zinc-900 border border-zinc-800 rounded-2xl p-6 shadow-2xl space-y-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400 shrink-0">
                <AlertTriangle className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-base font-bold text-white">¿Restaurar copia local?</h3>
                <p className="text-xs text-zinc-400 mt-0.5">
                  Esta acción restaurará la base de datos a su estado en la copia seleccionada.
                </p>
              </div>
            </div>

            <div className="p-3 rounded-lg bg-zinc-950/60 border border-zinc-800 text-xs font-mono text-zinc-300 break-all">
              {backupToRestore.filename}
            </div>

            <div className="text-xs text-zinc-400">
              Se creará automáticamente una copia de seguridad del estado actual antes de proceder.
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                onClick={() => setBackupToRestore(null)}
                disabled={restoringLocal}
                className="px-4 py-2 rounded-lg text-xs font-medium text-zinc-300 bg-zinc-800 hover:bg-zinc-700 transition-colors cursor-pointer"
              >
                Cancelar
              </button>
              <button
                onClick={handleExecuteLocalRestore}
                disabled={restoringLocal}
                className="px-4 py-2 rounded-lg bg-rose-600 hover:bg-rose-500 text-white text-xs font-medium flex items-center gap-1.5 transition-colors disabled:opacity-50 cursor-pointer"
              >
                {restoringLocal ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>Restaurando...</span>
                  </>
                ) : (
                  <span>Sí, restaurar ahora</span>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
