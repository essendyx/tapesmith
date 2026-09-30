/** Test-Fixtures der Einstellungsseite (nur für Vitest, kein Laufzeitcode). */
import type { MockHandler } from '../../test/utils';
import type { SettingsJson } from '../../api/types';
import type { UpdateStatus } from '../../api/update';

/** Ruhiger Standardzustand für `GET /update/status` (installierte, aktuelle Version, kein Update verfügbar). */
export function makeUpdateStatus(overrides?: Partial<UpdateStatus>): UpdateStatus {
  return {
    installed: true,
    current: '0.2.0',
    previous: null,
    root: 'C:/Users/test/AppData/Local/Programs/Tapesmith',
    enabled: true,
    source: 'github:essendyx/tapesmith',
    channel: 'stable',
    auto_install: false,
    last_check: null,
    available: null,
    state: 'idle',
    error: null,
    can_rollback: false,
    idle_ok: false,
    consent_needed: false,
    ...overrides,
  };
}

export function makeSettings(overrides?: Partial<SettingsJson>): SettingsJson {
  const base: SettingsJson = {
    config_path: 'C:/Users/test/AppData/Roaming/Tapesmith/config.json',
    sections: [
      {
        id: 'verbindung',
        title: 'Verbindung',
        fields: [
          {
            key: 'transport',
            label: 'Verbindung',
            type: 'choice',
            value: 'bt:COM5',
            default: 'auto',
            nullable: false,
            choices: [
              { value: 'auto', label: 'Automatisch' },
              { value: 'bt:COM5', label: 'Bluetooth COM5' },
            ],
            help: 'Wie der Dienst den Drucker erreicht.',
            visibility: 'erweitert',
          },
        ],
      },
      {
        id: 'allgemein',
        title: 'Allgemein',
        fields: [
          {
            key: 'app.ctrl_enter_only',
            label: 'Nur mit Strg+Enter drucken',
            type: 'bool',
            value: false,
            default: false,
            nullable: false,
            help: 'Verhindert versehentliches Drucken beim Tippen.',
          },
          {
            key: 'web.port',
            label: 'Web-Port',
            type: 'int',
            value: 8712,
            default: 8712,
            nullable: false,
            min: 1024,
            max: 65535,
            step: 1,
            restart: true,
            help: 'Port der lokalen Web-Oberfläche.',
          },
          {
            // Eigener Testschlüssel (kein Schlüssel aus dem echten Schema): sonst würde die
            // Feldübersetzung den Server-Fallback-Text dieses reinen Mock-Feldes überschreiben.
            key: 'test.design_choice',
            label: 'Design',
            type: 'choice',
            value: 'system',
            default: 'system',
            nullable: false,
            choices: [
              { value: 'system', label: 'System' },
              { value: 'light', label: 'Hell' },
              { value: 'dark', label: 'Dunkel' },
            ],
          },
          {
            key: 'templates.dir',
            label: 'Vorlagenordner',
            type: 'path',
            value: 'C:/Vorlagen',
            default: null,
            nullable: true,
          },
          {
            // Eigener Testschlüssel, siehe Hinweis bei `test.design_choice`.
            key: 'test.quick_hotkey',
            label: 'Schnelldruck-Kürzel',
            type: 'hotkey',
            value: 'Ctrl+Alt+L',
            default: 'Ctrl+Alt+L',
            nullable: false,
          },
          {
            key: 'experimental.ble_scan',
            label: 'BLE-Suche',
            type: 'bool',
            value: false,
            default: false,
            nullable: false,
            experimental: true,
          },
        ],
      },
      {
        id: 'ssh',
        title: 'SSH-Hosts',
        module: 'datentraeger',
        fields: [
          {
            key: 'ssh.hosts',
            label: 'SSH-Hosts',
            type: 'json',
            value: [],
            default: [],
            nullable: false,
          },
        ],
      },
      {
        // Text-identisch zum echten Schema (settings_schema.py), damit die Übersetzung (fields.*)
        // hier keinen abweichenden Text erzeugt: prüft die Kollision mit der Karte „Druckdienst“ (id).
        id: 'druckdienst',
        title: 'Druckdienst und Warteschlange',
        fields: [
          { key: 'queue.enabled', label: 'Warteschlange aktiv', type: 'bool', value: true, default: true, nullable: false },
        ],
      },
      {
        // Text-identisch zum echten Schema: prüft die Update-Einbindung ohne Kollision mit UpdateCard.
        id: 'updates',
        title: 'Updates',
        fields: [
          {
            key: 'update.source',
            label: 'Update-Quelle',
            type: 'string',
            value: 'github:essendyx/tapesmith',
            default: null,
            nullable: false,
            help: 'github:owner/repo, file:Ordner oder https-Adresse',
          },
          {
            key: 'update.channel',
            label: 'Kanal',
            type: 'choice',
            value: 'stable',
            default: 'stable',
            nullable: false,
            choices: [
              { value: 'stable', label: 'Stabil' },
              { value: 'beta', label: 'Beta' },
            ],
          },
        ],
      },
      {
        id: 'tray',
        title: 'Tray',
        fields: [
          {
            key: 'tray.favorites',
            label: 'Tray-Favoriten',
            type: 'json',
            value: [],
            default: [],
            nullable: false,
          },
        ],
      },
    ],
  };
  return { ...base, ...overrides };
}

