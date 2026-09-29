import { describe, expect, it } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { formatCombo, listRegisteredShortcuts, matchesCombo, parseCombo, useShortcut } from './shortcuts';

function key(init: KeyboardEventInit): KeyboardEvent {
  return new KeyboardEvent('keydown', init);
}

describe('formatCombo', () => {
  it('Deutsch und Englisch', () => {
    expect(formatCombo('Ctrl+Shift+V', 'en')).toBe('Ctrl+Shift+V');
    expect(formatCombo('Ctrl+Shift+V', 'de')).toBe('Strg+Umschalt+V');
    expect(formatCombo('Ctrl+PageDown', 'de')).toBe('Strg+Bild ab');
    expect(formatCombo('Ctrl+PageUp', 'en')).toBe('Ctrl+PgUp');
    expect(formatCombo('Space', 'de')).toBe('Leertaste');
    expect(formatCombo('Space', 'en')).toBe('Space');
    expect(formatCombo('Escape', 'en')).toBe('Esc');
    expect(formatCombo('Enter', 'de')).toBe('Eingabe');
    expect(formatCombo('Enter', 'en')).toBe('Enter');
    expect(formatCombo('F1', 'de')).toBe('F1');
    expect(formatCombo('Ctrl+,', 'de')).toBe('Strg+,');
    expect(formatCombo('Delete', 'de')).toBe('Entf');
  });

  it('ohne Sprache folgt der aktuellen Sprache (Test: Deutsch)', () => {
    expect(formatCombo('Ctrl+K')).toBe('Strg+K');
  });
});

describe('matchesCombo', () => {
  it('? passt unabhängig von Umschalt (deutsche Tastatur: Umschalt+ß)', () => {
    const combo = parseCombo('?');
    expect(matchesCombo(key({ key: '?', shiftKey: true }), combo)).toBe(true);
    expect(matchesCombo(key({ key: '?' }), combo)).toBe(true);
    expect(matchesCombo(key({ key: '?', ctrlKey: true }), combo)).toBe(false);
    expect(matchesCombo(key({ key: 'ß', shiftKey: false }), combo)).toBe(false);
  });

  it('F1 und PageDown als Tastennamen', () => {
    expect(matchesCombo(key({ key: 'F1' }), parseCombo('F1'))).toBe(true);
    expect(matchesCombo(key({ key: 'PageDown', ctrlKey: true }), parseCombo('Ctrl+PageDown'))).toBe(true);
    expect(matchesCombo(key({ key: 'PageUp', ctrlKey: true }), parseCombo('Ctrl+PageDown'))).toBe(false);
  });

  it('QWERTZ: Strg+Y (Taste an der Z-Position) ist Wiederholen, nicht Rückgängig', () => {
    // Deutsche Tastatur: Y liegt auf code KeyZ, Z auf code KeyY.
    const strgY = key({ key: 'y', code: 'KeyZ', ctrlKey: true });
    const strgZ = key({ key: 'z', code: 'KeyY', ctrlKey: true });
    expect(matchesCombo(strgY, parseCombo('Ctrl+Z'))).toBe(false);
    expect(matchesCombo(strgY, parseCombo('Ctrl+Y'))).toBe(true);
    expect(matchesCombo(strgZ, parseCombo('Ctrl+Y'))).toBe(false);
    expect(matchesCombo(strgZ, parseCombo('Ctrl+Z'))).toBe(true);
  });

  it('nicht lateinische Belegung: Buchstabe über die Tastenposition', () => {
    expect(matchesCombo(key({ key: 'я', code: 'KeyZ', ctrlKey: true }), parseCombo('Ctrl+Z'))).toBe(true);
  });

  it('AZERTY: Strg+1 über die Tastenposition, auch wenn die Taste & liefert', () => {
    expect(matchesCombo(key({ key: '&', code: 'Digit1', ctrlKey: true }), parseCombo('Ctrl+1'))).toBe(true);
    expect(matchesCombo(key({ key: '1', code: 'Digit2', ctrlKey: true }), parseCombo('Ctrl+2'))).toBe(false);
  });
});

describe('useShortcut mit Beschreibung', () => {
  it('meldet das Kürzel an, solange es aktiv ist, und ab beim Aushängen', () => {
    const { rerender, unmount } = renderHook(
      ({ enabled }: { enabled: boolean }) => useShortcut('Alt+N', () => undefined, { description: 'Neu', group: 'Test', enabled }),
      { initialProps: { enabled: true } },
    );
    expect(listRegisteredShortcuts().map((s) => [s.combo, s.description, s.group])).toContainEqual(['Alt+N', 'Neu', 'Test']);
    act(() => rerender({ enabled: false }));
    expect(listRegisteredShortcuts().some((s) => s.description === 'Neu')).toBe(false);
    act(() => rerender({ enabled: true }));
    expect(listRegisteredShortcuts().some((s) => s.description === 'Neu')).toBe(true);
    unmount();
    expect(listRegisteredShortcuts().some((s) => s.description === 'Neu')).toBe(false);
  });

  it('ohne Beschreibung keine Anmeldung', () => {
    const before = listRegisteredShortcuts().length;
    const { unmount } = renderHook(() => useShortcut('Alt+M', () => undefined));
    expect(listRegisteredShortcuts()).toHaveLength(before);
    unmount();
  });
});
