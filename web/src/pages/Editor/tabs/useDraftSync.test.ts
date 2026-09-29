import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { setTokenForTests } from '../../../api/client';
import { windowSessionId } from '../../../api/session';
import { unsavedCount } from '../../../api/unsaved';
import type { LabelDocumentJson } from '../../../api/types';
import { MockResponse, mockApi, type MockApi } from '../../../test/utils';
import { markSaved, push } from '../undoStack';
import { resetDraftSyncForTests, settleDraftWrites, takeLeftoverDrafts, useDraftSync } from './useDraftSync';
import { initialTabs, type EditorTab } from './useEditorTabs';

const doc = (text: string): LabelDocumentJson => ({ version: 1, objects: [{ kind: 'text', id: 'text1', x: 0, y: 0, w: 10, h: 10, text }] });

function baseTab(): EditorTab {
  return initialTabs(() => 'Unbenannt').tabs[0]!;
}

function edit(tab: EditorTab, text: string): EditorTab {
  return { ...tab, undo: push(tab.undo, doc(text), 'Text geändert') };
}

function puts(api: MockApi) {
  return api.calls.filter((c) => c.method === 'PUT' && c.path.startsWith('/api/v1/drafts/'));
}

describe('useDraftSync', () => {
  let failures = 0;
  let api: MockApi;

  beforeEach(() => {
    vi.useFakeTimers();
    setTokenForTests('test-token');
    failures = 0;
    api = mockApi({
      'PUT /api/v1/drafts/:id': ({ params, body }) => {
        if (failures > 0) {
          failures -= 1;
          return new MockResponse(500, { error: { kind: 'OSError', code: 'internal', message: 'Platte voll', hint: '', exit_code: 1, details: null } });
        }
        const b = body as { title: string };
        return { id: params.id, title: b.title };
      },
      'DELETE /api/v1/drafts/:id': () => ({}),
    });
  });

  afterEach(() => {
    resetDraftSyncForTests();
    vi.useRealTimers();
  });

  it('Änderung: nach 1500 ms genau ein PUT mit Sitzung und dirty: true', async () => {
    const tab = baseTab();
    const { rerender } = renderHook(({ tabs }) => useDraftSync(tabs, { enabled: true }), { initialProps: { tabs: [tab] } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(puts(api)).toHaveLength(0);
    rerender({ tabs: [edit(tab, 'A')] });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1400);
    });
    expect(puts(api)).toHaveLength(0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(puts(api)).toHaveLength(1);
    const call = puts(api)[0]!;
    expect(call.path).toBe(`/api/v1/drafts/${tab.id}`);
    expect(call.body).toMatchObject({ session: windowSessionId(), dirty: true, title: 'Unbenannt', doc_name: null, order: 0 });
  });

  it('schnelle Folge von Änderungen ergibt ein PUT', async () => {
    const tab = baseTab();
    const { rerender } = renderHook(({ tabs }) => useDraftSync(tabs, { enabled: true }), { initialProps: { tabs: [tab] } });
    let t = tab;
    for (const text of ['A', 'AB', 'ABC', 'ABCD']) {
      t = edit(t, text);
      rerender({ tabs: [t] });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(500);
      });
    }
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(puts(api)).toHaveLength(1);
    expect((puts(api)[0]!.body as { document: LabelDocumentJson }).document.objects[0]).toMatchObject({ text: 'ABCD' });
  });

  it('Speichern als Dokument sendet sofort dirty: false', async () => {
    const tab = edit(baseTab(), 'A');
    const { rerender } = renderHook(({ tabs }) => useDraftSync(tabs, { enabled: true }), { initialProps: { tabs: [tab] } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });
    expect(puts(api)).toHaveLength(1);
    rerender({ tabs: [{ ...tab, docName: 'Mein', title: 'Mein', undo: markSaved(tab.undo) }] });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(puts(api)).toHaveLength(2);
    expect(puts(api)[1]!.body).toMatchObject({ dirty: false, doc_name: 'Mein', title: 'Mein' });
  });

  it('Tab schließen löscht den Entwurf, eine offene Sicherung entfällt', async () => {
    const tab = baseTab();
    const { result, rerender } = renderHook(({ tabs }) => useDraftSync(tabs, { enabled: true }), { initialProps: { tabs: [tab] } });
    rerender({ tabs: [edit(tab, 'A')] });
    await act(async () => {
      await result.current.discard(tab.id);
    });
    rerender({ tabs: [] });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(puts(api)).toHaveLength(0);
    expect(api.calls.filter((c) => c.method === 'DELETE').map((c) => c.path)).toEqual([`/api/v1/drafts/${tab.id}`]);
  });

  it('Fehler: Hinweis bleibt einmalig bestehen, beim nächsten Erfolg ist er weg', async () => {
    failures = 2;
    const tab = baseTab();
    const { result, rerender } = renderHook(({ tabs }) => useDraftSync(tabs, { enabled: true, retryMs: 5000 }), {
      initialProps: { tabs: [tab] },
    });
    const first = edit(tab, 'A');
    rerender({ tabs: [first] });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });
    expect(result.current.error).not.toBeNull();
    const err = result.current.error;
    rerender({ tabs: [edit(first, 'AB')] });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });
    expect(puts(api)).toHaveLength(2);
    expect(result.current.error).toBe(err);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(puts(api)).toHaveLength(3);
    expect(result.current.error).toBeNull();
  });

  it('Editor verlassen, Dienst nicht erreichbar: der letzte Stand bleibt als Übergabe erhalten', async () => {
    failures = 100;
    const tab = baseTab();
    const { rerender, unmount } = renderHook(({ tabs }) => useDraftSync(tabs, { enabled: true, retryMs: 5000 }), {
      initialProps: { tabs: [tab] },
    });
    rerender({ tabs: [edit(tab, 'Neu')] });
    // Innerhalb der Entprellzeit weg vom Editor: offene Sicherung geht noch raus, scheitert aber.
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(puts(api)).toHaveLength(1);
    // Nicht gesicherter Stand zählt als ungespeichert (Rückfrage beim Schließen des Fensters).
    expect(unsavedCount()).toBe(1);
    const left = takeLeftoverDrafts();
    expect(unsavedCount()).toBe(0);
    expect([...left.keys()]).toEqual([tab.id]);
    expect(left.get(tab.id)!.document.objects[0]).toMatchObject({ text: 'Neu' });
    // Übernommen: kein weiterer Hintergrundversuch.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    expect(puts(api)).toHaveLength(1);
  });

  it('Editor verlassen, Dienst kurz weg: Hintergrundversuch sichert den Stand nach', async () => {
    failures = 1;
    const tab = baseTab();
    const { rerender, unmount } = renderHook(({ tabs }) => useDraftSync(tabs, { enabled: true, retryMs: 5000 }), {
      initialProps: { tabs: [tab] },
    });
    rerender({ tabs: [edit(tab, 'Neu')] });
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5100);
    });
    expect(puts(api)).toHaveLength(2);
    expect((puts(api)[1]!.body as { document: LabelDocumentJson }).document.objects[0]).toMatchObject({ text: 'Neu' });
    expect(takeLeftoverDrafts().size).toBe(0);
  });

  it('Editor verlassen: scheitert eine ältere Sicherung, gelingt aber die neuere, bleibt keine veraltete Übergabe', async () => {
    let failFirst: () => void = () => undefined;
    let n = 0;
    api.restore();
    api = mockApi({
      'PUT /api/v1/drafts/:id': ({ params }) => {
        n += 1;
        if (n === 1) {
          return new Promise((resolve) => {
            failFirst = () =>
              resolve(new MockResponse(503, { error: { kind: 'Offline', code: 'internal', message: 'weg', hint: '', exit_code: 5, details: null } }));
          });
        }
        return { id: params.id };
      },
    });
    const tab = baseTab();
    const { rerender, unmount } = renderHook(({ tabs }) => useDraftSync(tabs, { enabled: true, retryMs: 60_000 }), {
      initialProps: { tabs: [tab] },
    });
    const first = edit(tab, 'Alt');
    rerender({ tabs: [first] });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(puts(api)).toHaveLength(1);
    rerender({ tabs: [edit(first, 'Neu')] });
    unmount();
    failFirst();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(puts(api)).toHaveLength(2);
    expect(takeLeftoverDrafts().size).toBe(0);
  });

  it('settleDraftWrites wartet auf eine noch laufende Sicherung', async () => {
    let release: () => void = () => undefined;
    api.restore();
    api = mockApi({
      'PUT /api/v1/drafts/:id': () => new Promise((resolve) => (release = () => resolve({ id: 'x' }))),
    });
    const tab = baseTab();
    const { rerender, unmount } = renderHook(({ tabs }) => useDraftSync(tabs, { enabled: true }), { initialProps: { tabs: [tab] } });
    rerender({ tabs: [edit(tab, 'Neu')] });
    unmount();
    let settled = false;
    void settleDraftWrites().then(() => {
      settled = true;
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(settled).toBe(false);
    release();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(settled).toBe(true);
  });
});
