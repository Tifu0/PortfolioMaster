'use client';

import React, { createContext, useContext, useEffect, useState, useMemo, useCallback, useSyncExternalStore } from 'react';
import { translations, type Language, type TranslationKey } from '@/lib/translations';
import { getStoredString, setStoredString } from '@/lib/storage';

const LANGUAGE_STORAGE_KEY = 'portfoliomaster_language';

function getDefaultLanguage(): Language {
  return 'en';
}

function readSavedLanguage(): Language {
  const saved = getStoredString(LANGUAGE_STORAGE_KEY);
  if (saved === 'en' || saved === 'es') return saved;
  return getDefaultLanguage();
}

function subscribeToLanguageStorage(onChange: () => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key === LANGUAGE_STORAGE_KEY || event.key === null) onChange();
  };
  window.addEventListener('storage', onStorage);
  return () => window.removeEventListener('storage', onStorage);
}

interface LanguageContextType {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: (key: TranslationKey, params?: Record<string, string | number>) => string;
}

const LanguageContext = createContext<LanguageContextType | null>(null);

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const savedLanguage = useSyncExternalStore(subscribeToLanguageStorage, readSavedLanguage, getDefaultLanguage);
  const [selectedLanguage, setSelectedLanguage] = useState<Language | null>(null);
  const language = selectedLanguage ?? savedLanguage;

  // Sync document.documentElement.lang
  useEffect(() => {
    if (typeof document !== 'undefined') {
      document.documentElement.lang = language;
    }
  }, [language]);

  const setLanguage = useCallback((newLang: Language) => {
    setSelectedLanguage(newLang);
    setStoredString(LANGUAGE_STORAGE_KEY, newLang);
  }, []);

  const t = useCallback(
    (key: TranslationKey, params?: Record<string, string | number>): string => {
      const langDict = translations[language] || translations.en;
      let text: string = langDict[key] ?? translations.en[key] ?? key;

      if (params) {
        for (const [pKey, pVal] of Object.entries(params)) {
          text = text.replace(new RegExp(`\\{${pKey}\\}`, 'g'), String(pVal));
        }
      }
      return text;
    },
    [language]
  );

  const value = useMemo(
    () => ({
      language,
      setLanguage,
      t,
    }),
    [language, setLanguage, t]
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage(): LanguageContextType {
  const context = useContext(LanguageContext);
  if (!context) {
    // Graceful fallback to default English translations if used outside Provider
    return {
      language: 'en',
      setLanguage: () => {},
      t: (key: TranslationKey, params?: Record<string, string | number>) => {
        let text: string = translations.en[key] ?? key;
        if (params) {
          for (const [pKey, pVal] of Object.entries(params)) {
            text = text.replace(new RegExp(`\\{${pKey}\\}`, 'g'), String(pVal));
          }
        }
        return text;
      },
    };
  }
  return context;
}

export function TranslatedText({
  tKey,
  params,
}: {
  tKey: TranslationKey;
  params?: Record<string, string | number>;
}) {
  const { t } = useLanguage();
  return <>{t(tKey, params)}</>;
}

export function SkipToContentLink() {
  const { t } = useLanguage();
  return (
    <a
      href="#main-content"
      className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[300] focus:px-3 focus:py-2 focus:rounded-lg focus:bg-emerald-600 focus:text-white focus:text-xs focus:font-semibold focus:shadow-lg"
    >
      {t('skipToContent')}
    </a>
  );
}
