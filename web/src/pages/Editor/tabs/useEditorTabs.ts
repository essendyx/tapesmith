/**
 * Tabs des Editors: mehrere Etiketten je Fenster, jedes mit eigenem Undo-Stapel.
 * Reine Zustandsfunktionen plus ein Hook, der den Zustand zusätzlich in einem Ref spiegelt, damit
 * asynchrone Bearbeitungen immer den aktuellen Stand lesen.
 */
import { useCallback, useMemo, useRef, useState } from 'react';
import type { LabelDocumentJson } from '../../../api/types';
import { createUndo, current, isDirty, markSaved as markUndoSaved, reset, type UndoState } from '../undoStack';

export const MAX_TABS = 12;

export interface EditorTab {
  id: string;
  title: string;
  docName: string | null;
  undo: UndoState;
  /** Dokument beim letzten Laden bzw. Speichern (JSON). */
  savedJson: string;
  order: number;
  /** Nummer bei „Unbenannt N“, sonst null. */
  untitledNo: number | null;
  /** Aus einem ungespeicherten Entwurf wiederhergestellt: bleibt bis zum Speichern ungespeichert. */
  restoredDirty: boolean;
  /** Aus einem Entwurf auf dem Server entstanden (für das Autosave schon gesichert). */
  fromDraft: boolean;
}

export interface TabsState {
  tabs: EditorTab[];
  activeId: string;
}

export interface TabMeta {
  title?: string;
  docName?: string | null;
  /** Name des ersten Undo-Schritts. */
  label?: string;
}

export interface TabSeed {
  id: string;
  title: string;
  docName: string | null;
  document: LabelDocumentJson;
  dirty: boolean;
  label?: string;
  /** Stand ist neuer als der Entwurf auf dem Server (Übergabe eines verlassenen Editors): neu sichern. */
  unsynced?: boolean;
}

export type UntitledTitle = (n: number) => string;

export const EMPTY_DOCUMENT: LabelDocumentJson = { version: 1, objects: [] };

