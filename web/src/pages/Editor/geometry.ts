/**
 * Anzeige-Geometrie des Editors: Zoom, Umrechnung Bildschirm und Druckpunkte, Anfasser,
 * Treffertest und Gummiband. Keine Dokumentlogik (die liegt im Python-Kern).
 */
import type { LabelDocumentJson } from '../../api/types';

/** [x, y, w, h] in Druckpunkten. */
export type Box = [number, number, number, number];
export type Point = [number, number];
export type Zoom = 'fit' | 1 | 2 | 4;
export const HANDLES = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'] as const;
export type Handle = (typeof HANDLES)[number];

export const DEFAULT_SCREEN_PX_PER_MM = 96 / 25.4;
/** Pfeiltasten: 1 Punkt, mit Umschalt 8 Punkte (1 mm beim P12). */
export const NUDGE_SMALL = 1;
export const NUDGE_LARGE = 8;

/** CSS-Pixel je Druckpunkt bei 100 % (echte Millimeter). */
export function cssPxPerDot(screenPxPerMm: number | null | undefined, dotsPerMm: number): number {
  return (screenPxPerMm ?? DEFAULT_SCREEN_PX_PER_MM) / (dotsPerMm > 0 ? dotsPerMm : 8);
}

/** Maßstab (CSS-Pixel je Punkt). „Anpassen“ füllt `availWidth`, ohne messbare Breite gilt 100 %. */
export function zoomScale(zoom: Zoom, base: number, docWidth: number, availWidth: number): number {
  if (zoom !== 'fit') return base * zoom;
  if (availWidth <= 0 || docWidth <= 0) return base;
  return Math.min(base * 16, Math.max(base / 4, availWidth / docWidth));
}

export function toDots(px: number, py: number, scale: number): Point {
  return [px / scale, py / scale];
}

export function toScreen(x: number, y: number, scale: number): Point {
  return [x * scale, y * scale];
}

export function handlePositions(box: Box): Record<Handle, Point> {
  const [x, y, w, h] = box;
  const cx = x + w / 2;
  const cy = y + h / 2;
  return {
    nw: [x, y],
    n: [cx, y],
    ne: [x + w, y],
    e: [x + w, cy],
    se: [x + w, y + h],
    s: [cx, y + h],
    sw: [x, y + h],
    w: [x, cy],
  };
}

/** Anfasser unter dem Punkt (Toleranz in Punkten). */
export function handleAt(point: Point, box: Box, tolerance: number): Handle | null {
  const positions = handlePositions(box);
  for (const handle of HANDLES) {
    const [hx, hy] = positions[handle];
    if (Math.abs(point[0] - hx) <= tolerance && Math.abs(point[1] - hy) <= tolerance) return handle;
  }
  return null;
}

/** Boxen je Objekt: Server-Boxen (`EditorOverlay.boxes`) haben Vorrang, sonst x/y/w/h. */
export function objectBoxes(
  doc: LabelDocumentJson,
  overlay: Record<string, [number, number, number, number]> | null | undefined,
): Record<string, Box> {
  const out: Record<string, Box> = {};
  for (const o of doc.objects) {
    const b = overlay?.[o.id];
    out[o.id] = b ? [b[0], b[1], b[2], b[3]] : [o.x, o.y, o.w, o.h];
  }
  return out;
}

/** Oberstes sichtbares Objekt am Punkt (spätere Objekte liegen vorne). */
export function hitTest(doc: LabelDocumentJson, boxes: Record<string, Box>, x: number, y: number): string | null {
  for (let i = doc.objects.length - 1; i >= 0; i -= 1) {
    const o = doc.objects[i]!;
    if (o.visible === false) continue;
    const b = boxes[o.id];
    if (!b) continue;
    if (x >= b[0] && x < b[0] + b[2] && y >= b[1] && y < b[1] + b[3]) return o.id;
  }
  return null;
}

/** Rechteck aus zwei Ecken als [x, y, w, h]. */
export function normRect(ax: number, ay: number, bx: number, by: number): Box {
  return [Math.min(ax, bx), Math.min(ay, by), Math.abs(bx - ax), Math.abs(by - ay)];
}

/** Sichtbare Objekte, die das Rechteck berühren (Dokumentreihenfolge). */
export function rubberBand(doc: LabelDocumentJson, boxes: Record<string, Box>, rect: Box): string[] {
  const [rx, ry, rw, rh] = rect;
  return doc.objects
    .filter((o) => {
      if (o.visible === false) return false;
      const b = boxes[o.id];
      if (!b) return false;
      return b[0] <= rx + rw && b[0] + b[2] >= rx && b[1] <= ry + rh && b[1] + b[3] >= ry;
    })
    .map((o) => o.id);
}

export function arrowDelta(key: string, shift: boolean): Point | null {
  const step = shift ? NUDGE_LARGE : NUDGE_SMALL;
  switch (key) {
    case 'ArrowLeft':
      return [-step, 0];
    case 'ArrowRight':
      return [step, 0];
    case 'ArrowUp':
      return [0, -step];
    case 'ArrowDown':
      return [0, step];
    default:
      return null;
  }
}

/** Box nach Ziehen eines Anfassers um (dx, dy); Breite und Höhe mindestens 1 Punkt. */
export function resizeBox(box: Box, handle: Handle, dx: number, dy: number): Box {
  let x0 = box[0];
  let y0 = box[1];
  let x1 = box[0] + box[2];
  let y1 = box[1] + box[3];
  if (handle.includes('w')) x0 = Math.min(x0 + dx, x1 - 1);
  if (handle.includes('e')) x1 = Math.max(x1 + dx, x0 + 1);
  if (handle.includes('n')) y0 = Math.min(y0 + dy, y1 - 1);
  if (handle.includes('s')) y1 = Math.max(y1 + dy, y0 + 1);
  return [x0, y0, x1 - x0, y1 - y0];
}

export function selectionBox(ids: string[], boxes: Record<string, Box>): Box | null {
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const id of ids) {
    const b = boxes[id];
    if (!b) continue;
    x0 = Math.min(x0, b[0]);
    y0 = Math.min(y0, b[1]);
    x1 = Math.max(x1, b[0] + b[2]);
    y1 = Math.max(y1, b[1] + b[3]);
  }
  return Number.isFinite(x0) ? [x0, y0, x1 - x0, y1 - y0] : null;
}
