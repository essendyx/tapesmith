/**
 * Felder der Moduleinstellungen aus homelab.json, je Abschnitt. Beschriftung und Hilfetext stehen im
 * Namespace `homelabEinstellungen` unter `fields.<camelCase(schlüssel)>` (`label`, `help`).
 */

/** Art eines Eingabefelds. */
export type HomelabFieldKind = 'text' | 'optionalText' | 'number' | 'int' | 'bool' | 'list' | 'tokenRef' | 'warranty' | 'hosts';

export interface HomelabFieldDef {
  /** Schlüssel in homelab.json, z. B. "paperless.asn_prefix". */
  key: string;
  kind: HomelabFieldKind;
  /** Einheit im Feld (`einstellungen:units.<einheit>`). */
  unit?: string;
  /** Standardwert (Platzhalter „Standard: …“ in leeren Feldern). */
  default?: string | number;
}

export const HOMELAB_FIELDS: Record<string, HomelabFieldDef[]> = {
  paperless: [
    { key: 'paperless.url', kind: 'optionalText' },
    { key: 'paperless.token_ref', kind: 'tokenRef' },
    { key: 'paperless.public_url', kind: 'optionalText' },
    { key: 'paperless.asn_range', kind: 'text', default: 'asn' },
    { key: 'paperless.asn_prefix', kind: 'text', default: 'ASN' },
    { key: 'paperless.asn_width', kind: 'int', unit: 'stellen', default: 5 },
    { key: 'paperless.warranty_fields', kind: 'warranty' },
    { key: 'paperless.timeout_s', kind: 'number', unit: 's', default: 10 },
  ],
  proxmox: [
    { key: 'proxmox.hosts', kind: 'hosts' },
    { key: 'proxmox.timeout_s', kind: 'number', unit: 's', default: 10 },
  ],
  obsidian: [
    { key: 'obsidian.mcp_url', kind: 'optionalText' },
    { key: 'obsidian.vault_dir', kind: 'optionalText' },
    { key: 'obsidian.folders', kind: 'list', default: 'Hosts, Dienste' },
    { key: 'obsidian.attachments_dir', kind: 'text', default: 'Anhänge/Labels' }, // i18n-ignore (Standardwert aus homelab.json)
    { key: 'obsidian.append_after_print', kind: 'bool' },
    { key: 'obsidian.timeout_s', kind: 'number', unit: 's', default: 10 },
  ],
  homeassistant: [
    { key: 'homeassistant.url', kind: 'optionalText' },
    { key: 'homeassistant.token_ref', kind: 'tokenRef' },
    { key: 'homeassistant.todo_entity', kind: 'optionalText' },
    { key: 'homeassistant.battery_below', kind: 'int', unit: 'prozent', default: 101 },
    { key: 'homeassistant.timeout_s', kind: 'number', unit: 's', default: 10 },
  ],
  assets: [
    { key: 'assets.range', kind: 'text', default: 'asset' },
    { key: 'assets.prefix', kind: 'text', default: 'HL-' },
    { key: 'assets.width', kind: 'int', unit: 'stellen', default: 4 },
    { key: 'assets.check_digit', kind: 'bool' },
  ],
  shortlink: [
    { key: 'shortlink.base_url', kind: 'optionalText' },
    { key: 'shortlink.token_ref', kind: 'tokenRef' },
    { key: 'shortlink.admin_url', kind: 'optionalText' },
    { key: 'shortlink.timeout_s', kind: 'number', unit: 's', default: 10 },
  ],
  kleinanzeigen: [
    { key: 'kleinanzeigen.range', kind: 'text', default: 'ka' },
    { key: 'kleinanzeigen.prefix', kind: 'text', default: 'KA-' },
    { key: 'kleinanzeigen.width', kind: 'int', unit: 'stellen', default: 3 },
  ],
  kabel: [
    { key: 'kabel.range', kind: 'text', default: 'kabel' },
    { key: 'kabel.prefix', kind: 'text', default: 'K-' },
    { key: 'kabel.width', kind: 'int', unit: 'stellen', default: 3 },
    { key: 'kabel.tia_pattern', kind: 'text', default: '{rack}.U{unit:02}:P{port:02}' },
  ],
  plausi: [
    { key: 'plausi.networks', kind: 'list', default: '192.168.0.0/16' },
    { key: 'plausi.dns_check', kind: 'bool' },
  ],
};

/** "paperless.asn_prefix" -> "paperlessAsnPrefix" (Schlüssel unter `fields.` im Namespace). */
export function fieldI18nId(key: string): string {
  return key.replace(/[._]([a-zA-Z0-9])/g, (_m, c: string) => c.toUpperCase());
}
