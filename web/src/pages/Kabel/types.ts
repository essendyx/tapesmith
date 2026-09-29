/** Typen der Seite Kabel: NetBox-Import, TIA-606-ID-Schema, Kabel-Register. */

export interface CableRowJson {
  kabel_id: string;
  quelle: string;
  ziel: string;
  kabeltyp: string;
  farbe: string;
  laenge: string;
  neu: boolean;
}

/** Zuordnungswert: eine Spalte oder (für Quelle/Ziel) eine Liste von Spalten (kombiniert). */
export type ColumnMappingValue = string | string[];
export type ColumnMapping = Record<string, ColumnMappingValue>;

export interface NetboxPreviewJson {
  headers: string[];
  mapping: ColumnMapping;
  rows: CableRowJson[];
  duplicates: string[];
  warnings: string[];
  preview_only: true;
}

export interface NetboxTableJson {
  pending_id: string;
  template: string;
  count: number;
  new_ids: string[];
  duplicates: string[];
  warnings: string[];
}

export interface PortRangeInput {
  rack: string;
  units: string;
  ports: string;
}

export interface IdsRequest {
  mode: 'schema' | 'frei';
  pattern?: string;
  ranges?: PortRangeInput[];
  count?: number;
  register?: boolean;
  table?: boolean;
}

export interface IdsResultJson {
  ids: string[];
  duplicates: string[];
  pending_id: string | null;
}

export interface KabelEntryJson {
  id: string;
  quelle: string;
  ziel: string;
  kabeltyp: string;
  quelle_import: string;
  created: string;
}

export interface KabelRegisterJson {
  entries: KabelEntryJson[];
}

/**
 * Felder der NetBox-Zuordnung (Reihenfolge wie `integrations.netbox.FIELDS`). Beschriftung unter
 * `mappingFields.<id>` im Namespace kabel.
 */
export const MAPPING_FIELDS: { id: string; multi: boolean }[] = [
  { id: 'kabel_id', multi: false },
  { id: 'quelle', multi: true },
  { id: 'ziel', multi: true },
  { id: 'kabeltyp', multi: false },
  { id: 'farbe', multi: false },
  { id: 'laenge', multi: false },
];
