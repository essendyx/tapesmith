/** Typen der Seite Kleinanzeigen. */

export type KaStatus = 'verfügbar' | 'reserviert' | 'verkauft'; // i18n-ignore (Server-Werte)

export const KA_STATUSES: KaStatus[] = ['verfügbar', 'reserviert', 'verkauft']; // i18n-ignore (Server-Werte)

export interface ArtikelJson {
  id: string;
  titel: string;
  preis: string;
  anzeige: string | null;
  status: KaStatus;
  name: string;
  datum: string;
  ort: string;
  notiz: string;
  created: string;
  updated: string;
}

export interface ArtikelListJson {
  items: ArtikelJson[];
  next: string;
  shortlink: boolean;
}

export interface NewArtikelRequest {
  titel: string;
  preis?: string;
  anzeige?: string | null;
  ort?: string;
  notiz?: string;
}

export interface UpdateArtikelRequest {
  titel?: string;
  preis?: string;
  anzeige?: string | null;
  ort?: string;
  notiz?: string;
}

export interface StatusRequest {
  status: KaStatus;
  name?: string;
  datum?: string;
}

export interface LabelResponse {
  template: string;
  values: Record<string, string>;
  warnings: string[];
}

/** Formularwerte des gemeinsamen Dialogs (Neu/Bearbeiten). */
export interface ArtikelFormValues {
  titel: string;
  preis: string;
  anzeige: string;
  ort: string;
  notiz: string;
}
