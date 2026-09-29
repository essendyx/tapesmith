/** Typen der Seite Paperless: ASN-Serien, Garantie-Etikett. */

export interface AsnNextJson {
  paperless_next: number;
  local_next: string | null;
  next: string;
  prefix: string;
  width: number;
  hint: string;
}

export interface AsnReserveJson {
  numbers: string[];
  pending_id: string;
  template: string;
  hint: string;
}

export interface DocumentHitJson {
  id: number;
  title: string;
  created: string;
  correspondent: string | null;
  asn: number | null;
  custom: Record<string, string>;
  url: string;
}

export interface WarrantyJson {
  document: DocumentHitJson;
  kaufdatum: string;
  monate: number | null;
  ende: string | null;
  quelle: string;
  quelle_ende: string;
}

export interface WarrantyResponseJson {
  warranty: WarrantyJson;
  label: { template: string; values: Record<string, string> };
  warnings: string[];
}

export interface DocumentSearchParams {
  query: string;
  correspondent: string;
  date_from: string;
  date_to: string;
}
