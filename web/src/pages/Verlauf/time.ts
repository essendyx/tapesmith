/**
 * Zeitangaben (gemeinsamer Helfer für Verlauf, Warteschlange, Statistik und Zugriff): dünner
 * Aufsatz auf den gemeinsamen, sprachabhängigen Formatierern aus `i18n/format.ts`
 * statt fest Deutsch. Zeitpunkte kommen als ISO ohne Zeitzone und werden als lokale
 * Zeit gelesen. Übersetzungen des Countdown-Texts liegen im eigenen Namensraum `verlauf`, da
 * dieser gemeinsame Helfer hier im Verlauf-Ordner liegt (inhaltlich gehört er eher nach
 * `common`).
 */
import { i18n } from '../../i18n';
import { formatDate, formatDateTime, formatRelative } from '../../i18n/format';

/** ISO-Zeitpunkt ohne Zeitzone als lokale Zeit lesen (new Date() würde ihn sonst als UTC deuten). */
export function parseServerTime(iso: string): Date {
  if (/[zZ]|[+-]\d\d:?\d\d$/.test(iso)) return new Date(iso);
  return new Date(iso.replace(' ', 'T'));
}

export function absoluteTime(iso: string): string {
  return formatDateTime(parseServerTime(iso));
}

export function dateOnly(iso: string): string {
  return formatDate(parseServerTime(iso));
}

/** „vor 5 Minuten“ bzw. „5 minutes ago“ (sprachabhängig über `formatRelative`). */
export function relativeTime(iso: string, now: Date = new Date()): string {
  return formatRelative(parseServerTime(iso), now);
}

/** Countdown bis zu einem künftigen Zeitpunkt: „in 42 s“, „in 3 min“, „jetzt“, „kein Termin“ ohne Zeitpunkt. */
export function countdownText(iso: string | null, now: Date = new Date()): string {
  if (!iso) return i18n.t('verlauf:time.noAppointment');
  const seconds = Math.ceil((parseServerTime(iso).getTime() - now.getTime()) / 1000);
  if (seconds <= 0) return i18n.t('verlauf:time.now');
  if (seconds < 120) return i18n.t('verlauf:time.inSeconds', { count: seconds });
  const minutes = Math.ceil(seconds / 60);
  return i18n.t('verlauf:time.inMinutes', { count: minutes });
}