/** Ruhige Standardantworten für alle Karten außer den generischen Feldern (überschreibbar). */
export function baseSettingsRoutes(overrides?: Record<string, MockHandler>): Record<string, MockHandler> {
  return {
    'GET /api/v1/settings': () => makeSettings(),
    'GET /api/v1/settings/ports': () => ({ transports: [{ value: 'auto', label: 'Automatisch', experimental: false }] }),
    'GET /api/v1/status': () => ({
      report: { state: { state: 'bereit', transport: 'bt:COM5', last_error: null, leased: false }, status: null, checked_at: null },
      view: { chip: 'Bereit', role: 'success', title: 'Bereit', detail: 'Bereit', tooltip: 'Bereit' },
    }),
    'GET /api/v1/tapes': () => ({ tapes: [], current: '' }),
    'GET /api/v1/rolls': () => ({ current: null, all: [] }),
    'GET /api/v1/calibration': () => ({ length_factor: 1, leader_mm: 5, trailer_mm: 5, content_offset: 8, content_dots: 80, verified: [], path: '' }),
    'GET /api/v1/daemon': () => ({ pid: 1, version: '0.9.0', uptime_s: 60, web_port: 8712, home_key: 'test', log_path: 'p12d.log', app_dir: 'C:/App' }),
    'GET /api/v1/integration': () => ({ status: { context: 'nicht installiert', uri: 'nicht installiert', autostart: 'nicht installiert' }, lines: [] }),
    'GET /api/v1/backups': () => ({ dir: 'C:/Sicherung', backups: [] }),
    'GET /api/v1/templates': () => ({ templates: [] }),
    'GET /api/v1/update/status': () => makeUpdateStatus(),
    'GET /api/v1/homelab/settings': () => ({ settings: {}, path: 'C:/App/homelab.json' }),
    ...overrides,
  };
}

/**
 * Alle Abschnitts- und Feldschlüssel des echten Schemas (`src/tapesmith/webapi/settings_schema.py`),
 * damit ein Test prüfen kann, dass `de/einstellungen.json` und `en/einstellungen.json` für jeden
 * Schlüssel einen Eintrag `sections.<id>` bzw. `fields.<schlüssel mit "_">.label` haben.
 */
export const ALL_SETTINGS_SECTIONS: readonly { id: string; fields: readonly string[] }[] = [
  { id: 'verbindung', fields: ['transport', 'mac'] },
  {
    id: 'drucken',
    fields: [
      'gui_ctrl_enter_only',
      'cut_pause_s',
      'guard_confirm_label_mm',
      'guard_confirm_copies',
      'guard_max_label_mm',
      'guard_max_request_mm',
      'guard_max_copies',
    ],
  },
  { id: 'warteschlange', fields: ['queue_enabled', 'queue_auto_retry'] },
  { id: 'editor', fields: ['gui_editor_snap', 'gui_editor_grid_mm'] },
  { id: 'tray', fields: ['hotkey_enabled', 'hotkey_quick', 'hotkey_clipboard', 'tray_notify', 'tray_favorites'] },
  { id: 'oberflaeche', fields: ['app_language', 'app_theme'] },
  { id: 'updates', fields: ['update_enabled', 'update_auto_install', 'update_channel'] },
  { id: 'sicherung', fields: ['backup_auto_daily', 'backup_keep', 'backup_dir'] },
  { id: 'vorlagen', fields: ['templates_dir'] },
  { id: 'archiv', fields: ['archive_dir', 'archive_git_commit'] },
  { id: 'druckdienst', fields: ['web_port'] },
  { id: 'ble', fields: ['ble_address', 'ble_scan_timeout_s'] },
  { id: 'ssh', fields: ['ssh_hosts', 'ssh_timeout_s', 'ssh_strict_host_key'] },
];
