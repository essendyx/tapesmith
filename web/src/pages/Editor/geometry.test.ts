import { describe, expect, it } from 'vitest';
import type { LabelDocumentJson } from '../../api/types';
import {
  arrowDelta,
  cssPxPerDot,
  handleAt,
  handlePositions,
  hitTest,
  normRect,
  objectBoxes,
  resizeBox,
  rubberBand,
  selectionBox,
  toDots,
  toScreen,
  zoomScale,
} from './geometry';

const DOC: LabelDocumentJson = {
  version: 1,
  objects: [
    { kind: 'rect', id: 'rect1', x: 0, y: 0, w: 100, h: 60 },
    { kind: 'text', id: 'text1', x: 10, y: 10, w: 40, h: 20 },
    { kind: 'text', id: 'text2', x: 20, y: 15, w: 40, h: 20, visible: false },
    { kind: 'qr', id: 'qr1', x: 150, y: 5, w: 50, h: 50 },
  ],
};

describe('geometry', () => {
  it('Zoom 100 % mit screen_px_per_mm 4 und dots_per_mm 8 ergibt 0,5 px je Punkt', () => {
    expect(cssPxPerDot(4, 8)).toBe(0.5);
    expect(cssPxPerDot(null, 8)).toBeCloseTo(96 / 25.4 / 8);
    expect(zoomScale(1, 0.5, 400, 1000)).toBe(0.5);
    expect(zoomScale(4, 0.5, 400, 1000)).toBe(2);
  });

  it('Anpassen füllt die verfügbare Breite, ohne Breite gilt 100 %', () => {
    expect(zoomScale('fit', 0.5, 400, 1000)).toBe(2.5);
    expect(zoomScale('fit', 0.5, 400, 0)).toBe(0.5);
  });

  it('Maus und Punkte hin und zurück', () => {
    const scale = 0.5;
    expect(toDots(50, 20, scale)).toEqual([100, 40]);
    expect(toScreen(100, 40, scale)).toEqual([50, 20]);
    const [x, y] = toDots(...toScreen(37, 11, 2.5), 2.5);
    expect(x).toBeCloseTo(37);
    expect(y).toBeCloseTo(11);
  });

  it('Anfasser-Positionen einer Box', () => {
    const h = handlePositions([10, 20, 40, 30]);
    expect(h.nw).toEqual([10, 20]);
    expect(h.n).toEqual([30, 20]);
    expect(h.ne).toEqual([50, 20]);
    expect(h.e).toEqual([50, 35]);
    expect(h.se).toEqual([50, 50]);
    expect(h.s).toEqual([30, 50]);
    expect(h.sw).toEqual([10, 50]);
    expect(h.w).toEqual([10, 35]);
    expect(handleAt([49, 51], [10, 20, 40, 30], 3)).toBe('se');
    expect(handleAt([30, 35], [10, 20, 40, 30], 3)).toBeNull();
  });

  it('Treffer wählt das oberste sichtbare Objekt, Boxen aus dem Overlay haben Vorrang', () => {
    const boxes = objectBoxes(DOC, null);
    expect(hitTest(DOC, boxes, 25, 18)).toBe('text1');
    expect(hitTest(DOC, boxes, 55, 40)).toBe('rect1');
    expect(hitTest(DOC, boxes, 120, 40)).toBeNull();
    const overlay = objectBoxes(DOC, { qr1: [110, 0, 20, 20] });
    expect(hitTest(DOC, overlay, 115, 5)).toBe('qr1');
  });

  it('Gummiband liefert berührte sichtbare Objekte im Rechteck', () => {
    const boxes = objectBoxes(DOC, null);
    expect(rubberBand(DOC, boxes, normRect(140, 0, 210, 70))).toEqual(['qr1']);
    expect(rubberBand(DOC, boxes, normRect(45, 25, 5, 5))).toEqual(['rect1', 'text1']);
    expect(normRect(10, 20, 4, 5)).toEqual([4, 5, 6, 15]);
  });

  it('Pfeiltasten: 1 Punkt, mit Umschalt 8 Punkte', () => {
    expect(arrowDelta('ArrowLeft', false)).toEqual([-1, 0]);
    expect(arrowDelta('ArrowRight', true)).toEqual([8, 0]);
    expect(arrowDelta('ArrowUp', true)).toEqual([0, -8]);
    expect(arrowDelta('ArrowDown', false)).toEqual([0, 1]);
    expect(arrowDelta('a', false)).toBeNull();
  });

  it('Größe ändern je Anfasser, mindestens 1 Punkt', () => {
    expect(resizeBox([10, 10, 40, 20], 'se', 5, 6)).toEqual([10, 10, 45, 26]);
    expect(resizeBox([10, 10, 40, 20], 'nw', 5, 6)).toEqual([15, 16, 35, 14]);
    expect(resizeBox([10, 10, 40, 20], 'n', 5, 50)).toEqual([10, 29, 40, 1]);
    expect(resizeBox([10, 10, 40, 20], 'e', -100, 0)).toEqual([10, 10, 1, 20]);
  });

  it('Auswahlbox umschließt alle gewählten', () => {
    const boxes = objectBoxes(DOC, null);
    expect(selectionBox(['text1', 'qr1'], boxes)).toEqual([10, 5, 190, 50]);
    expect(selectionBox([], boxes)).toBeNull();
  });
});
