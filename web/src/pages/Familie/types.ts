/** JSON-Typen der Familienrouten. Eigenständig, kein Import aus ../../api/types. */

export interface FamilyField {
  id: string;
  label: string;
  type: string;
  default: string | null;
  required: boolean;
  choices: string[];
  /** Anzeige je Auswahlwert (der Wert selbst wird gedruckt). */
  choice_labels?: Record<string, string>;
  max_len: number | null;
  multiline: boolean;
}

export interface FamilyTemplate {
  name: string;
  title: string;
  description: string;
  category: string;
  fields: FamilyField[];
  sample: Record<string, string>;
}

export interface FamilyTemplatesResponse {
  templates: FamilyTemplate[];
  max_copies: number;
}

export interface FamilyPreview {
  ok: boolean;
  errors: string[];
  warnings: string[];
  design_png: string | null;
  width: number | null;
  height: number | null;
  length_mm: number | null;
}

export type FamilyPrintStatus = 'ok' | 'wartet' | 'bestätigung_nötig' | 'abgelehnt' | 'abgebrochen' | 'unvollständig' | 'fehler'; // i18n-ignore (Server-Werte)

export interface FamilyPrintResult {
  status: FamilyPrintStatus;
  message: string;
  reasons: string[];
  queue_id: number | null;
}

export interface FamilyStatus {
  online: boolean;
  text: string;
  waiting: number;
}
