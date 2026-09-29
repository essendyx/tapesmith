/** Formatierer für Zahlen, Millimeter, Datum und relative Zeit; alle folgen der aktuellen Sprache. */
import { useTranslation } from 'react-i18next';
import { currentLanguage, i18n, type Language } from './index';

const DEFAULT_TAGS: Record<Language, string> = { de: 'de-DE', en: 'en-US' };

/** BCP-47-Tag der Sprache; die Browser-Region gilt, wenn die Hauptsprache übereinstimmt. */
export function localeTag(lang: Language = currentLanguage()): string {
  try {
    const nav = typeof navigator !== 'undefined' ? navigator.language : '';
    if (nav && nav.toLowerCase().split(/[-_]/)[0] === lang && nav.includes('-')) return nav;
  } catch {
    // Rückfall unten
  }
  return DEFAULT_TAGS[lang];
}

function toDate(value: string | Date): Date {
  return value instanceof Date ? value : new Date(value);
}

export function formatNumber(value: number, opts?: Intl.NumberFormatOptions): string {
  return new Intl.NumberFormat(localeTag(), opts).format(value);
}

/** "38 mm" bzw. "38,5 mm" / "38.5 mm" (höchstens `digits` Nachkommastellen). */
export function formatMm(mm: number, digits = 1): string {
  const value = formatNumber(mm, { maximumFractionDigits: digits });
  return String(i18n.t('common:units.mm', { value }));
}

function dateOptions(): Intl.DateTimeFormatOptions {
  return currentLanguage() === 'de'
    ? { day: '2-digit', month: '2-digit', year: 'numeric' }
    : { day: 'numeric', month: 'numeric', year: 'numeric' };
}

export function formatDate(value: string | Date): string {
  const d = toDate(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return new Intl.DateTimeFormat(localeTag(), dateOptions()).format(d);
}

export function formatDateTime(value: string | Date): string {
  const d = toDate(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return new Intl.DateTimeFormat(localeTag(), { ...dateOptions(), hour: '2-digit', minute: '2-digit' }).format(d);
}

const STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['second', 60],
  ['minute', 60],
  ['hour', 24],
  ['day', 7],
  ['week', 4.34524],
  ['month', 12],
  ['year', Number.POSITIVE_INFINITY],
];

/** "vor 5 Minuten" bzw. "5 minutes ago"; Stufen Sekunden bis Jahre. */
export function formatRelative(value: string | Date, now: Date = new Date()): string {
  const d = toDate(value);
  if (Number.isNaN(d.getTime())) return String(value);
  let amount = (d.getTime() - now.getTime()) / 1000;
  const rtf = new Intl.RelativeTimeFormat(localeTag(), { numeric: 'auto' });
  for (const [unit, size] of STEPS) {
    if (Math.abs(amount) < size) return rtf.format(Math.round(amount), unit);
    amount /= size;
  }
  return rtf.format(Math.round(amount), 'year');
}

/** Wie die Einzelfunktionen, rendert aber bei einem Sprachwechsel neu. */
export function useFormat(): {
  formatNumber: typeof formatNumber;
  formatMm: typeof formatMm;
  formatDate: typeof formatDate;
  formatDateTime: typeof formatDateTime;
  formatRelative: typeof formatRelative;
  language: Language;
} {
  useTranslation();
  return { formatNumber, formatMm, formatDate, formatDateTime, formatRelative, language: currentLanguage() };
}
