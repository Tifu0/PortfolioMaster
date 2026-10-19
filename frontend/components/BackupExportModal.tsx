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
  X,
  ShieldCheck,
  FileDown,
} from 'lucide-react';
import {
  exportWatchlist,
  downloadDatabaseBackup,
  getBackupList,
  restoreBackupFile,
  restoreLocalBackup,
} from '@/lib/api';
import type { BackupItem } from '@/lib/types';

interface BackupExportModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
  onDataRestored: () => void;
}

export function BackupExportModal({
  isOpen,
  onClose,
  onSuccess,
  onError,
  onDataRestored,
}: BackupExportModalProps) {
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

  // Load local backups when opening modal or switching to backup tab
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
    if (isOpen && activeTab === 'backup') {
      fetchBackups();
    }
  }, [isOpen, activeTab, fetchBackups]);

  // Reset internal states on close
  const handleClose = () => {
    setSelectedFile(null);
    setConfirmFileRestore(false);
    setBackupToRestore(null);
    onClose();
  };

  // 1. Export Handlers
  const handleExport = async (format: 'csv' | 'excel' | 'json') => {
    setExportingFormat(format);
    try {
      await exportWatchlist(format);
      onSuccess(`Exportación a ${format.toUpperCase()} descargada correctamente.`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError(`Error al exportar a ${format.toUpperCase()}: ${msg}`);
    } finally {
      setExportingFormat(null);
    }
  };

  const handleDownloadDbSnapshot = async () => {
    setDownloadingDb(true);
    try {
      await downloadDatabaseBackup();
      onSuccess('Copia atómica de la base de datos SQLite (.db) descargada correctamente.');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError(`Error al descargar la base de datos: ${msg}`);
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
      onSuccess(
        `Restauración completada con éxito. Se restauraron ${res.restored_instruments ?? 'todos los'} instrumentos.`
      );
      setSelectedFile(null);
      setConfirmFileRestore(false);
      await fetchBackups();
      onDataRestored();
      handleClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError(`Fallo en la restauración: ${msg}`);
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
      onSuccess(
        `Base de datos restaurada correctamente desde "${backupToRestore.filename}" (${res.restored_instruments ?? 0} instrumentos).`
      );
      setBackupToRestore(null);
      await fetchBackups();
      onDataRestored();
      handleClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onError(`Fallo al restaurar la copia de seguridad: ${msg}`);
    } finally {
      setRestoringLocal(false);
    }
  };

  if (!isOpen) return null;

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
    <div className="fixed inset-0 z-[150] flex items-center justify-center p-4 sm:p-6 overflow-y-auto bg-zinc-950/80 backdrop-blur-sm animate-in fade-in duration-150">
      <div className="relative w-full max-w-2xl bg-zinc-900 border border-zinc-800 rounded-2xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-zinc-800/80 bg-zinc-900/90">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
              <Download className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white tracking-tight">
                Exportación y Copias de Seguridad
              </h2>
              <p className="text-xs text-zinc-400 mt-0.5">
                Exporta tus valores a múltiples formatos o gestiona instantáneas de la base de datos.
              </p>
            </div>
          </div>
          <button
            onClick={handleClose}
            className="text-zinc-400 hover:text-white p-2 rounded-lg hover:bg-zinc-800/60 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tabs Switcher */}
        <div className="flex border-b border-zinc-800 px-6 bg-zinc-950/40">
          <button
            onClick={() => setActiveTab('export')}
            className={`py-3.5 px-4 text-xs sm:text-sm font-medium border-b-2 transition-all flex items-center gap-2 ${
              activeTab === 'export'
                ? 'border-emerald-500 text-emerald-400'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <FileDown className="w-4 h-4" />
            Exportar Cartera
          </button>
          <button
            onClick={() => setActiveTab('backup')}
            className={`py-3.5 px-4 text-xs sm:text-sm font-medium border-b-2 transition-all flex items-center gap-2 ${
              activeTab === 'backup'
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-zinc-400 hover:text-zinc-200'
            }`}
          >
            <Database className="w-4 h-4" />
            Base de Datos y Restauración
          </button>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {activeTab === 'export' ? (
            /* TAB 1: EXPORT WATCHLIST */
            <div className="space-y-4">
              <div className="p-3.5 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 text-xs flex items-center gap-2.5">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                <span>
                  Los formatos <strong>Excel</strong> y <strong>CSV</strong> son 100% compatibles con el importador. Puedes volver a importarlos en cualquier momento sin pérdida de datos ni notas de análisis.
                </span>
              </div>

              {/* Action Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3.5">
                {/* Excel .xlsx */}
                <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-4 flex flex-col justify-between hover:border-emerald-500/40 transition-all group">
                  <div>
                    <div className="w-9 h-9 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 mb-3 group-hover:scale-105 transition-transform">
                      <FileSpreadsheet className="w-5 h-5" />
                    </div>
                    <h3 className="text-sm font-semibold text-white">Excel (.xlsx)</h3>
                    <p className="text-xs text-zinc-400 mt-1.5 leading-relaxed">
                      Hoja de cálculo estilizada con cotizaciones, variaciones calculadas y notas.
                    </p>
                  </div>
                  <button
                    onClick={() => handleExport('excel')}
                    disabled={exportingFormat !== null}
                    className="mt-4 w-full h-9 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50"
                  >
                    {exportingFormat === 'excel' ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        <span>Generando...</span>
                      </>
                    ) : (
                      <>
                        <Download className="w-3.5 h-3.5" />
                        <span>Descargar Excel</span>
                      </>
                    )}
                  </button>
                </div>

                {/* CSV */}
                <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-4 flex flex-col justify-between hover:border-blue-500/40 transition-all group">
                  <div>
                    <div className="w-9 h-9 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400 mb-3 group-hover:scale-105 transition-transform">
                      <FileText className="w-5 h-5" />
                    </div>
                    <h3 className="text-sm font-semibold text-white">CSV (.csv)</h3>
                    <p className="text-xs text-zinc-400 mt-1.5 leading-relaxed">
                      Texto plano estándar UTF-8. Compatible con Excel, Google Sheets y PortfolioMaster.
                    </p>
                  </div>
                  <button
                    onClick={() => handleExport('csv')}
                    disabled={exportingFormat !== null}
                    className="mt-4 w-full h-9 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50"
                  >
                    {exportingFormat === 'csv' ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        <span>Generando...</span>
                      </>
                    ) : (
                      <>
                        <Download className="w-3.5 h-3.5" />
                        <span>Descargar CSV</span>
                      </>
                    )}
                  </button>
                </div>

                {/* JSON */}
                <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-4 flex flex-col justify-between hover:border-purple-500/40 transition-all group">
                  <div>
                    <div className="w-9 h-9 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400 mb-3 group-hover:scale-105 transition-transform">
                      <FileJson className="w-5 h-5" />
                    </div>
                    <h3 className="text-sm font-semibold text-white">JSON (.json)</h3>
                    <p className="text-xs text-zinc-400 mt-1.5 leading-relaxed">
                      Volcado estructurado con versión, metadatos, cotizaciones e instrumentos.
                    </p>
                  </div>
                  <button
                    onClick={() => handleExport('json')}
                    disabled={exportingFormat !== null}
                    className="mt-4 w-full h-9 rounded-lg bg-purple-600 hover:bg-purple-500 text-white text-xs font-medium flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50"
                  >
                    {exportingFormat === 'json' ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        <span>Generando...</span>
                      </>
                    ) : (
                      <>
                        <Download className="w-3.5 h-3.5" />
                        <span>Descargar JSON</span>
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>
          ) : (
            /* TAB 2: DATABASE BACKUP & RESTORE */
            <div className="space-y-6">
              {/* Snapshot Download Card */}
              <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="flex items-start gap-3">
                  <div className="w-9 h-9 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 shrink-0 mt-0.5">
                    <ShieldCheck className="w-5 h-5" />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-white">
                      Instantánea SQLite Atómica (.db)
                    </h3>
                    <p className="text-xs text-zinc-400 mt-1 leading-relaxed">
                      Copia thread-safe del archivo de base de datos activa. No interrumpe las actualizaciones automáticas.
                    </p>
                  </div>
                </div>
                <button
                  onClick={handleDownloadDbSnapshot}
                  disabled={downloadingDb}
                  className="h-9 px-4 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-100 border border-zinc-700 text-xs font-medium flex items-center justify-center gap-1.5 shrink-0 transition-colors disabled:opacity-50"
                >
                  {downloadingDb ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin text-emerald-400" />
                      <span>Descargando...</span>
                    </>
                  ) : (
                    <>
                      <Download className="w-3.5 h-3.5 text-emerald-400" />
                      <span>Descargar .db</span>
                    </>
                  )}
                </button>
              </div>

              {/* Restore From Uploaded File */}
              <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-4 space-y-3">
                <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                  <Upload className="w-4 h-4 text-blue-400" />
                  Restaurar desde archivo (.db o .json)
                </h3>
                <p className="text-xs text-zinc-400">
                  Sube un archivo de copia de seguridad previo para restaurar el contenido íntegro de la cartera.
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
                    className="w-full py-6 border-2 border-dashed border-zinc-800 hover:border-blue-500/50 rounded-xl flex flex-col items-center justify-center gap-2 text-zinc-400 hover:text-zinc-200 transition-colors cursor-pointer bg-zinc-900/40"
                  >
                    <Upload className="w-6 h-6 text-zinc-500" />
                    <span className="text-xs font-medium">Haz clic para seleccionar un archivo .db o .json</span>
                    <span className="text-[10px] text-zinc-500">Se validará la integridad antes de cualquier cambio</span>
                  </button>
                ) : (
                  <div className="p-3.5 rounded-xl border border-blue-500/30 bg-blue-500/5 space-y-3">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-mono text-zinc-200 font-medium truncate max-w-xs sm:max-w-md">
                        {selectedFile.name}
                      </span>
                      <span className="text-zinc-400 text-[11px] font-mono">
                        {formatFileSize(selectedFile.size)}
                      </span>
                    </div>

                    {!confirmFileRestore ? (
                      <div className="flex items-center justify-end gap-2 pt-1">
                        <button
                          onClick={() => setSelectedFile(null)}
                          className="px-3 py-1.5 rounded-lg text-xs font-medium text-zinc-400 hover:text-zinc-200 transition-colors"
                        >
                          Cancelar
                        </button>
                        <button
                          onClick={() => setConfirmFileRestore(true)}
                          className="px-3.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium flex items-center gap-1.5 transition-colors"
                        >
                          <Upload className="w-3.5 h-3.5" />
                          <span>Restaurar Archivo</span>
                        </button>
                      </div>
                    ) : (
                      <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-200 text-xs space-y-3">
                        <div className="flex items-start gap-2">
                          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                          <span>
                            <strong>¿Confirmar restauración?</strong> Se reemplazará la base de datos actual. PortfolioMaster creará automáticamente una copia de seguridad preventiva antes de aplicar los cambios.
                          </span>
                        </div>
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => setConfirmFileRestore(false)}
                            disabled={restoringFile}
                            className="px-3 py-1 rounded text-xs text-zinc-400 hover:text-zinc-200"
                          >
                            Volver
                          </button>
                          <button
                            onClick={handleExecuteFileRestore}
                            disabled={restoringFile}
                            className="px-3.5 py-1.5 rounded bg-rose-600 hover:bg-rose-500 text-white text-xs font-medium flex items-center gap-1.5 disabled:opacity-50"
                          >
                            {restoringFile ? (
                              <>
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                <span>Restaurando...</span>
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
              <div className="rounded-xl border border-zinc-800 bg-zinc-950/60 p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <History className="w-4 h-4 text-zinc-400" />
                    <h3 className="text-sm font-semibold text-white">
                      Copias de Seguridad Automáticas Locales
                    </h3>
                  </div>
                  <button
                    onClick={fetchBackups}
                    disabled={loadingBackups}
                    className="p-1 rounded text-zinc-400 hover:text-zinc-200 transition-colors"
                    title="Recargar lista de copias locales"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${loadingBackups ? 'animate-spin text-blue-400' : ''}`} />
                  </button>
                </div>

                <p className="text-xs text-zinc-400">
                  Instantáneas generadas automáticamente antes de acciones destructivas (borrado de BD, importación o restauración). Se mantiene una rotación de las últimas 10 copias.
                </p>

                {loadingBackups ? (
                  <div className="py-6 flex items-center justify-center text-xs text-zinc-500 gap-2">
                    <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
                    <span>Cargando copias de seguridad...</span>
                  </div>
                ) : backups.length === 0 ? (
                  <div className="py-6 text-center text-xs text-zinc-500 border border-zinc-800/80 rounded-lg">
                    No hay copias de seguridad automáticas registradas en <code className="text-zinc-400">backups/</code>.
                  </div>
                ) : (
                  <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
                    {backups.map((bkp) => (
                      <div
                        key={bkp.filename}
                        className="flex items-center justify-between p-2.5 rounded-lg border border-zinc-800/80 bg-zinc-900/60 hover:bg-zinc-900 transition-colors text-xs"
                      >
                        <div className="min-w-0 pr-3">
                          <p className="font-mono text-zinc-200 font-medium truncate" title={bkp.filename}>
                            {bkp.filename}
                          </p>
                          <div className="flex items-center gap-2 text-[11px] text-zinc-400 mt-0.5">
                            <span>{formatDate(bkp.created_at)}</span>
                            <span>·</span>
                            <span className="font-mono">{formatFileSize(bkp.size_bytes)}</span>
                          </div>
                        </div>

                        <button
                          onClick={() => setBackupToRestore(bkp)}
                          className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-blue-600 hover:text-white text-zinc-300 border border-zinc-700 text-xs font-medium transition-colors shrink-0"
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

        {/* Footer */}
        <div className="px-6 py-4 border-t border-zinc-800 bg-zinc-900/90 flex items-center justify-end">
          <button
            onClick={handleClose}
            className="px-4 py-2 rounded-lg text-xs font-medium text-zinc-300 bg-zinc-800 border border-zinc-700 hover:bg-zinc-700 transition-colors"
          >
            Cerrar
          </button>
        </div>
      </div>

      {/* Confirmation Modal for Local Backup Restore */}
      {backupToRestore && (
        <div className="fixed inset-0 z-[160] flex items-center justify-center p-4 bg-zinc-950/80 backdrop-blur-sm">
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
                className="px-4 py-2 rounded-lg text-xs font-medium text-zinc-300 bg-zinc-800 hover:bg-zinc-700 transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={handleExecuteLocalRestore}
                disabled={restoringLocal}
                className="px-4 py-2 rounded-lg bg-rose-600 hover:bg-rose-500 text-white text-xs font-medium flex items-center gap-1.5 transition-colors disabled:opacity-50"
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
