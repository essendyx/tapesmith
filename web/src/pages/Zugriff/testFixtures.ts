/** Test-Fixtures der Zugriffsseite (nur für Vitest, kein Laufzeitcode). */
import type { MockHandler } from '../../test/utils';
import type { AccessJson } from './types';

export function makeAccess(overrides?: Partial<AccessJson>): AccessJson {
  const base: AccessJson = {
    lan: {
      enabled: false,
      bind: '0.0.0.0',
      allowed_networks: ['192.0.2.0/24'],
      hostnames: [],
      public_url: null,
      active: false,
      restart_needed: false,
      listen: ['127.0.0.1:8712'],
      base_urls: ['http://127.0.0.1:8712'],
    },
    local_addresses: ['192.0.2.5'],
    tokens: [
      {
        id: 'a1b2c3d4',
        name: 'Handy',
        role: 'familie',
        role_label: 'Familie',
        created: '2026-09-01T10:00:00',
        last_used: '2026-09-28T09:00:00',
        hint: 'p12_a1b2c3d4_...',
      },
      {
        id: 'e5f6a7b8',
        name: 'Verwaltung',
        role: 'admin',
        role_label: 'Verwaltung',
        created: '2026-08-01T10:00:00',
        last_used: null,
        hint: 'p12_e5f6a7b8_...',
      },
    ],
    family: {
      templates: ['gefriergut', 'geoeffnet-am', 'vorratsdose'],
      max_copies: 5,
      available: [
        { name: 'gefriergut', description: 'Gefriergut' },
        { name: 'geoeffnet-am', description: 'Geöffnet am' },
        { name: 'vorratsdose', description: 'Vorratsdose' },
        { name: 'schule', description: 'Schule' },
        { name: 'eigentum', description: 'Eigentum' },
      ],
    },
    mcp: { http: true, url: 'http://127.0.0.1:8712/mcp', stdio_command: 'C:/App/python.exe -m tapesmith.cli mcp' },
    hotfolder: { enabled: false, dir: null, effective_dir: 'C:/App/hotfolder', poll_s: 2.0, settle_s: 1.5, max_bytes: 2000000 },
    mqtt: {
      enabled: false,
      host: '192.0.2.9',
      port: 1883,
      username: 'tapesmith',
      password_ref: 'keyring:tapesmith/mqtt',
      password_describe: 'Windows-Anmeldeinformationen tapesmith/mqtt',
      password_set: false,
      base_topic: 'tapesmith',
      discovery_prefix: 'homeassistant',
      templates: [],
      tls: false,
      keepalive_s: 60,
    },
    telegram: {
      enabled: false,
      token_ref: 'file:C:\\Tokens\\.telegram_bot_token',
      token_describe: 'Datei C:\\Tokens\\.telegram_bot_token',
      token_set: true,
      chat_id: null,
      quiet_hours: '22:00-07:00',
      offline_min: 30,
      queue_stuck_min: 15,
      roll_low_m: 0.5,
      notify_queue: true,
      notify_offline: true,
      notify_error: true,
      notify_roll: true,
    },
    addons: [
      { name: 'hotfolder', running: false, error: null, detail: 'aus' },
      { name: 'mqtt', running: false, error: null, detail: 'aus' },
      { name: 'telegram', running: false, error: null, detail: 'aus' },
    ],
  };
  return { ...base, ...overrides };
}

/** Ruhige Standardantworten für die Zugriffsseite (überschreibbar). */
export function baseAccessRoutes(overrides?: Record<string, MockHandler>): Record<string, MockHandler> {
  return {
    'GET /api/v1/access': () => makeAccess(),
    ...overrides,
  };
}
