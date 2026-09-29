/**
 * Autosave je Tab: nach jeder Änderung entprellt `PUT /drafts/<tab-id>`, nach dem
 * Speichern als Dokument sofort (`dirty: false`), beim Schließen `DELETE`. Aufrufe je Tab laufen
 * nacheinander, damit ein spätes PUT einen gelöschten Entwurf nie wieder anlegt. Was beim Verlassen des
 * Editors nicht mehr ankommt, bleibt als Übergabe für den nächsten Editor (`takeLeftoverDrafts`).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../../../api/client';
import { deleteDraft, putDraft } from '../../../api/drafts';
import type { DraftPutBody } from '../../../api/types';
import { registerUnsaved } from '../../../api/unsaved';
import { current } from '../undoStack';
import { isTabBlank, isTabDirty, type EditorTab } from './useEditorTabs';

export const AUTOSAVE_DELAY_MS = 1500;
export const AUTOSAVE_RETRY_MS = 10000;
/** Höchstens so lange wartet ein neu geöffneter Editor auf noch laufende Sicherungen. */
export const SETTLE_TIMEOUT_MS = 3000;

// ---------- Über Editor-Instanzen hinweg (Editor verlassen und wieder öffnen) ----------

/** Laufende Aufrufe je Tab, über alle Instanzen: ein PUT des alten Editors überholt nie ein späteres. */
const chains = new Map<string, Promise<void>>();
/** Sicherungen, die beim Verlassen des Editors nicht beim Dienst ankamen (Tab-ID → Körper). */
const leftovers = new Map<string, DraftPutBody>();
let leftoverTimer: ReturnType<typeof setTimeout> | null = null;
/** Zählt Test-Zurücksetzungen: Antworten aus einem früheren Test legen keine Übergaben mehr an. */
let generation = 0;

function chainFor(id: string, step: () => Promise<void>): Promise<void> {
  const next = (chains.get(id) ?? Promise.resolve()).then(step, step);
  chains.set(id, next);
  void next.then(() => {
    if (chains.get(id) === next) chains.delete(id);
  });
  return next;
}

/** Ohne Aussicht auf Erfolg (Anfrage selbst ungültig) nicht im Hintergrund wiederholen. */
function retryable(err: unknown): boolean {
  return !(err instanceof ApiError && err.status >= 400 && err.status < 500);
}

function scheduleLeftovers(retryMs: number): void {
  // Noch nicht beim Dienst: zählt als ungespeichert, damit das Schließen des Fensters nachfragt.
  registerUnsaved('editor-uebergabe', () => leftovers.size);
  if (leftoverTimer !== null) return;
  leftoverTimer = setTimeout(() => {
    leftoverTimer = null;
    for (const [id, body] of [...leftovers]) {
      void chainFor(id, async () => {
        if (leftovers.get(id) !== body) return;
        try {
          await putDraft(id, body);
          if (leftovers.get(id) === body) leftovers.delete(id);
        } catch (err) {
          if (leftovers.get(id) === body && retryable(err)) scheduleLeftovers(retryMs);
        }
      });
    }
  }, retryMs);
}

/** Wartet (höchstens `timeoutMs`) auf alle noch laufenden Sicherungen und Löschungen. */
export async function settleDraftWrites(timeoutMs: number = SETTLE_TIMEOUT_MS): Promise<void> {
  const pendingWrites = [...chains.values()];
  if (!pendingWrites.length) return;
  let timer: ReturnType<typeof setTimeout> | undefined;
  await Promise.race([
    Promise.all(pendingWrites),
    new Promise<void>((resolve) => {
      timer = setTimeout(resolve, timeoutMs);
    }),
  ]);
  if (timer !== undefined) clearTimeout(timer);
}

/**
 * Übernimmt die Sicherungen, die ein verlassener Editor nicht mehr zum Dienst gebracht hat (neuer als
 * der Entwurf auf dem Server). Der Hintergrundversuch endet damit; der neue Editor sichert selbst.
 */
export function takeLeftoverDrafts(): Map<string, DraftPutBody> {
  if (leftoverTimer !== null) clearTimeout(leftoverTimer);
  leftoverTimer = null;
  const out = new Map(leftovers);
  leftovers.clear();
  return out;
}

/** Gibt eine übernommene Sicherung zurück (Editor wurde vor dem Übernehmen wieder verlassen). */
export function putLeftoverBack(id: string, body: DraftPutBody, retryMs: number = AUTOSAVE_RETRY_MS): void {
  if (!leftovers.has(id)) leftovers.set(id, body);
  scheduleLeftovers(retryMs);
}

