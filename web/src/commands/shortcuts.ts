/** Tastenkürzel: `useShortcut("Ctrl+K", …)`, Anzeige je Sprache und ein Register für die Übersicht. */
import { useEffect, useRef } from 'react';
import { currentLanguage, type Language } from '../i18n';

interface Combo {
  ctrl: boolean;
  shift: boolean;
  alt: boolean;
  key: string;
}

const KEY_ALIASES: Record<string, string> = {
  space: ' ',
  leertaste: ' ',
  esc: 'escape',
  escape: 'escape',
  enter: 'enter',
  comma: ',',
  del: 'delete',
  entf: 'delete',
  pgdn: 'pagedown',
  pgup: 'pageup',
};

export function parseCombo(combo: string): Combo {
  const result: Combo = { ctrl: false, shift: false, alt: false, key: '' };
  const parts = combo.split('+');
  // "Ctrl++" (Plus-Taste): zwei leere Teile am Ende
  if (combo.endsWith('++')) {
    parts.splice(parts.length - 2, 2);
    result.key = '+';
  }
  for (const raw of parts) {
    const p = raw.trim().toLowerCase();
    if (!p) continue;
    if (p === 'ctrl' || p === 'strg' || p === 'control') result.ctrl = true;
    else if (p === 'shift' || p === 'umschalt') result.shift = true;
    else if (p === 'alt') result.alt = true;
    else result.key = KEY_ALIASES[p] ?? p;
  }
  return result;
}

export function matchesCombo(e: KeyboardEvent, combo: Combo): boolean {
  const key = (e.key ?? '').toLowerCase();
  // `?` liegt je nach Tastatur auf Umschalt+ß oder Umschalt+/: Umschalt zählt hier nicht.
  if (combo.key === '?') return key === '?' && e.ctrlKey === combo.ctrl && e.altKey === combo.alt;
  if (e.ctrlKey !== combo.ctrl || e.shiftKey !== combo.shift || e.altKey !== combo.alt) return false;
  if (key === combo.key) return true;
  const code = e.code ?? '';
  // Die Tastenposition nur als Rückfall, wenn die Taste selbst keinen lateinischen Buchstaben bzw.
  // keine Ziffer liefert (z. B. kyrillisch, AZERTY-Ziffernreihe). Sonst löste auf QWERTZ Strg+Y
  // (Position KeyZ) zusätzlich Strg+Z aus.
  if (/^[a-z]$/.test(combo.key)) return !/^[a-z]$/.test(key) && code === `Key${combo.key.toUpperCase()}`;
  if (/^[0-9]$/.test(combo.key)) return !/^[0-9]$/.test(key) && (code === `Digit${combo.key}` || code === `Numpad${combo.key}`);
  if (combo.key === ' ') return code === 'Space';
  return false;
}

interface KeyNames {
  ctrl: string;
  shift: string;
  alt: string;
  keys: Record<string, string>;
}

const NAMES: Record<Language, KeyNames> = {
  de: {
    ctrl: 'Strg',
    shift: 'Umschalt',
    alt: 'Alt',
    keys: {
      ' ': 'Leertaste',
      escape: 'Esc',
      enter: 'Eingabe',
      pagedown: 'Bild ab',
      pageup: 'Bild auf',
      delete: 'Entf',
      arrowup: '↑',
      arrowdown: '↓',
      arrowleft: '←',
      arrowright: '→',
    },
  },
  en: {
    ctrl: 'Ctrl',
    shift: 'Shift',
    alt: 'Alt',
    keys: {
      ' ': 'Space',
      escape: 'Esc',
      enter: 'Enter',
      pagedown: 'PgDn',
      pageup: 'PgUp',
      delete: 'Del',
      arrowup: '↑',
      arrowdown: '↓',
      arrowleft: '←',
      arrowright: '→',
    },
  },
};

/**
 * Anzeige eines Kürzels in der Sprache der Oberfläche, z. B. "Ctrl+Shift+V" wird
 * „Strg+Umschalt+V“ (Deutsch) bzw. „Ctrl+Shift+V“ (Englisch).
 */
