/** Zahlen in Eingabefeldern der Einstellungen: Anzeige mit Komma (Deutsch) bzw. Punkt, Eingabe mit beidem. */

/** Zahl in der Schreibweise der Oberfläche (Deutsch mit Komma). */
export function formatNumberText(value: number | null, lang: string): string {
  if (value === null || !Number.isFinite(value)) return '';
  const text = String(Math.round(value * 1000) / 1000);
  return lang.startsWith('de') ? text.replace('.', ',') : text;
}

/** Getippter Text als Zahl (Komma oder Punkt); leer: null, ungültig: NaN. */
export function parseNumberText(raw: string): number | null {
  const text = raw.trim().replace(/\s/g, '').replace(',', '.');
  if (text === '') return null;
  return /^-?\d*(\.\d*)?$/.test(text) && text !== '-' && text !== '.' ? Number(text) : Number.NaN;
}
