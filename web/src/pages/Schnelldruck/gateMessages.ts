/**
 * Kennungen der Gründe des Fehldruckschutzes (`quickGate.ts`, reine Logik ohne i18n) für die
 * Übersetzung. Gemeinsam für Schnelldruck und Kompakt genutzt.
 */
import { REASONS } from './quickGate';

const REASON_IDS: Record<string, string> = {
  [REASONS.empty]: 'empty',
  [REASONS.busy]: 'busy',
  [REASONS.stale]: 'stale',
  [REASONS.invalid]: 'invalid',
  [REASONS.review]: 'review',
  [REASONS.debounce]: 'debounce',
  [REASONS.repeat]: 'repeat',
  [REASONS.lines]: 'lines',
};

/** Kennung eines Fehldruckschutz-Grundes für die Übersetzung (Schlüssel `gate.<id>`), `null` bei leerem Text. */
export function gateReasonId(reason: string): string | null {
  if (!reason) return null;
  return REASON_IDS[reason] ?? null;
}
