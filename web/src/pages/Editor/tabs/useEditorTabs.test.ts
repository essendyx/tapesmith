import { describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import type { LabelDocumentJson } from '../../../api/types';
import { push } from '../undoStack';
import { MAX_TABS, isTabDirty, useEditorTabs } from './useEditorTabs';

const DOC_A: LabelDocumentJson = { version: 1, objects: [{ kind: 'text', id: 'text1', x: 0, y: 0, w: 10, h: 10, text: 'A' }] };
const DOC_B: LabelDocumentJson = { version: 1, objects: [{ kind: 'text', id: 'text1', x: 0, y: 0, w: 10, h: 10, text: 'B' }] };

function setup(onLimit?: () => void) {
  return renderHook(() => useEditorTabs({ untitled: (n) => (n === 1 ? 'Unbenannt' : `Unbenannt ${n}`), onLimit }));
}

describe('useEditorTabs', () => {
  it('startet mit einem leeren Tab „Unbenannt“, neuer Tab heißt „Unbenannt 2“ und wird aktiv', () => {
    const { result } = setup();
    expect(result.current.state.tabs).toHaveLength(1);
    expect(result.current.state.tabs[0]?.title).toBe('Unbenannt');
    let id: string | null = null;
    act(() => {
      id = result.current.newTab();
    });
    expect(result.current.state.tabs).toHaveLength(2);
    expect(result.current.state.activeId).toBe(id);
    expect(result.current.state.tabs[1]?.title).toBe('Unbenannt 2');
    expect(result.current.state.tabs.map((t) => t.order)).toEqual([0, 1]);
  });

  it('höchstens zwölf Tabs, danach null und Hinweis', () => {
    const onLimit = vi.fn();
    const { result } = setup(onLimit);
    act(() => {
      for (let i = 0; i < 20; i += 1) result.current.newTab();
    });
    expect(result.current.state.tabs).toHaveLength(MAX_TABS);
    expect(MAX_TABS).toBe(12);
    let extra: string | null = 'x';
    act(() => {
      extra = result.current.newTab();
    });
    expect(extra).toBeNull();
    expect(onLimit).toHaveBeenCalled();
  });

  it('Schließen aktiviert den rechten, am Ende den linken Nachbarn; der letzte Tab wird ersetzt', () => {
    const { result } = setup();
    const first = result.current.state.tabs[0]!.id;
    let second = '';
    let third = '';
    act(() => {
      second = result.current.newTab() ?? '';
      third = result.current.newTab() ?? '';
      result.current.activate(second);
    });
    act(() => result.current.closeTab(second));
    expect(result.current.state.activeId).toBe(third);
    act(() => result.current.closeTab(third));
    expect(result.current.state.activeId).toBe(first);
    act(() => result.current.closeTab(first));
    expect(result.current.state.tabs).toHaveLength(1);
    expect(result.current.state.tabs[0]?.id).not.toBe(first);
  });

  it('next und prev laufen zyklisch', () => {
    const { result } = setup();
    const ids = [result.current.state.tabs[0]!.id];
    act(() => {
      ids.push(result.current.newTab() ?? '');
      ids.push(result.current.newTab() ?? '');
    });
    expect(result.current.state.activeId).toBe(ids[2]);
    act(() => result.current.next());
    expect(result.current.state.activeId).toBe(ids[0]);
    act(() => result.current.prev());
    expect(result.current.state.activeId).toBe(ids[2]);
    act(() => result.current.prev());
    expect(result.current.state.activeId).toBe(ids[1]);
  });

  it('replaceActiveIfEmpty nutzt den leeren Tab, sonst einen neuen', () => {
    const { result } = setup();
    const blank = result.current.state.tabs[0]!.id;
    let id: string | null = null;
    act(() => {
      id = result.current.replaceActiveIfEmpty(DOC_A, { docName: 'A' });
    });
    expect(id).toBe(blank);
    expect(result.current.state.tabs).toHaveLength(1);
    expect(result.current.state.tabs[0]).toMatchObject({ title: 'A', docName: 'A' });
    act(() => {
      id = result.current.replaceActiveIfEmpty(DOC_B, { docName: 'B' });
    });
    expect(result.current.state.tabs).toHaveLength(2);
    expect(result.current.state.activeId).toBe(id);
  });

  it('gleiches Dokument aktiviert den vorhandenen Tab', () => {
    const { result } = setup();
    let a: string | null = null;
    act(() => {
      a = result.current.openDocument(DOC_A, { docName: 'A' });
      result.current.openDocument(DOC_B, { docName: 'B' });
    });
    expect(result.current.state.tabs).toHaveLength(2);
    let again: string | null = null;
    act(() => {
      again = result.current.openDocument(DOC_A, { docName: 'A' });
    });
    expect(again).toBe(a);
    expect(result.current.state.activeId).toBe(a);
    expect(result.current.state.tabs).toHaveLength(2);
  });

  it('dirty: unbenannt mit Objekten, Änderung am Undo-Stapel, Speichern macht sauber', () => {
    const { result } = setup();
    const id = result.current.state.tabs[0]!.id;
    expect(isTabDirty(result.current.state.tabs[0]!)).toBe(false);
    act(() => result.current.updateUndo(id, push(result.current.tab(id)!.undo, DOC_A, 'Text hinzugefügt')));
    expect(isTabDirty(result.current.tab(id)!)).toBe(true);
    act(() => result.current.markSaved(id, 'Mein'));
    expect(isTabDirty(result.current.tab(id)!)).toBe(false);
    expect(result.current.tab(id)).toMatchObject({ title: 'Mein', docName: 'Mein' });
    act(() => {
      result.current.newTab(DOC_B, {});
    });
    expect(isTabDirty(result.current.active())).toBe(true);
  });

  it('restore übernimmt Entwürfe, ersetzt den leeren Tab und behält „ungespeichert“', () => {
    const { result } = setup();
    act(() => {
      result.current.restore([
        { id: 'draft-0001', title: 'Server', docName: 'Server', document: DOC_A, dirty: true },
        { id: 'draft-0002', title: 'Unbenannt 2', docName: null, document: DOC_B, dirty: false },
      ]);
    });
    expect(result.current.state.tabs.map((t) => t.id)).toEqual(['draft-0001', 'draft-0002']);
    expect(isTabDirty(result.current.tab('draft-0001')!)).toBe(true);
    expect(result.current.state.activeId).toBe('draft-0001');
  });
});
