import type { Language } from './translations';

const locales: Record<Language, string> = { en: 'en-US', es: 'es-ES' };
const numberFormatters = new Map<string, Intl.NumberFormat>();

export function formatCurrency(
  value: number | null | undefined,
  currency: string | null | undefined,
  language: Language,
): string {
  if (value == null || !Number.isFinite(value)) return '—';

  const locale = locales[language];
  const code = currency?.trim().toUpperCase();
  const currencyCode = code && /^[A-Z]{3}$/.test(code) ? code : undefined;
  const key = `${locale}:${currencyCode ?? ''}`;
  let formatter = numberFormatters.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat(locale, {
      style: currencyCode ? 'currency' : 'decimal',
      currency: currencyCode,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    numberFormatters.set(key, formatter);
  }
  return formatter.format(value);
}
