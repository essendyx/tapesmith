/** Typen der Endpunkte /api/v1/homelab/settings und /homelab/check. */

/** Ein Proxmox-Host aus `proxmox.hosts` (öffentliche Sicht mit Token-Status). */
export interface ProxmoxHostJson {
  name: string;
  url: string;
  token_ref: string;
  verify_tls?: boolean;
  token_describe?: string;
  token_set?: boolean;
}

/** Einstellungen je Sektion; Sektionen mit `token_ref` tragen zusätzlich `token_describe` und `token_set`. */
export type HomelabSettings = Record<string, Record<string, unknown>>;

export interface HomelabSettingsJson {
  settings: HomelabSettings;
  path: string;
}

export interface ServiceCheckJson {
  id: string;
  label: string;
  configured: boolean;
  token_set: boolean | null;
  detail: string;
}

export interface HomelabCheckJson {
  services: ServiceCheckJson[];
}
