/**
 * i18n der Web-Oberfläche: eine synchrone i18next-Instanz, Sprachwahl aus `AppInfo.language`.
 * "auto" folgt der vom Dienst gemeldeten Systemsprache (`AppInfo.resolved_language`, die
 * Windows-Anzeigesprache), nur ohne Meldung des Dienstes der Browsersprache (Familienseite auf dem
 * Handy). Unterstützt sind Deutsch und Englisch, jede andere Sprache wird Englisch.
 */
import { useEffect } from 'react';
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import { namespaces, resources } from './resources';

export type Language = 'de' | 'en';
export type LanguageSetting = 'auto' | Language;

export const LANGUAGES: readonly Language[] = ['de', 'en'];
/** Sprache für jede andere oder unbekannte Sprache (die App wird international veröffentlicht). */
export const DEFAULT_LANGUAGE: Language = 'en';

function isLanguage(value: unknown): value is Language {
  return value === 'de' || value === 'en';
}

function primary(tag: string | null | undefined): string {
  return (tag ?? '').trim().toLowerCase().split(/[-_]/)[0] ?? '';
}

function browserLanguages(): readonly string[] {
  try {
    if (typeof navigator === 'undefined') return [];
    if (navigator.languages && navigator.languages.length) return navigator.languages;
    return navigator.language ? [navigator.language] : [];
  } catch {
    return [];
  }
}

let serviceLanguage: Language | null = null;

/** Merkt sich die vom Dienst gemeldete Sprache (`AppInfo.resolved_language`) für "auto". */
export function setServiceLanguage(value: string | null | undefined): void {
  const p = primary(value);
  serviceLanguage = isLanguage(p) ? p : null;
}

/**
 * "auto" bzw. null: die Sprache des Dienstes (Windows-Anzeigesprache), ohne sie die erste
 * Browser-Sprache mit Hauptteil de oder en, sonst Englisch.
 */
export function resolveLanguage(
  setting: LanguageSetting | null | undefined,
  navigatorLanguages: readonly string[] = browserLanguages(),
  service: string | null | undefined = serviceLanguage,
): Language {
  if (isLanguage(setting)) return setting;
  const fromService = primary(service);
  if (isLanguage(fromService)) return fromService;
  for (const tag of navigatorLanguages) {
    const p = primary(tag);
    if (isLanguage(p)) return p;
  }
  return DEFAULT_LANGUAGE;
}

/**
 * Initialisiert die Instanz synchron (alle Übersetzungen liegen im Bundle). Idempotent: ein
 * zweiter Aufruf ändert nur die Sprache. `test` lässt fehlende Schlüssel einen Fehler werfen.
 */
export function initI18n(opts?: { language?: Language; test?: boolean }): typeof i18n {
  const lng = opts?.language ?? resolveLanguage('auto');
  if (i18n.isInitialized) {
    if (i18n.language !== lng) void i18n.changeLanguage(lng);
    return i18n;
  }
  const test = opts?.test ?? false;
  void i18n.use(initReactI18next).init({
    resources,
    lng,
    fallbackLng: 'de',
    supportedLngs: [...LANGUAGES],
    ns: namespaces,
    defaultNS: 'common',
    keySeparator: '.',
    nsSeparator: ':',
    // i18next ab Version 24 heißt die Option `initAsync` (früher `initImmediate`).
    initAsync: false,
    returnNull: false,
    interpolation: { escapeValue: false },
    saveMissing: test,
    missingKeyHandler: test
      ? (_lngs: readonly string[], ns: string, key: string) => {
          throw new Error(`i18n: fehlender Schlüssel ${ns}:${key}`);
        }
      : false,
    react: { useSuspense: false },
  });
  return i18n;
}

/** Aktuelle Sprache der Oberfläche ("de" oder "en"). */
export function currentLanguage(): Language {
  const lng = primary(i18n.resolvedLanguage ?? i18n.language);
  return isLanguage(lng) ? lng : 'de';
}

function applyLanguage(lng: Language): void {
  if (i18n.language !== lng) void i18n.changeLanguage(lng);
  if (typeof document !== 'undefined') document.documentElement.lang = lng;
}

/**
 * Folgt der Einstellung `app.language` ohne Neustart und setzt `<html lang>`. `undefined` heißt
 * "noch nicht geladen" und ändert nichts (die Startsprache kommt aus `initI18n`), `null` wie "auto".
 * `service` ist die vom Dienst aufgelöste Sprache (`AppInfo.resolved_language`), die bei "auto" gilt.
 */
export function useLanguageSync(setting: LanguageSetting | null | undefined, service?: string | null): void {
  useEffect(() => {
    if (service !== undefined) setServiceLanguage(service);
    if (setting === undefined) {
      if (typeof document !== 'undefined') document.documentElement.lang = currentLanguage();
      return;
    }
    applyLanguage(resolveLanguage(setting));
  }, [setting, service]);
}

/** Übersetzt `key`, wenn es ihn gibt, sonst `fallback` (z. B. Server-Texte als Rückfall). */
export function translateOr(key: string, fallback: string, options?: Record<string, unknown>): string {
  return i18n.exists(key, options) ? String(i18n.t(key, options)) : fallback;
}

export { i18n };
