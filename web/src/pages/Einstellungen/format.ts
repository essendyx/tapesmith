/** Formatierungshelfer der Einstellungsseite: Tastenkürzel, Größenangaben, Byte-Anzeige. */
import type { KeyboardEvent } from 'react';

/**
 * Baut aus einem Tastendruck die Anzeigeform „Ctrl+Alt+K“ (englische Kurznamen, Reihenfolge
 * Ctrl, Alt, Shift, Win, Taste). Gibt `null` zurück, solange nur eine Zusatztaste gedrückt ist.
 */
export function hotkeyFromEvent(e: KeyboardEvent): string | null {
  const { key } = e;
  if (key === 'Control' || key === 'Alt' || key === 'Shift' || key === 'Meta' || key === 'OS') return null;
  const parts: string[] = [];
  if (e.ctrlKey) parts.push('Ctrl');
  if (e.altKey) parts.push('Alt');
  if (e.shiftKey) parts.push('Shift');
  if (e.metaKey) parts.push('Win');
  let main = key;
  if (main.length === 1) main = main.toUpperCase();
  else if (/^[Ff]([1-9]|1[0-9]|2[0-4])$/.test(main)) main = main.toUpperCase();
  else if (main === ' ') main = 'Leertaste';
  parts.push(main);
  return parts.join('+');
}

export function formatBytes(n: number): string {
  if (!Number.isFinite(n) || n < 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = n;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  const text = i === 0 ? String(value) : value.toFixed(value < 10 ? 1 : 0);
  return `${text} ${units[i]}`;
}

export function formatUptime(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const parts: string[] = [];
  if (days > 0) parts.push(`${days} T`);
  if (days > 0 || hours > 0) parts.push(`${hours} Std`);
  parts.push(`${minutes} Min`);
  return parts.join(' ');
}

const CARD_WIDTH_MM = 85.6;

export function screenPxPerMmFromCardWidth(widthPx: number): number {
  return widthPx / CARD_WIDTH_MM;
}

export function cardWidthPxFromScreenPxPerMm(value: number): number {
  return value * CARD_WIDTH_MM;
}
