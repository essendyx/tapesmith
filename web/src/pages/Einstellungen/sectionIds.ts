/**
 * Sprungziele und gemerkter Zustand der Einstellungsseite: DOM-IDs der Karten, welche Ziele im
 * eingeklappten Abschnitt „Erweitert“ liegen und ob er geöffnet ist (je Browser, fehlertolerant).
 */
import { MODULES, type ModuleDef, type ModulesState } from '../../modules';

export const ADVANCED_ID = 'erweitert';
export const ADVANCED_STORAGE_KEY = 'tapesmith.einstellungen.erweitert';
export const MODULES_CARD_ID = 'module';
export const SUPPORT_CARD_ID = 'support';
export const INTEGRATION_ADVANCED_ID = 'integration-erweitert';
export const CONFIG_CODE_ID = 'konfiguration-code';
export const PLAUSI_ID = 'plausibilitaet';

/** DOM-ID der Karte eines Abschnitts unter „Erweitert“. */
export function advancedCardId(sectionId: string): string {
  return `erweitert-${sectionId}`;
}

/** DOM-ID der Einstellungskarte eines Moduls (Sprungziel `?abschnitt=modul-<id>`). */
export function moduleCardId(id: string): string {
  return `modul-${id}`;
}

/** Eingeschaltete Module mit eigener Einstellungskarte. */
export function modulesWithSettings(modules: ModulesState): ModuleDef[] {
  return MODULES.filter((m) => m.settings.length > 0 && modules.isEnabled(m.id));
}

/** Frühere Sprungziele, die heute unter „Erweitert“ oder in einer Modulkarte liegen. */
export const LEGACY_TARGETS: Record<string, string> = {
  ble: advancedCardId('ble'),
  archiv: advancedCardId('ordner'),
  vorlagen: advancedCardId('ordner'),
  'erweitert-archiv': advancedCardId('ordner'),
  'erweitert-vorlagen': advancedCardId('ordner'),
  'erweitert-sicherung': advancedCardId('ordner'),
  web: advancedCardId('druckdienst'),
  druckdienst: advancedCardId('druckdienst'),
  'druckdienst-status': SUPPORT_CARD_ID,
  ssh: moduleCardId('datentraeger'),
  homelab: MODULES_CARD_ID,
};

/** Liegt das Sprungziel im Abschnitt „Erweitert“? */
export function isAdvancedTarget(id: string): boolean {
  return (
    id === ADVANCED_ID ||
    id.startsWith(`${ADVANCED_ID}-`) ||
    id === INTEGRATION_ADVANCED_ID ||
    id === CONFIG_CODE_ID ||
    id === PLAUSI_ID
  );
}

/** Gemerkter Zustand von „Erweitert“; ohne Speicher (privates Fenster, gesperrt) zu. */
export function readAdvancedOpen(): boolean {
  try {
    return window.localStorage.getItem(ADVANCED_STORAGE_KEY) === 'offen';
  } catch {
    return false;
  }
}

export function writeAdvancedOpen(open: boolean): void {
  try {
    window.localStorage.setItem(ADVANCED_STORAGE_KEY, open ? 'offen' : 'zu');
  } catch {
    // Speicher nicht verfügbar: Zustand gilt nur bis zum Neuladen.
  }
}
