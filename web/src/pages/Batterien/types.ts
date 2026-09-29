/** Typen der Seite Batterien (Endpunkte `/api/v1/homelab/ha/*`). */

export interface BatteryDeviceJson {
  entity_id: string;
  device: string;
  area: string;
  level: number | null;
  low: boolean;
  battery_type: string;
  type_source: string;
  manufacturer: string;
  model: string;
}

export interface BatteriesJson {
  devices: BatteryDeviceJson[];
  todo_entity: string | null;
  warnings: string[];
}

export interface TableRequest {
  entity_ids: string[];
  datum?: string;
}

export interface TableResponse {
  pending_id: string;
  template: string;
  count: number;
  warnings: string[];
}

export interface TodoRequest {
  item: string;
  due: string;
  description?: string;
}

export interface TodoResponse {
  ok: boolean;
  entity_id: string;
}

/** Gängige Batterietypen für die Combobox (frei eingebbar, nicht abschließend). */
export const BATTERY_TYPE_CHOICES = ['CR2032', 'CR2450', 'AA', 'AAA', 'CR123A', '9V'];

/** Schnellknöpfe für häufige Wartungen; Beschriftung unter `wartung.suggestions.<id>` im Namespace batterien. */
export const WARTUNG_SUGGESTIONS: { id: string; months: number }[] = [
  { id: 'usvAkku', months: 36 },
  { id: 'luftfilter', months: 6 },
  { id: 'waermeleitpaste', months: 36 },
  { id: 'rauchmelderTesten', months: 12 },
];
