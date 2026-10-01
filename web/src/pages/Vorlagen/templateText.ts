/** Anzeige-Helfer der Vorlagenseite (ohne Komponenten, damit Fast Refresh greift). */
import type { FieldJson, TemplateSummary } from '../../api/types';

/** Anzeigename einer Vorlage: Titel, sonst die ID lesbar gemacht („ordnerruecken-breit“ → „Ordnerruecken breit“). */
export function templateTitle(t: Pick<TemplateSummary, 'name' | 'title'>): string {
  if (t.title && t.title !== t.name) return t.title;
  const text = t.name.replace(/[-_]+/g, ' ').trim();
  return text ? text.charAt(0).toLocaleUpperCase() + text.slice(1) : t.name;
}

/** Erster Satz einer Beschreibung, für die Zweitzeile der Liste. */
export function shortDescription(text: string): string {
  const trimmed = text.trim();
  const first = /^(.+?[.:!?])(\s|$)/.exec(trimmed)?.[1] ?? trimmed;
  return first.replace(/[.:]$/, '');
}

/** Element-ID eines Formularfelds (zum Fokussieren aus der Seite heraus). */
export function templateFieldId(prefix: string, fieldId: string): string {
  return `${prefix}-${fieldId}`;
}

/** Beispielwert für ein leeres Pflichtfeld: Beispiel der Vorlage, sonst Standard, erste Auswahl oder die Feldbezeichnung. */
export function placeholderValue(field: FieldJson, sample: Record<string, string>): string {
  return sample[field.id] || field.default || field.choices[0] || field.label;
}

export type CategoryKind = 'office' | 'home' | 'homelab' | 'disks' | 'cables' | 'grid' | 'other';

/** Symbol-Art einer Kategorie (Namen der eingebauten Vorlagen auf Deutsch und Englisch). */
export function categoryKind(name: string): CategoryKind {
  // Akzente und Umlautpunkte entfernen, damit die Vergleichsschlüssel reines ASCII bleiben
  const n = name.trim().toLocaleLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  if (n === 'buro' || n === 'office') return 'office';
  if (n === 'haushalt' || n === 'household') return 'home';
  if (n === 'homelab') return 'homelab';
  if (n === 'datentrager' || n === 'disk' || n === 'disks') return 'disks';
  if (n === 'kabel' || n === 'cable' || n === 'cables') return 'cables';
  if (n === 'raster' || n === 'grid') return 'grid';
  return 'other';
}
