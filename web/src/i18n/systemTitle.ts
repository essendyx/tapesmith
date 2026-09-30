/**
 * Anzeige-Titel für Verlauf und Warteschlange: Titel, die der Druckdienst selbst vergibt
 * (Kalibrierung, Testlabel, Bild aus der Zwischenablage, Präfixe „Nachdruck #n: “ und
 * „Serie (n): “, Anzeige eines WLAN-QR mit Passwort), stehen in der Sprache, in der gedruckt wurde. Beim Anzeigen
 * werden sie anhand der Art (`kind`) in die aktuelle Oberflächensprache übersetzt. Gespeicherte
 * Titel bleiben unverändert, und Nutzertexte (Art `text`, `template`, `qr` ohne bekanntes Muster)
 * werden nie angefasst.
 *
 * Die Warteschlange kennt die Art eines Auftrags nicht: dort gilt `kind` `undefined`, und nur die
 * vollständigen Systemtitel und die Präfixe werden erkannt.
 */
import { i18n } from './index';

type SystemKey = 'calibrateRuler' | 'calibrateEdge' | 'testLabel' | 'clipboardImage';

/** Bekannte Systemtitel in beiden Sprachen (Server-Katalog `locales/messages/en.json`). // i18n-ignore */
const EXACT: Record<string, SystemKey> = {
  'Kalibrierung Lineal': 'calibrateRuler', // i18n-ignore (Server-Titel)
  'Calibration ruler': 'calibrateRuler',
  'Kalibrierung ruler': 'calibrateRuler', // i18n-ignore (Server-Titel der Kommandozeile)
  'Calibration edge': 'calibrateEdge',
  'Kalibrierung Kantentest': 'calibrateEdge', // i18n-ignore (Server-Titel)
  'Calibration edge test': 'calibrateEdge',
  'Kalibrierung edge': 'calibrateEdge', // i18n-ignore (Server-Titel der Kommandozeile)
  Testlabel: 'testLabel', // i18n-ignore (Server-Titel)
  'Test label': 'testLabel',
  'Bild aus Zwischenablage': 'clipboardImage', // i18n-ignore (Server-Titel)
  'Image from clipboard': 'clipboardImage',
};

/** Welche Arten welche exakten Systemtitel tragen können. */
const KIND_KEYS: Record<string, readonly SystemKey[]> = {
  calibrate: ['calibrateRuler', 'calibrateEdge'],
  test: ['testLabel'],
  image: ['clipboardImage'],
};

const REPRINT_PREFIX = /^(?:Nachdruck|Reprint) #(\d+): /; // i18n-ignore (Server-Präfix)
const SERIES_PREFIX = /^(?:Serie|Series) \((\d+)\): /; // i18n-ignore (Server-Präfix)
const CALIBRATE_GENERIC = /^(?:Kalibrierung|Calibration) (\S+)$/; // i18n-ignore (Server-Titel)
const WIFI = /^(?:WLAN|Wi-Fi) (.*?)(?: \((?:Passwort|password) ([^)]*)\))?$/; // i18n-ignore (QR-Anzeige)

function tr(key: string, options?: Record<string, unknown>): string {
  return String(i18n.t(`common:systemTitle.${key}`, options));
}

function exact(title: string, kind: string | undefined): string | null {
  const key = EXACT[title];
  if (!key) return null;
  if (kind !== undefined && !(KIND_KEYS[kind] ?? []).includes(key)) return null;
  return tr(key);
}

/** Rest nach einem Präfix: nur bekannte Systemtitel und die WLAN-Anzeige, nie Nutzertext. */
function rest(title: string, wifiEntry: boolean): string {
  const known = exact(title, undefined);
  if (known) return known;
  const wifi = wifiEntry ? WIFI.exec(title) : null;
  if (wifi) return wifiTitle(wifi);
  return title;
}

function wifiTitle(match: RegExpExecArray): string {
  const ssid = match[1] ?? '';
  const redacted = match[2];
  return redacted !== undefined ? tr('wifiSecret', { ssid, redacted }) : tr('wifi', { ssid });
}

/**
 * Titel eines Verlaufseintrags oder Auftrags in der aktuellen Sprache. `kind` ist die Art des
 * Verlaufseintrags (`calibrate`, `test`, `image`, `reprint`, `template`, `qr`, `text`) oder
 * `undefined` (Warteschlange). `values` sind die gespeicherten Werte des Eintrags: nur ein
 * WLAN-QR mit Passwort (`qr_kind` `wifi`) ist sicher als solcher erkennbar, ein Text-QR, der mit
 * „WLAN“ beginnt, bleibt unverändert.
 */
export function displayTitle(title: string, kind?: string, values?: Record<string, string>): string {
  if (!title) return title;
  const wifiEntry = values?.qr_kind === 'wifi';
  const direct = exact(title, kind);
  if (direct) return direct;

  if (kind === undefined || kind === 'reprint') {
    const reprint = REPRINT_PREFIX.exec(title);
    if (reprint) return tr('reprintPrefix', { id: reprint[1] }) + rest(title.slice(reprint[0].length), wifiEntry);
  }
  if (kind === undefined || kind === 'template') {
    const series = SERIES_PREFIX.exec(title);
    if (series) return tr('seriesPrefix', { count: Number(series[1]) }) + title.slice(series[0].length);
  }
  if (kind === undefined || kind === 'calibrate') {
    const generic = CALIBRATE_GENERIC.exec(title);
    if (generic) return tr('calibrate', { name: generic[1] });
  }
  if (kind === 'qr' && wifiEntry) {
    const wifi = WIFI.exec(title);
    if (wifi) return wifiTitle(wifi);
  }
  return title;
}
