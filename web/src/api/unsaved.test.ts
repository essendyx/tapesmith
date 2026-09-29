import { describe, expect, it } from 'vitest';
import { registerUnsaved, unsavedCount } from './unsaved';

function fireBeforeUnload(): Event {
  const event = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(event);
  return event;
}

describe('unsaved', () => {
  it('zwei Quellen summieren sich, Abmelden entfernt', () => {
    const offA = registerUnsaved('editor', () => 2);
    const offB = registerUnsaved('einstellungen', () => 1);
    expect(unsavedCount()).toBe(3);
    expect(window.p12UnsavedCount?.()).toBe(3);
    offA();
    expect(unsavedCount()).toBe(1);
    offB();
    expect(window.p12UnsavedCount?.()).toBe(0);
  });

  it('gleicher Name ersetzt die alte Quelle, altes Abmelden entfernt die neue nicht', () => {
    const offOld = registerUnsaved('editor', () => 5);
    registerUnsaved('editor', () => 1);
    offOld();
    expect(unsavedCount()).toBe(1);
  });

  it('defekte Quelle zählt als 0', () => {
    registerUnsaved('kaputt', () => {
      throw new Error('x');
    });
    registerUnsaved('ok', () => 1);
    expect(unsavedCount()).toBe(1);
  });

  it('beforeunload fragt nur bei ungespeicherten Änderungen nach', () => {
    expect(fireBeforeUnload().defaultPrevented).toBe(false);
    const off = registerUnsaved('editor', () => 1);
    expect(fireBeforeUnload().defaultPrevented).toBe(true);
    off();
    expect(fireBeforeUnload().defaultPrevented).toBe(false);
  });

  it('nach dem Zurücksetzen (afterEach) ist das Register leer', () => {
    expect(unsavedCount()).toBe(0);
    expect(typeof window.p12UnsavedCount).toBe('function');
  });
});