export function newTabId(): string {
  try {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  } catch {
    // Rückfall unten
  }
  return `tab-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

/** Ungespeichert: Undo-Stapel geändert, unbenannt mit Objekten oder aus ungespeichertem Entwurf. */
export function isTabDirty(tab: EditorTab): boolean {
  return tab.restoredDirty || isDirty(tab.undo) || (tab.docName === null && current(tab.undo).objects.length > 0);
}

/** Leer und unverändert (darf durch ein geöffnetes Dokument ersetzt werden). */
export function isTabBlank(tab: EditorTab): boolean {
  return tab.docName === null && !isTabDirty(tab) && current(tab.undo).objects.length === 0 && tab.undo.entries.length === 1;
}

function freeUntitledNo(tabs: EditorTab[]): number {
  const used = new Set(tabs.map((t) => t.untitledNo).filter((n): n is number => n !== null));
  let n = 1;
  while (used.has(n)) n += 1;
  return n;
}

function renumber(tabs: EditorTab[]): EditorTab[] {
  return tabs.map((t, i) => (t.order === i ? t : { ...t, order: i }));
}

function makeTab(
  tabs: EditorTab[],
  doc: LabelDocumentJson,
  meta: TabMeta,
  untitled: UntitledTitle,
  id: string = newTabId(),
): EditorTab {
  const docName = meta.docName ?? null;
  const untitledNo = docName === null && !meta.title ? freeUntitledNo(tabs) : null;
  const title = meta.title ?? docName ?? untitled(untitledNo ?? 1);
  return {
    id,
    title,
    docName,
    undo: createUndo(doc, meta.label),
    savedJson: JSON.stringify(doc),
    order: tabs.length,
    untitledNo,
    restoredDirty: false,
    fromDraft: false,
  };
}

export function initialTabs(untitled: UntitledTitle): TabsState {
  const tab = makeTab([], EMPTY_DOCUMENT, {}, untitled);
  return { tabs: [tab], activeId: tab.id };
}

/** Neuer Tab am Ende (aktiv); `null`, wenn schon MAX_TABS offen sind. */
export function addTab(s: TabsState, doc: LabelDocumentJson, meta: TabMeta, untitled: UntitledTitle): { state: TabsState; id: string } | null {
  if (s.tabs.length >= MAX_TABS) return null;
  const tab = makeTab(s.tabs, doc, meta, untitled);
  return { state: { tabs: [...s.tabs, tab], activeId: tab.id }, id: tab.id };
}

/** Schließt einen Tab; aktiv wird der rechte, sonst der linke Nachbar. Der letzte Tab wird durch einen leeren ersetzt. */
export function removeTab(s: TabsState, id: string, untitled: UntitledTitle): TabsState {
  const idx = s.tabs.findIndex((t) => t.id === id);
  if (idx < 0) return s;
  const rest = s.tabs.filter((t) => t.id !== id);
  if (rest.length === 0) return initialTabs(untitled);
  let activeId = s.activeId;
  if (activeId === id) activeId = (rest[idx] ?? rest[idx - 1] ?? rest[0]!).id;
  return { tabs: renumber(rest), activeId };
}

export function cycle(s: TabsState, step: 1 | -1): TabsState {
  if (s.tabs.length < 2) return s;
  const idx = Math.max(0, s.tabs.findIndex((t) => t.id === s.activeId));
  const next = s.tabs[(idx + step + s.tabs.length) % s.tabs.length]!;
  return { ...s, activeId: next.id };
}

function patchTab(s: TabsState, id: string, patch: (t: EditorTab) => EditorTab): TabsState {
  let changed = false;
  const tabs = s.tabs.map((t) => {
    if (t.id !== id) return t;
    const next = patch(t);
    if (next !== t) changed = true;
    return next;
  });
  return changed ? { ...s, tabs } : s;
}

export interface EditorTabsApi {
  state: TabsState;
  /** Immer der neueste Zustand (auch zwischen zwei Renderläufen). */
  get(): TabsState;
  tab(id: string): EditorTab | undefined;
  active(): EditorTab;
  newTab(doc?: LabelDocumentJson, meta?: TabMeta): string | null;
  closeTab(id: string): void;
  activate(id: string): void;
  next(): void;
  prev(): void;
  updateUndo(id: string, undo: UndoState): void;
  /** Gespeichert unter `name`; `entryId` ist der gespeicherte Undo-Schritt (Standard: der aktuelle). */
  markSaved(id: string, name: string, entryId?: number): void;
  rename(id: string, title: string): void;
  /** Nutzt einen leeren, unveränderten aktiven Tab, sonst einen neuen; `null` bei zu vielen Tabs. */
  replaceActiveIfEmpty(doc: LabelDocumentJson, meta: TabMeta): string | null;
  /** Wie `replaceActiveIfEmpty`, aktiviert aber einen Tab, in dem `meta.docName` schon offen ist. */
  openDocument(doc: LabelDocumentJson, meta: TabMeta): string | null;
  findByDocName(name: string): EditorTab | undefined;
  /** Übernimmt Entwürfe als Tabs (leere, unveränderte Tabs fallen weg); gibt die übernommenen IDs zurück. */
  restore(seeds: TabSeed[], opts?: { activate?: boolean }): string[];
}

export function useEditorTabs(opts: { untitled: UntitledTitle; onLimit?: () => void }): EditorTabsApi {
  const untitledRef = useRef(opts.untitled);
  untitledRef.current = opts.untitled;
  const onLimitRef = useRef(opts.onLimit);
  onLimitRef.current = opts.onLimit;
  const untitled = useCallback<UntitledTitle>((n) => untitledRef.current(n), []);

  const [state, setState] = useState<TabsState>(() => initialTabs(opts.untitled));
  const ref = useRef(state);

  const commit = useCallback((next: TabsState) => {
    if (next === ref.current) return;
    ref.current = next;
    setState(next);
  }, []);

  const get = useCallback(() => ref.current, []);
  const tab = useCallback((id: string) => ref.current.tabs.find((t) => t.id === id), []);
  const active = useCallback(() => ref.current.tabs.find((t) => t.id === ref.current.activeId) ?? ref.current.tabs[0]!, []);

  const newTab = useCallback(
    (doc: LabelDocumentJson = EMPTY_DOCUMENT, meta: TabMeta = {}) => {
      const res = addTab(ref.current, doc, meta, untitled);
      if (!res) {
        onLimitRef.current?.();
        return null;
      }
      commit(res.state);
      return res.id;
    },
    [commit, untitled],
  );

  const closeTab = useCallback((id: string) => commit(removeTab(ref.current, id, untitled)), [commit, untitled]);

  const activate = useCallback(
    (id: string) => {
      if (ref.current.activeId !== id && ref.current.tabs.some((t) => t.id === id)) commit({ ...ref.current, activeId: id });
    },
    [commit],
  );

  const next = useCallback(() => commit(cycle(ref.current, 1)), [commit]);
  const prev = useCallback(() => commit(cycle(ref.current, -1)), [commit]);

  const updateUndo = useCallback(
    (id: string, undo: UndoState) => commit(patchTab(ref.current, id, (t) => (t.undo === undo ? t : { ...t, undo }))),
    [commit],
  );

  const markSaved = useCallback(
    (id: string, name: string, entryId?: number) =>
      commit(
        patchTab(ref.current, id, (t) => {
          const entry = entryId === undefined ? t.undo.entries[t.undo.index] : t.undo.entries.find((e) => e.id === entryId);
          const undo = entryId === undefined ? markUndoSaved(t.undo) : { ...t.undo, savedId: entryId };
          return {
            ...t,
            undo,
            docName: name,
            title: name,
            untitledNo: null,
            restoredDirty: false,
            savedJson: JSON.stringify(entry?.doc ?? current(t.undo)),
          };
        }),
      ),
    [commit],
  );

  const rename = useCallback((id: string, title: string) => commit(patchTab(ref.current, id, (t) => ({ ...t, title }))), [commit]);

  const replaceActiveIfEmpty = useCallback(
    (doc: LabelDocumentJson, meta: TabMeta) => {
      const s = ref.current;
      const act = s.tabs.find((t) => t.id === s.activeId);
      if (act && isTabBlank(act)) {
        const others = s.tabs.filter((t) => t.id !== act.id);
        const fresh = makeTab(others, doc, meta, untitled, act.id);
        commit({
          ...s,
          tabs: s.tabs.map((t) => (t.id === act.id ? { ...fresh, order: t.order, undo: reset(t.undo, doc, meta.label) } : t)),
        });
        return act.id;
      }
      return newTab(doc, meta);
    },
    [commit, newTab, untitled],
  );

  const findByDocName = useCallback((name: string) => ref.current.tabs.find((t) => t.docName === name), []);

  const openDocument = useCallback(
    (doc: LabelDocumentJson, meta: TabMeta) => {
      if (meta.docName) {
        const existing = findByDocName(meta.docName);
        if (existing) {
          activate(existing.id);
          return existing.id;
        }
      }
      return replaceActiveIfEmpty(doc, meta);
    },
    [activate, findByDocName, replaceActiveIfEmpty],
  );

  const restore = useCallback(
    (seeds: TabSeed[], o?: { activate?: boolean }) => {
      const s = ref.current;
      const known = new Set(s.tabs.map((t) => t.id));
      let tabs = s.tabs.filter((t) => !isTabBlank(t));
      const ids: string[] = [];
      for (const seed of seeds) {
        if (known.has(seed.id) || tabs.length >= MAX_TABS) continue;
        const base = makeTab(tabs, seed.document, { title: seed.title, docName: seed.docName, label: seed.label }, untitled, seed.id);
        tabs = [...tabs, { ...base, restoredDirty: seed.dirty, fromDraft: !seed.unsynced }];
        ids.push(seed.id);
      }
      if (ids.length < seeds.filter((x) => !known.has(x.id)).length) onLimitRef.current?.();
      if (!ids.length) return ids;
      const keepActive = tabs.some((t) => t.id === s.activeId) && !o?.activate;
      commit({ tabs: renumber(tabs), activeId: keepActive ? s.activeId : ids[0]! });
      return ids;
    },
    [commit, untitled],
  );

  return useMemo(
    () => ({
      state,
      get,
      tab,
      active,
      newTab,
      closeTab,
      activate,
      next,
      prev,
      updateUndo,
      markSaved,
      rename,
      replaceActiveIfEmpty,
      openDocument,
      findByDocName,
      restore,
    }),
    [state, get, tab, active, newTab, closeTab, activate, next, prev, updateUndo, markSaved, rename, replaceActiveIfEmpty, openDocument, findByDocName, restore],
  );
}
