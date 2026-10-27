'use client';

import React, { createContext, useContext, useEffect, useState, useMemo, useCallback } from 'react';
import { translations, type Language, type TranslationKey } from '@/lib/translations';

const LANGUAGE_STORAGE_KEY = 'portfoliomaster_language';

interface LanguageContextType {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: (key: TranslationKey, params?: Record<string, string | number>) => string;
}

const LanguageContext = createContext<LanguageContextType | null>(null);

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  // Default language is English ('en')
  const [language, setLanguageState] = useState<Language>('en');

  // Load saved preference on client mount
  useEffect(() => {
    try {
      const saved = localStorage.getItem(LANGUAGE_STORAGE_KEY);
      if (saved === 'en' || saved === 'es') {
        setLanguageState(saved);
      }
    } catch {
      // Ignore localStorage errors (private browsing, etc.)
    }
  }, []);

  // Sync document.documentElement.lang
  useEffect(() => {
    if (typeof document !== 'undefined') {
      document.documentElement.lang = language;
    }
  }, [language]);

  const setLanguage = useCallback((newLang: Language) => {
    setLanguageState(newLang);
    try {
      localStorage.setItem(LANGUAGE_STORAGE_KEY, newLang);
    } catch {
      // Ignore localStorage write error
    }
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
