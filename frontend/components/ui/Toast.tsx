'use client';

import React, { createContext, use, useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle2, Info, X } from 'lucide-react';
import { useLanguage } from '@/context/LanguageContext';

const variants = {
  success: { Icon: CheckCircle2, colors: 'bg-emerald-950/95 border-emerald-500/30 text-emerald-200' },
  error: { Icon: AlertTriangle, colors: 'bg-rose-950/95 border-rose-500/30 text-rose-200' },
  info: { Icon: Info, colors: 'bg-blue-950/95 border-blue-500/30 text-blue-200' },
};

type ToastType = keyof typeof variants;
type AddToast = (type: ToastType, message: string, durationMs?: number | null) => void;

interface Notification {
  id: number;
  type: ToastType;
  message: string;
  durationMs: number | null;
}

const ToastContext = createContext<AddToast | null>(null);

function Toast({ notification, onDismiss }: {
  notification: Notification;
  onDismiss: (id: number) => void;
}) {
  const { id, type, message, durationMs } = notification;
  const { Icon, colors } = variants[type];
  const { language } = useLanguage();

  useEffect(() => {
    if (durationMs === null) return;
    const timer = setTimeout(() => onDismiss(id), durationMs);
    return () => clearTimeout(timer);
  }, [id, durationMs, onDismiss]);

  return (
    <div className={`pointer-events-auto flex items-start gap-3 rounded-xl border p-3 text-xs shadow-xl backdrop-blur-md ${colors}`}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <span role={type === 'error' ? 'alert' : 'status'} className="min-w-0 flex-1 wrap-break-word font-medium leading-relaxed">
        {message}
      </span>
      <button
        type="button"
        onClick={() => onDismiss(id)}
        aria-label={language === 'es' ? 'Cerrar notificación' : 'Dismiss notification'}
        className="shrink-0 rounded p-1 text-zinc-300 transition-colors hover:bg-white/10 hover:text-white"
      >
        <X className="size-4" aria-hidden="true" />
      </button>
    </div>
  );
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const nextId = useRef(0);
  const addToast = useCallback<AddToast>((type, message, durationMs = 5000) => {
    const id = ++nextId.current;
    setNotifications((current) => [...current, { id, type, message, durationMs }]);
  }, []);
  const dismissToast = useCallback((id: number) => {
    setNotifications((current) => current.filter((notification) => notification.id !== id));
  }, []);

  return (
    <ToastContext value={addToast}>
      {children}
      {notifications.length > 0 && (
        <div className="pointer-events-none fixed inset-x-4 top-20 z-[200] ml-auto flex max-h-[calc(100dvh-6rem)] max-w-sm flex-col gap-2 overflow-y-auto sm:left-auto sm:w-full">
          {notifications.map((notification) => (
            <Toast key={notification.id} notification={notification} onDismiss={dismissToast} />
          ))}
        </div>
      )}
    </ToastContext>
  );
}

export function useToast(): AddToast {
  const addToast = use(ToastContext);
  if (!addToast) throw new Error('useToast requires a ToastProvider');
  return addToast;
}
