/** Typen der Seite „Assets": Register mit zentralem Nummernkreis und Kurz-Links. */

export interface AssetJson {
  id: string;
  bezeichnung: string;
  kategorie: string;
  standort: string;
  seriennummer: string;
  host: string;
  ziel: string | null;
  paperless_doc: number | null;
  status: 'aktiv' | 'verworfen' | 'ausgemustert';
  notiz: string;
  created: string;
  updated: string;
}

export interface AssetRangeJson {
  prefix: string;
  width: number;
  next: string;
  check_digit: boolean;
}

export interface AssetsListResponse {
  assets: AssetJson[];
  range: AssetRangeJson;
  shortlink: boolean;
}

export interface AssetCreateBody {
  count: number;
  bezeichnung: string;
  kategorie: string;
  standort: string;
  seriennummer: string;
  host: string;
  ziel: string | null;
  paperless_doc: number | null;
  notiz: string;
}

export interface AssetImportBody {
  id: string;
  bezeichnung: string;
  kategorie: string;
  standort: string;
  seriennummer: string;
  host: string;
  ziel: string | null;
  paperless_doc: number | null;
  notiz: string;
}

export interface AssetUpdateBody {
  bezeichnung?: string;
  kategorie?: string;
  standort?: string;
  seriennummer?: string;
  host?: string;
  ziel?: string | null;
  paperless_doc?: number | null;
  notiz?: string;
}

export interface AssetCreateResponse {
  assets: AssetJson[];
  warnings: string[];
}

export interface AssetUpdateResponse extends AssetJson {
  warnings: string[];
}

export interface AssetLabelResponse {
  template: string;
  values: Record<string, string>;
  warnings: string[];
}

export interface AssetTableResponse {
  pending_id: string;
  template: string;
  count: number;
  warnings: string[];
}

/** Antwort von POST /homelab/assets/{id}/vault-note. */
export interface AssetVaultNoteResponse {
  path: string;
}
