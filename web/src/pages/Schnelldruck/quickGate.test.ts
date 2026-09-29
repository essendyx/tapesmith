import { describe, expect, it } from 'vitest';
import { MAX_LINES, QuickGate, REASONS, normalizePaste } from './quickGate';

describe('QuickGate', () => {
  it('druckt nur mit aktueller, fehlerfreier Vorschau', () => {
    const g = new QuickGate();
    g.edited();

    let decision = g.key('enter', { text: 'A' });
    expect(decision).toEqual({ action: 'ignore', reason: REASONS.stale });

    g.previewReady(g.revision, true);
    decision = g.key('enter', { text: 'A' });
    expect(decision.action).toBe('print');
  });

  it('veraltete Vorschau-Revision bleibt stale', () => {
    const g = new QuickGate();
    const r = g.edited();
    g.edited();
    g.previewReady(r, true);

    const decision = g.key('enter', { text: 'A' });
    expect(decision).toEqual({ action: 'ignore', reason: REASONS.stale });
  });

  it('fehlerhafte Vorschau (ok=false)', () => {
    const g = new QuickGate();
    const rev = g.edited();
    g.previewReady(rev, false);

    const decision = g.key('enter', { text: 'A' });
    expect(decision).toEqual({ action: 'ignore', reason: REASONS.invalid });
  });

  it('leerer Text', () => {
    const g = new QuickGate();
    const rev = g.edited();
    g.previewReady(rev, true);

    const decision = g.key('enter', { text: '   ' });
    expect(decision).toEqual({ action: 'ignore', reason: REASONS.empty });
  });

  it('busy blockt, danach wieder frei', () => {
    const g = new QuickGate();
    const rev = g.edited();
    g.previewReady(rev, true);
    g.setBusy(true);

    let decision = g.key('enter', { text: 'A' });
    expect(decision).toEqual({ action: 'ignore', reason: REASONS.busy });

    g.setBusy(false);
    decision = g.key('enter', { text: 'A' });
    expect(decision.action).toBe('print');
  });

  it('Entprellung mit injizierbarer Uhr', () => {
    let now = 100;
    const g = new QuickGate({ clock: () => now });
    const rev = g.edited();
    g.previewReady(rev, true);

    let decision = g.key('enter', { text: 'A' });
    expect(decision.action).toBe('print');
    g.markPrinted();

    now = 100.5;
    decision = g.key('enter', { text: 'A' });
    expect(decision).toEqual({ action: 'ignore', reason: REASONS.debounce });

    now = 101.1;
    decision = g.key('enter', { text: 'A' });
    expect(decision.action).toBe('print');
  });

  it('gehaltene Taste (repeat) wird immer ignoriert', () => {
    const g = new QuickGate();
    const rev = g.edited();
    g.previewReady(rev, true);

    let decision = g.key('enter', { text: 'A', autoRepeat: true });
    expect(decision).toEqual({ action: 'ignore', reason: REASONS.repeat });

    decision = g.key('shift_enter', { text: 'A', autoRepeat: true });
    expect(decision).toEqual({ action: 'ignore', reason: REASONS.repeat });
  });

  it('Umschalt+Enter fügt Zeile ein oder lehnt ab (max 3 Zeilen)', () => {
    const g = new QuickGate();

    let decision = g.key('shift_enter', { text: 'A' });
    expect(decision.action).toBe('newline');

    decision = g.key('shift_enter', { text: 'A\nB\nC' });
    expect(decision).toEqual({ action: 'ignore', reason: REASONS.lines });
  });

  it('ctrlEnterOnly: Enter fügt Zeile ein, Strg+Enter druckt', () => {
    const g = new QuickGate({ ctrlEnterOnly: true });
    const rev = g.edited();
    g.previewReady(rev, true);

    let decision = g.key('enter', { text: 'A' });
    expect(decision.action).toBe('newline');

    decision = g.key('ctrl_enter', { text: 'A' });
    expect(decision.action).toBe('print');
  });

  it('Einfügen einzeilig mit abschließendem Umbruch druckt sofort', () => {
    const g = new QuickGate();

    const result = g.pasted('pmx10 SSD-1\r\n');
    expect(result.lines).toEqual(['pmx10 SSD-1']);
    expect(result.multiline).toBe(false);
    expect(result.error).toBeNull();

    g.previewReady(g.revision, true);
    const decision = g.key('enter', { text: 'pmx10 SSD-1' });
    expect(decision.action).toBe('print');
  });

  it('Einfügen mehrzeilig verlangt zusätzliches Enter (druckt nie selbst)', () => {
    const g = new QuickGate();

    const result = g.pasted('a\nb\n');
    expect(result.multiline).toBe(true);
    expect(result.lines).toEqual(['a', 'b']);

    g.previewReady(g.revision, true);

    let decision = g.key('enter', { text: 'a\nb' });
    expect(decision).toEqual({ action: 'ignore', reason: REASONS.review });

    decision = g.key('enter', { text: 'a\nb' });
    expect(decision.action).toBe('print');
  });

  it('Einfügen macht die Vorschau veraltet', () => {
    const g = new QuickGate();
    const rev = g.edited();
    g.previewReady(rev, true);
    expect(g.previewCurrent).toBe(true);

    g.pasted('a\nb\n');
    expect(g.previewCurrent).toBe(false);
  });

  it('mehr als 3 Zeilen beim Einfügen ergeben einen Fehler ohne Revisionswechsel', () => {
    const g = new QuickGate();
    const before = g.revision;

    let result = g.pasted('1\n2\n3\n4');
    expect(result.error).toBe(REASONS.lines);
    expect(g.revision).toBe(before);

    result = g.pasted('a\nb\nc', 2);
    expect(result.error).toBe(REASONS.lines);
  });

  it('canPrint stimmt mit der Enter-Entscheidung überein', () => {
    const g = new QuickGate();
    const rev = g.edited();

    let decision = g.canPrint('A');
    expect(decision).toEqual({ action: 'ignore', reason: REASONS.stale });

    decision = g.canPrint('   ');
    expect(decision).toEqual({ action: 'ignore', reason: REASONS.empty });

    g.previewReady(rev, true);
    decision = g.canPrint('   ');
    expect(decision).toEqual({ action: 'ignore', reason: REASONS.empty });

    decision = g.canPrint('A');
    expect(decision.action).toBe('print');
  });
});

describe('normalizePaste', () => {
  it('vereinheitlicht Zeilenumbrüche (CRLF, CR, U+2028/U+2029) und Tabs, entfernt Steuerzeichen', () => {
    const result = normalizePaste('a b\tc\x07');
    expect(result.lines).toEqual(['a', 'b c']);
  });

  it('CRLF und CR werden zu einem Umbruch', () => {
    const result = normalizePaste('a\r\nb\rc');
    expect(result.lines).toEqual(['a', 'b', 'c']);
  });

  it('führende/abschließende Leerzeilen fallen weg', () => {
    const result = normalizePaste('\n\nHallo\n\n');
    expect(result.lines).toEqual(['Hallo']);
    expect(result.multiline).toBe(false);
  });

  it(`mehr als ${MAX_LINES} Zeilen ergeben einen Fehler`, () => {
    const result = normalizePaste('1\n2\n3\n4');
    expect(result.error).toBe(REASONS.lines);
  });

  it('berücksichtigt bereits vorhandene Zeilen im Feld', () => {
    const result = normalizePaste('a\nb\nc', 2);
    expect(result.error).toBe(REASONS.lines);
  });
});
