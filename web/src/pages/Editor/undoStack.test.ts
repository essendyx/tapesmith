import { describe, expect, it } from 'vitest';
import type { LabelDocumentJson } from '../../api/types';
import { canRedo, canUndo, createUndo, current, isDirty, jump, labels, markSaved, push, redo, reset, undo } from './undoStack';

function doc(n: number): LabelDocumentJson {
  return { version: 1, objects: Array.from({ length: n }, (_, i) => ({ kind: 'text', id: `text${i + 1}`, x: 0, y: 0, w: 10, h: 10, text: `T${i}` })) };
}

describe('undoStack', () => {
  it('push, undo, redo und Beschriftungen', () => {
    let s = createUndo(doc(0), 'Neues Label', 0);
    expect(canUndo(s)).toBe(false);
    s = push(s, doc(1), 'Text hinzugefügt', { now: 10 });
    s = push(s, doc(2), 'Text hinzugefügt', { now: 20 });
    expect(labels(s)).toEqual(['Neues Label', 'Text hinzugefügt', 'Text hinzugefügt']);
    expect(s.index).toBe(2);
    s = undo(s);
    expect(current(s).objects).toHaveLength(1);
    expect(canRedo(s)).toBe(true);
    s = redo(s);
    expect(current(s).objects).toHaveLength(2);
    expect(canRedo(s)).toBe(false);
    expect(redo(s)).toBe(s);
  });

  it('gleiches Dokument ergibt keinen Schritt', () => {
    let s = createUndo(doc(1), 'Start', 0);
    s = push(s, doc(1), 'nichts', { now: 5 });
    expect(labels(s)).toEqual(['Start']);
  });

  it('Redo-Zweig verfällt nach neuem push', () => {
    let s = createUndo(doc(0), 'Start', 0);
    s = push(s, doc(1), 'a', { now: 1 });
    s = push(s, doc(2), 'b', { now: 2 });
    s = undo(undo(s));
    s = push(s, doc(3), 'c', { now: 3 });
    expect(labels(s)).toEqual(['Start', 'c']);
    expect(canRedo(s)).toBe(false);
  });

  it('jump springt zu jedem Schritt, außerhalb bleibt alles', () => {
    let s = createUndo(doc(0), 'Start', 0);
    s = push(s, doc(1), 'a', { now: 1 });
    s = push(s, doc(2), 'b', { now: 2 });
    s = jump(s, 0);
    expect(current(s).objects).toHaveLength(0);
    expect(labels(s)).toHaveLength(3);
    expect(jump(s, 9)).toBe(s);
  });

  it('gleicher merge key innerhalb 1 s wird zusammengefasst, danach nicht mehr (Fake-Uhr)', () => {
    let s = createUndo(doc(0), 'Start', 0);
    const a = { ...doc(1) };
    s = push(s, a, 'Text geändert', { mergeKey: 'update:text1:text', now: 1000 });
    s = push(s, { ...doc(1), objects: [{ ...doc(1).objects[0]!, text: 'x' }] }, 'Text geändert', { mergeKey: 'update:text1:text', now: 1800 });
    expect(labels(s)).toEqual(['Start', 'Text geändert']);
    expect(current(s).objects[0]?.text).toBe('x');
    // gleitendes Fenster: 1800 + 1000 >= 2700
    s = push(s, { ...doc(1), objects: [{ ...doc(1).objects[0]!, text: 'y' }] }, 'Text geändert', { mergeKey: 'update:text1:text', now: 2700 });
    expect(labels(s)).toHaveLength(2);
    s = push(s, { ...doc(1), objects: [{ ...doc(1).objects[0]!, text: 'z' }] }, 'Text geändert', { mergeKey: 'update:text1:text', now: 3800 });
    expect(labels(s)).toHaveLength(3);
  });

  it('anderer merge key oder eigenes Fenster (500 ms) trennt', () => {
    let s = createUndo(doc(0), 'Start', 0);
    s = push(s, doc(1), 'a', { mergeKey: 'k1', now: 0 });
    s = push(s, doc(2), 'b', { mergeKey: 'k2', now: 100 });
    expect(labels(s)).toHaveLength(3);
    s = push(s, doc(3), 'c', { mergeKey: 'k2', now: 700, windowMs: 500 });
    expect(labels(s)).toHaveLength(4);
    s = push(s, doc(4), 'd', { mergeKey: 'k2', now: 1100, windowMs: 500 });
    expect(labels(s)).toHaveLength(4);
  });

  it('nach undo wird nicht mehr zusammengefasst', () => {
    let s = createUndo(doc(0), 'Start', 0);
    s = push(s, doc(1), 'a', { mergeKey: 'k', now: 0 });
    s = push(s, doc(2), 'a', { mergeKey: 'k', now: 10 });
    s = undo(s);
    s = push(s, doc(3), 'a', { mergeKey: 'k', now: 20 });
    expect(labels(s)).toEqual(['Start', 'a']);
    expect(current(s).objects).toHaveLength(3);
  });

  it('dirty nach Änderung, sauber nach markSaved, wieder dirty nach Zusammenfassung', () => {
    let s = createUndo(doc(0), 'Start', 0);
    expect(isDirty(s)).toBe(false);
    s = push(s, doc(1), 'a', { mergeKey: 'k', now: 0 });
    expect(isDirty(s)).toBe(true);
    s = markSaved(s);
    expect(isDirty(s)).toBe(false);
    s = push(s, doc(2), 'a', { mergeKey: 'k', now: 10 });
    expect(isDirty(s)).toBe(true);
    s = markSaved(s);
    s = undo(s);
    expect(isDirty(s)).toBe(true);
    s = redo(s);
    expect(isDirty(s)).toBe(false);
    s = reset(s, doc(5), 'Geöffnet');
    expect(isDirty(s)).toBe(false);
    expect(labels(s)).toEqual(['Geöffnet']);
  });
});