/** Nur für Tests: vergisst Übergaben, Hintergrundversuche und laufende Ketten. */
export function resetDraftSyncForTests(): void {
  generation += 1;
  takeLeftoverDrafts();
  chains.clear();
}

export function draftBody(tab: EditorTab, order: number): DraftPutBody {
  return { title: tab.title, doc_name: tab.docName, document: current(tab.undo), dirty: isTabDirty(tab), order };
}

export interface DraftSync {
  /** Letzter Fehler des Autosave (null nach dem nächsten Erfolg). */
  error: unknown;
  /** Verwirft den Entwurf eines geschlossenen Tabs (offene Sicherung fällt weg, dann DELETE). */
  discard(id: string): Promise<void>;
  /** Sendet alle offenen Sicherungen sofort. */
  flush(): void;
}

export function useDraftSync(tabs: EditorTab[], opts: { enabled: boolean; delayMs?: number; retryMs?: number }): DraftSync {
  const delayMs = opts.delayMs ?? AUTOSAVE_DELAY_MS;
  const retryMs = opts.retryMs ?? AUTOSAVE_RETRY_MS;
  const [error, setError] = useState<unknown>(null);
  const queued = useRef(new Map<string, { sig: string; dirty: boolean }>());
  const pending = useRef(new Map<string, DraftPutBody>());
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const discarded = useRef(new Set<string>());
  const alive = useRef(true);

  const clearTimer = useCallback((id: string) => {
    const t = timers.current.get(id);
    if (t !== undefined) clearTimeout(t);
    timers.current.delete(id);
  }, []);

  const chain = useCallback((id: string, step: () => Promise<void>): Promise<void> => chainFor(id, step), []);

  const send = useCallback(
    (id: string) => {
      clearTimer(id);
      const body = pending.current.get(id);
      if (!body) return;
      pending.current.delete(id);
      const gen = generation;
      void chain(id, async () => {
        if (discarded.current.has(id)) return;
        try {
          await putDraft(id, body);
          // Ein späterer Erfolg macht eine frühere, gescheiterte Übergabe desselben Tabs hinfällig.
          if (gen === generation) leftovers.delete(id);
          if (alive.current) setError(null);
        } catch (err) {
          if (discarded.current.has(id)) return;
          if (!alive.current) {
            if (gen !== generation) return;
            // Editor schon verlassen: Stand für den nächsten Editor aufheben und im Hintergrund nachsichern.
            leftovers.set(id, body);
            if (retryable(err)) scheduleLeftovers(retryMs);
            else registerUnsaved('editor-uebergabe', () => leftovers.size);
            return;
          }
          if (!pending.current.has(id)) pending.current.set(id, body);
          if (alive.current) {
            setError((prev: unknown) => prev ?? err);
            if (!timers.current.has(id)) timers.current.set(id, setTimeout(() => send(id), retryMs));
          }
        }
      });
    },
    [chain, clearTimer, retryMs],
  );

  useEffect(() => {
    if (!opts.enabled) return;
    tabs.forEach((tab, order) => {
      const body = draftBody(tab, order);
      const sig = JSON.stringify(body);
      const prev = queued.current.get(tab.id);
      if (!prev && (tab.fromDraft || isTabBlank(tab))) {
        // schon auf dem Server bzw. nichts zu sichern
        queued.current.set(tab.id, { sig, dirty: body.dirty });
        return;
      }
      if (prev?.sig === sig) return;
      queued.current.set(tab.id, { sig, dirty: body.dirty });
      discarded.current.delete(tab.id);
      pending.current.set(tab.id, body);
      if (prev?.dirty && !body.dirty) {
        send(tab.id);
        return;
      }
      clearTimer(tab.id);
      timers.current.set(
        tab.id,
        setTimeout(() => send(tab.id), delayMs),
      );
    });
  }, [tabs, opts.enabled, delayMs, send, clearTimer]);

  const flush = useCallback(() => {
    for (const id of [...pending.current.keys()]) send(id);
  }, [send]);

  // Beim Verlassen des Editors offene Sicherungen noch senden.
  useEffect(() => {
    alive.current = true;
    const pendingTimers = timers.current;
    return () => {
      alive.current = false;
      flush();
      for (const t of pendingTimers.values()) clearTimeout(t);
      pendingTimers.clear();
    };
  }, [flush]);

  const discard = useCallback(
    (id: string) => {
      clearTimer(id);
      pending.current.delete(id);
      queued.current.delete(id);
      discarded.current.add(id);
      return chain(id, async () => {
        try {
          await deleteDraft(id);
        } catch {
          // Entwurf bleibt liegen und wird später als verwaist angeboten
        }
      });
    },
    [chain, clearTimer],
  );

  return { error, discard, flush };
}
