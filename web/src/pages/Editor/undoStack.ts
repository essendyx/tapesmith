/**
 * Unbegrenztes Undo/Redo mit benannten Schritten, Sprung und Zusammenfassen.
 * Reine Logik, unveränderliche Zustände (für React-State). Vorbild: `document/undo.py`.
 */
import type { LabelDocumentJson } from '../../api/types';

export const MERGE_WINDOW_MS = 1000;

export interface UndoEntry {
  id: number;
  label: string;
  doc: LabelDocumentJson;
  at: number;
}

export interface UndoState {
  entries: UndoEntry[];
  index: number;
  savedId: number;
  nextId: number;
  lastMergeKey: string | null;
}

export function createUndo(doc: LabelDocumentJson, label = 'Neues Label', now: number = Date.now()): UndoState {
  return { entries: [{ id: 1, label, doc, at: now }], index: 0, savedId: 1, nextId: 2, lastMergeKey: null };
}

export function reset(s: UndoState, doc: LabelDocumentJson, label = 'Neues Label', now: number = Date.now()): UndoState {
  const id = s.nextId;
  return { entries: [{ id, label, doc, at: now }], index: 0, savedId: id, nextId: id + 1, lastMergeKey: null };
}

export function current(s: UndoState): LabelDocumentJson {
  return (s.entries[s.index] ?? s.entries[0]!).doc;
}

function sameDoc(a: LabelDocumentJson, b: LabelDocumentJson): boolean {
  return a === b || JSON.stringify(a) === JSON.stringify(b);
}

/**
 * Neuer Schritt. Gleicher `mergeKey` wie beim letzten Schritt, am Ende des Stapels und innerhalb
 * von `windowMs` (gleitend) ersetzt den letzten Schritt statt einen neuen anzulegen.
 */
export function push(
  s: UndoState,
  doc: LabelDocumentJson,
  label: string,
  opts?: { mergeKey?: string | null; now?: number; windowMs?: number },
): UndoState {
  if (sameDoc(doc, current(s))) return s;
  const now = opts?.now ?? Date.now();
  const mergeKey = opts?.mergeKey ?? null;
  const windowMs = opts?.windowMs ?? MERGE_WINDOW_MS;
  const last = s.entries[s.index];
  const atEnd = s.index === s.entries.length - 1;
  if (mergeKey !== null && last && s.index > 0 && atEnd && s.lastMergeKey === mergeKey && now - last.at <= windowMs) {
    const entries = s.entries.slice();
    entries[s.index] = { id: s.nextId, label: last.label, doc, at: now };
    return { ...s, entries, nextId: s.nextId + 1 };
  }
  const entries = [...s.entries.slice(0, s.index + 1), { id: s.nextId, label, doc, at: now }];
  return { ...s, entries, index: entries.length - 1, nextId: s.nextId + 1, lastMergeKey: mergeKey };
}

export const canUndo = (s: UndoState): boolean => s.index > 0;
export const canRedo = (s: UndoState): boolean => s.index < s.entries.length - 1;

export function undo(s: UndoState): UndoState {
  return canUndo(s) ? { ...s, index: s.index - 1, lastMergeKey: null } : s;
}

export function redo(s: UndoState): UndoState {
  return canRedo(s) ? { ...s, index: s.index + 1, lastMergeKey: null } : s;
}

export function jump(s: UndoState, index: number): UndoState {
  if (!Number.isInteger(index) || index < 0 || index >= s.entries.length) return s;
  return { ...s, index, lastMergeKey: null };
}

export function labels(s: UndoState): string[] {
  return s.entries.map((e) => e.label);
}

export function markSaved(s: UndoState): UndoState {
  return { ...s, savedId: (s.entries[s.index] ?? s.entries[0]!).id };
}

export function isDirty(s: UndoState): boolean {
  return (s.entries[s.index] ?? s.entries[0]!).id !== s.savedId;
}