export function formatCombo(combo: string, lang: Language = currentLanguage()): string {
  const c = parseCombo(combo);
  const names = NAMES[lang];
  const parts: string[] = [];
  if (c.ctrl) parts.push(names.ctrl);
  if (c.shift) parts.push(names.shift);
  if (c.alt) parts.push(names.alt);
  const key = names.keys[c.key] ?? (c.key.length === 1 ? c.key.toUpperCase() : c.key.charAt(0).toUpperCase() + c.key.slice(1));
  parts.push(/^f\d{1,2}$/.test(c.key) ? c.key.toUpperCase() : key);
  return parts.join('+');
}

/** `aria-keyshortcuts`-Form (WAI-ARIA), z. B. "Control+Shift+V". */
export function ariaCombo(combo: string): string {
  const c = parseCombo(combo);
  const parts: string[] = [];
  if (c.ctrl) parts.push('Control');
  if (c.shift) parts.push('Shift');
  if (c.alt) parts.push('Alt');
  const special: Record<string, string> = { ' ': 'Space', escape: 'Escape', enter: 'Enter', pagedown: 'PageDown', pageup: 'PageUp', delete: 'Delete' };
  parts.push(special[c.key] ?? (c.key.length === 1 ? c.key.toUpperCase() : c.key));
  return parts.join('+');
}

// ---------- Register der laufenden Kürzel (für die Übersicht) ----------

export interface RegisteredShortcut {
  id: number;
  combo: string;
  description: string;
  group?: string;
}

let registered: RegisteredShortcut[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

function emit(): void {
  for (const fn of [...listeners]) fn();
}

/** Alle Kürzel mit Beschreibung, deren Komponenten gerade leben (älteste zuerst). */
export function listRegisteredShortcuts(): RegisteredShortcut[] {
  return registered;
}

/** Benachrichtigt bei jeder An- oder Abmeldung (für useSyncExternalStore). */
export function subscribeShortcuts(fn: () => void): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

function registerShortcut(entry: Omit<RegisteredShortcut, 'id'>): () => void {
  const item: RegisteredShortcut = { ...entry, id: nextId };
  nextId += 1;
  registered = [...registered, item];
  emit();
  return () => {
    registered = registered.filter((r) => r !== item);
    emit();
  };
}

function isTextInput(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (tag === 'INPUT') {
    const type = (target as HTMLInputElement).type;
    return !['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'color', 'file'].includes(type);
  }
  const role = target.getAttribute('role');
  return role === 'textbox' || role === 'combobox' || role === 'spinbutton';
}

function insideOverlay(target: EventTarget | null): boolean {
  return (
    target instanceof Element &&
    target.closest('[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"]') !== null
  );
}

export interface ShortcutOptions {
  enabled?: boolean;
  allowInInputs?: boolean;
  /** Übersetzte Beschreibung: das Kürzel erscheint dann in der Tastenkürzel-Übersicht. */
  description?: string;
  /** Übersetzte Gruppe in der Übersicht (Standard: „Diese Seite“). */
  group?: string;
}

/**
 * Globales Kürzel, solange die Komponente lebt. Kürzel ohne Strg/Alt wirken nicht in Eingabefeldern
 * (außer mit `allowInInputs`) und nicht innerhalb offener Dialoge oder Menüs. Mit `description`
 * meldet sich das Kürzel in der Übersicht an (nur solange es aktiv ist).
 */
export function useShortcut(combo: string, handler: (e: KeyboardEvent) => void, opts?: ShortcutOptions): void {
  const enabled = opts?.enabled ?? true;
  const allowInInputs = opts?.allowInInputs ?? false;
  const description = opts?.description;
  const group = opts?.group;
  const ref = useRef(handler);
  ref.current = handler;

  useEffect(() => {
    if (!enabled) return undefined;
    const parsed = parseCombo(combo);
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing || e.defaultPrevented) return;
      if (!matchesCombo(e, parsed)) return;
      if (!allowInInputs && isTextInput(e.target)) return;
      if (!parsed.ctrl && !parsed.alt && insideOverlay(e.target)) return;
      e.preventDefault();
      ref.current(e);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [combo, enabled, allowInInputs]);

  useEffect(() => {
    if (!enabled || !description) return undefined;
    return registerShortcut({ combo, description, group });
  }, [combo, enabled, description, group]);
}
