/** Testdaten für `/api/v1/secrets` (nur Zustand, nie Werte). */
import type { SecretSlot } from '../api/secrets';

export const DEFAULT_SECRET_SLOTS: SecretSlot[] = [
  { id: 'mqtt', label: 'MQTT-Passwort', source: 'tapesmith', set: false, module: null, module_enabled: true, target: '/zugriff' },
  { id: 'telegram', label: 'Telegram-Bot-Token', source: 'none', set: false, module: null, module_enabled: true, target: '/zugriff' },
  { id: 'paperless', label: 'Paperless', source: 'none', set: false, module: 'paperless', module_enabled: true, target: '/einstellungen?abschnitt=modul-paperless' },
  { id: 'homeassistant', label: 'Home Assistant', source: 'none', set: false, module: 'homeassistant', module_enabled: true, target: '/einstellungen?abschnitt=modul-homeassistant' },
  { id: 'shortlink', label: 'Kurz-Link-Dienst', source: 'none', set: false, module: 'assets', module_enabled: true, target: '/einstellungen?abschnitt=modul-assets' },
];

/** Standard-Slots, einzelne per `id` überschrieben oder ergänzt. */
export function makeSecrets(overrides: Partial<SecretSlot>[] = []): { slots: SecretSlot[] } {
  const slots = DEFAULT_SECRET_SLOTS.map((slot) => ({ ...slot, ...overrides.find((o) => o.id === slot.id) }));
  for (const extra of overrides) {
    if (extra.id && !slots.some((s) => s.id === extra.id)) {
      slots.push({ id: extra.id, label: extra.label ?? extra.id, source: extra.source ?? 'none', set: extra.set ?? false,
        module: extra.module ?? null, module_enabled: extra.module_enabled ?? true, target: extra.target ?? '/zugriff' });
    }
  }
  return { slots };
}
