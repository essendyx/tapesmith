/** JSON-Typen der Zugriffsseite. */

export type Role = 'admin' | 'drucken' | 'familie';

/** Anzeige der Rollenwerte kommt aus der Übersetzung (Namespace zugriff, newToken.role<Rolle>Label/Help). */
export const ROLES: readonly Role[] = ['admin', 'drucken', 'familie'];

export interface TokenInfoJson {
  id: string;
  name: string;
  role: Role;
  role_label: string;
  created: string;
  last_used: string | null;
  hint: string;
}

export interface AddonStatus {
  name: 'hotfolder' | 'mqtt' | 'telegram' | 'update';
  running: boolean;
  error: string | null;
  detail: string;
}

export interface AccessLan {
  enabled: boolean;
  bind: string;
  allowed_networks: string[];
  hostnames: string[];
  public_url: string | null;
  active: boolean;
  restart_needed: boolean;
  listen: string[];
  base_urls: string[];
}

export interface AccessFamilyAvailable {
  name: string;
  description: string;
}

export interface AccessFamily {
  templates: string[];
  max_copies: number;
  available: AccessFamilyAvailable[];
}

export interface AccessMcp {
  http: boolean;
  url: string;
  stdio_command: string;
}

export interface AccessHotfolder {
  enabled: boolean;
  dir: string | null;
  effective_dir: string;
  poll_s: number;
  settle_s: number;
  max_bytes: number;
}

export interface AccessMqtt {
  enabled: boolean;
  host: string;
  port: number;
  username: string | null;
  password_ref: string | null;
  password_describe: string;
  password_set: boolean;
  base_topic: string;
  discovery_prefix: string;
  templates: string[];
  tls: boolean;
  keepalive_s: number;
}

export interface AccessTelegram {
  enabled: boolean;
  token_ref: string | null;
  token_describe: string;
  token_set: boolean;
  chat_id: string | number | null;
  quiet_hours: string | null;
  offline_min: number;
  queue_stuck_min: number;
  roll_low_m: number;
  notify_queue: boolean;
  notify_offline: boolean;
  notify_error: boolean;
  notify_roll: boolean;
}

export interface AccessJson {
  lan: AccessLan;
  local_addresses: string[];
  tokens: TokenInfoJson[];
  family: AccessFamily;
  mcp: AccessMcp;
  hotfolder: AccessHotfolder;
  mqtt: AccessMqtt;
  telegram: AccessTelegram;
  addons: AddonStatus[];
}

export interface CreateTokenResponse {
  token: TokenInfoJson;
  secret: string;
  family_urls: string[];
}
