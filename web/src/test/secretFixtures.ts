/** Testdaten für `/api/v1/secrets` (nur Zustand, nie Werte). */
import type { SecretSlot } from '../api/secrets';

export const DEFAULT_SECRET_SLOTS: SecretSlot[] = [
  { id: 'mqtt', label: 'MQTT-Passwort', source: 'tapesmith', set: false },
  { id: 'telegram', label: 'Telegram-Bot-Token', source: 'none', set: false },
  { id: 'paperless', label: 'Paperless', source: 'none', set: false },
  { id: 'homeassistant', label: 'Home Assistant', source: 'none', set: false },
  { id: 'shortlink', label: 'Kurz-Link-Dienst', source: 'none', set: false },
];

/** Standard-Slots, einzelne per `id` überschrieben oder ergänzt. */
export function makeSecrets(overrides: Partial<SecretSlot>[] = []): { slots: SecretSlot[] } {
  const slots = DEFAULT_SECRET_SLOTS.map((slot) => ({ ...slot, ...overrides.find((o) => o.id === slot.id) }));
  for (const extra of overrides) {
    if (extra.id && !slots.some((s) => s.id === extra.id)) {
      slots.push({ id: extra.id, label: extra.label ?? extra.id, source: extra.source ?? 'none', set: extra.set ?? false });
    }
  }
  return { slots };
}
