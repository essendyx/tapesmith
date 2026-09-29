/**
 * Leinwand: zeigt das Server-Bild (`EditorOverlay.png`, 1 px = 1 Punkt) und zeichnet darüber nur
 * Auswahl, Anfasser, Hilfslinien, Gummiband und beim Ziehen einen halbtransparenten Geist.
 * Alle Änderungen gehen als Rückruf an die Seite (und von dort als Operation an den Server).
 */
import { useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent, type PointerEvent } from 'react';
import { Image as KImage, Layer, Line, Rect, Stage } from 'react-konva';
import { makeStyles, mergeClasses, tokens, webLightTheme, type Theme } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { pngSrc } from '../../api/client';
import type { EditorOverlay, EditorPreset, Guide, LabelDocumentJson, SnapResult } from '../../api/types';
import {
  handleAt,
  handlePositions,
  hitTest,
  normRect,
  objectBoxes,
  resizeBox,
  rubberBand,
  selectionBox,
  toDots,
  type Box,
  type Handle,
  type Point,
} from './geometry';
import { PRESET_MIME } from './presets';

/** Farben der Leinwand als Fluent-Tokens: Konva zeichnet auf ein Canvas und kennt keine CSS-Variablen. */
const CANVAS_TOKENS = {
  select: 'colorBrandStroke1',
  guide: 'colorPaletteBerryBorderActive',
  handle: 'colorNeutralBackground1',
} as const satisfies Record<string, keyof Theme>;

type CanvasColors = Record<keyof typeof CANVAS_TOKENS, string>;

/** Aktuelle Token-Werte am Element (Hell, Dunkel, Kontrast); ohne Element die hellen Standardwerte. */
function canvasColors(el: HTMLElement | null): CanvasColors {
  const style = el && typeof getComputedStyle === 'function' ? getComputedStyle(el) : null;
  const out = {} as CanvasColors;
  for (const [name, token] of Object.entries(CANVAS_TOKENS) as [keyof CanvasColors, keyof Theme][]) {
    const live = style?.getPropertyValue(`--${token}`).trim();
    out[name] = live || String(webLightTheme[token]);
  }
  return out;
}

const HANDLE_PX = 8;
const DRAG_START_PX = 3;
export const SNAP_INTERVAL_MS = 50;

const CURSORS: Record<Handle, string> = {
  n: 'ns-resize',
  s: 'ns-resize',
  e: 'ew-resize',
  w: 'ew-resize',
  ne: 'nesw-resize',
  sw: 'nesw-resize',
  nw: 'nwse-resize',
  se: 'nwse-resize',
};

type Drag =
  | { kind: 'band'; start: Point; cur: Point; base: string[]; startPx: Point }
  | {
      kind: 'move';
      start: Point;
      startPx: Point;
      ids: string[];
      raw: Point;
      shown: Point;
      guides: Guide[];
      active: boolean;
      reduceTo: string | null;
    }
  | { kind: 'resize'; start: Point; startPx: Point; id: string; handle: Handle; box: Box; raw: Point; shown: Point; guides: Guide[] };

export interface SnapQuery {
  ids: string[];
  dx: number;
  dy: number;
  mode: 'move' | 'resize';
  handle?: string;
}

const useStyles = makeStyles({
  frame: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXXS, width: 'max-content', margin: '0 auto' },
  ruler: { display: 'block', color: tokens.colorNeutralForeground3, overflow: 'visible' },
  surface: {
    position: 'relative',
    outline: 'none',
    borderRadius: tokens.borderRadiusSmall,
    boxShadow: tokens.shadow8,
    touchAction: 'none',
    ':focus-visible': { boxShadow: `0 0 0 2px ${tokens.colorStrokeFocus2}, ${tokens.shadow8}` },
  },
  dropping: { boxShadow: `0 0 0 3px ${tokens.colorBrandStroke1}, ${tokens.shadow8}` },
  placeholder: {
    display: 'grid',
    placeItems: 'center',
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
  },
});

function useLoadedImage(b64: string | undefined): HTMLImageElement | null {
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  useEffect(() => {
    if (!b64) return undefined;
    let alive = true;
    const el = new window.Image();
    el.onload = () => {
      if (alive) setImg(el);
    };
    el.src = pngSrc(b64);
    return () => {
      alive = false;
    };
  }, [b64]);
  return img;
}

function Ruler(props: { widthDots: number; scale: number; dotsPerMm: number }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('editor');
  const { widthDots, scale, dotsPerMm } = props;
  const mmCount = Math.floor(widthDots / dotsPerMm);
  const pxPerMm = scale * dotsPerMm;
  const labelEvery = pxPerMm >= 12 ? 5 : pxPerMm >= 5 ? 10 : 20;
  const tickEvery = pxPerMm >= 4 ? 1 : 5;
  const ticks: JSX.Element[] = [];
  for (let mm = 0; mm <= mmCount; mm += tickEvery) {
    const x = mm * pxPerMm + 0.5;
    const major = mm % labelEvery === 0;
    const mid = mm % 5 === 0;
    ticks.push(<line key={`t${mm}`} x1={x} x2={x} y1={major ? 4 : mid ? 9 : 12} y2={16} stroke="currentColor" strokeWidth={1} />);
    if (major) {
      ticks.push(
        <text key={`l${mm}`} x={x + 2} y={9} fontSize={9} fill="currentColor">
          {mm}
        </text>,
      );
    }
  }
  return (
    <svg className={styles.ruler} width={widthDots * scale} height={16} role="img" aria-label={t('canvas.ruler', { mm: mmCount })}>
      {ticks}
    </svg>
  );
}

export function EditorCanvas(props: {
  doc: LabelDocumentJson;
  overlay: EditorOverlay | null;
  selection: string[];
  scale: number;
  dotsPerMm: number;
  grid: boolean;
  snap: boolean;
  background: string;
  placeholderSize: [number, number];
  guides: Guide[];
  onSelect: (ids: string[]) => void;
  onMoveEnd: (ids: string[], dx: number, dy: number) => void;
  onResizeEnd: (id: string, handle: Handle, box: Box, dx: number, dy: number) => void;
  snapQuery: (q: SnapQuery, signal: AbortSignal) => Promise<SnapResult>;
  onKeyDown: (e: KeyboardEvent<HTMLDivElement>) => void;
  onDropPreset: (preset: EditorPreset, at: Point) => void;
  onDropFiles: (files: File[], at: Point) => void;
}): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('editor');
  const { doc, overlay, selection, scale } = props;
  const img = useLoadedImage(overlay?.png);
  const widthDots = overlay?.width ?? props.placeholderSize[0];
  const heightDots = overlay?.height ?? props.placeholderSize[1];
  const W = Math.max(1, Math.round(widthDots * scale));
  const H = Math.max(1, Math.round(heightDots * scale));
  const boxes = useMemo(() => objectBoxes(doc, overlay?.boxes), [doc, overlay]);
  const surfaceRef = useRef<HTMLDivElement>(null);
  const [drag, setDragState] = useState<Drag | null>(null);
  const dragRef = useRef<Drag | null>(null);
  const [cursor, setCursor] = useState('default');
  const [dropping, setDropping] = useState(false);
  const snapState = useRef<{ seq: number; applied: number; lastSent: number; timer: ReturnType<typeof setTimeout> | null; ctrl: AbortController | null }>({
    seq: 0,
    applied: 0,
    lastSent: 0,
    timer: null,
    ctrl: null,
  });

  const setDrag = (d: Drag | null) => {
    dragRef.current = d;
    setDragState(d);
  };

  useEffect(
    () => () => {
      const s = snapState.current;
      if (s.timer) clearTimeout(s.timer);
      s.ctrl?.abort();
    },
    [],
  );

  const pointAt = (clientX: number, clientY: number): { dots: Point; px: Point } => {
    const rect = surfaceRef.current?.getBoundingClientRect();
    const px: Point = [clientX - (rect?.left ?? 0), clientY - (rect?.top ?? 0)];
    return { dots: toDots(px[0], px[1], scale), px };
  };

  const singleBox = (): Box | null => {
    if (selection.length !== 1) return null;
    const o = doc.objects.find((x) => x.id === selection[0]);
    return o ? [o.x, o.y, o.w, o.h] : null;
  };

  const movable = (ids: string[]) => ids.filter((id) => doc.objects.find((o) => o.id === id)?.locked !== true);

  /** Live-Einrasten: höchstens alle 50 ms eine Anfrage, die letzte Antwort gewinnt. */
  const requestSnap = () => {
    const d = dragRef.current;
    if (!props.snap || !d || d.kind === 'band') return;
    const s = snapState.current;
    const now = Date.now();
    const wait = SNAP_INTERVAL_MS - (now - s.lastSent);
    if (wait > 0) {
      if (!s.timer) {
        s.timer = setTimeout(() => {
          s.timer = null;
          requestSnap();
        }, wait);
      }
      return;
    }
    s.lastSent = now;
    s.seq += 1;
    const seq = s.seq;
    const raw = d.raw;
    const q: SnapQuery =
      d.kind === 'move'
        ? { ids: d.ids, dx: raw[0], dy: raw[1], mode: 'move' }
        : { ids: [d.id], dx: raw[0], dy: raw[1], mode: 'resize', handle: d.handle };
    const ctrl = new AbortController();
    s.ctrl = ctrl;
    props.snapQuery(q, ctrl.signal).then(
      (res) => {
        if (seq < s.applied) return;
        s.applied = seq;
        const cur = dragRef.current;
        if (!cur || cur.kind === 'band') return;
        const same = cur.raw[0] === raw[0] && cur.raw[1] === raw[1];
        setDrag({ ...cur, shown: same ? [res.dx, res.dy] : cur.shown, guides: res.guides });
      },
      () => undefined,
    );
  };

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    surfaceRef.current?.focus();
    const { dots, px } = pointAt(e.clientX, e.clientY);
    const additive = e.shiftKey || e.ctrlKey || e.metaKey;
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      // jsdom und alte Browser
    }
    const box = singleBox();
    if (!additive && box && selection[0] && movable(selection).length === 1) {
      const handle = handleAt(dots, box, (HANDLE_PX / 2 + 2) / scale);
      if (handle) {
        setDrag({ kind: 'resize', start: dots, startPx: px, id: selection[0], handle, box, raw: [0, 0], shown: [0, 0], guides: [] });
        return;
      }
    }
    const hit = hitTest(doc, boxes, dots[0], dots[1]);
    if (hit) {
      if (additive) {
        props.onSelect(selection.includes(hit) ? selection.filter((id) => id !== hit) : [...selection, hit]);
        return;
      }
      const ids = selection.includes(hit) ? selection : [hit];
      if (!selection.includes(hit)) props.onSelect([hit]);
      const moving = movable(ids);
      if (moving.length > 0) {
        setDrag({
          kind: 'move',
          start: dots,
          startPx: px,
          ids: moving,
          raw: [0, 0],
          shown: [0, 0],
          guides: [],
          active: false,
          reduceTo: selection.length > 1 && selection.includes(hit) ? hit : null,
        });
      }
      return;
    }
    const base = additive ? selection : [];
    if (!additive && selection.length) props.onSelect([]);
    setDrag({ kind: 'band', start: dots, cur: dots, base, startPx: px });
  };

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const { dots, px } = pointAt(e.clientX, e.clientY);
    const d = dragRef.current;
    if (!d) {
      const box = singleBox();
      const handle = box && movable(selection).length === 1 ? handleAt(dots, box, (HANDLE_PX / 2 + 2) / scale) : null;
      const hit = handle ? null : hitTest(doc, boxes, dots[0], dots[1]);
      setCursor(handle ? CURSORS[handle] : hit ? (movable([hit]).length ? 'move' : 'not-allowed') : 'default');
      return;
    }
    if (d.kind === 'band') {
      setDrag({ ...d, cur: dots });
      return;
    }
    const raw: Point = [Math.round(dots[0] - d.start[0]), Math.round(dots[1] - d.start[1])];
    if (d.kind === 'move' && !d.active) {
      if (Math.hypot(px[0] - d.startPx[0], px[1] - d.startPx[1]) < DRAG_START_PX) return;
    }
    if (raw[0] === d.raw[0] && raw[1] === d.raw[1] && (d.kind !== 'move' || d.active)) return;
    const next: Drag = d.kind === 'move' ? { ...d, raw, shown: raw, active: true, reduceTo: null } : { ...d, raw, shown: raw };
    setDrag(next);
    requestSnap();
  };

  const finish = (e: PointerEvent<HTMLDivElement>) => {
    const d = dragRef.current;
    const s = snapState.current;
    if (s.timer) clearTimeout(s.timer);
    s.timer = null;
    s.ctrl?.abort();
    setDrag(null);
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      // ignorieren
    }
    if (!d) return;
    if (d.kind === 'band') {
      const { px } = pointAt(e.clientX, e.clientY);
      if (Math.hypot(px[0] - d.startPx[0], px[1] - d.startPx[1]) < DRAG_START_PX) return;
      const found = rubberBand(doc, boxes, normRect(d.start[0], d.start[1], d.cur[0], d.cur[1]));
      props.onSelect([...new Set([...d.base, ...found])]);
      return;
    }
    if (d.kind === 'move') {
      if (!d.active) {
        if (d.reduceTo) props.onSelect([d.reduceTo]);
        return;
      }
      if (d.raw[0] !== 0 || d.raw[1] !== 0) props.onMoveEnd(d.ids, d.raw[0], d.raw[1]);
      return;
    }
    if (d.raw[0] !== 0 || d.raw[1] !== 0) props.onResizeEnd(d.id, d.handle, d.box, d.raw[0], d.raw[1]);
  };

  const onDragOver = (e: DragEvent<HTMLDivElement>) => {
    const types = Array.from(e.dataTransfer.types);
    if (types.includes(PRESET_MIME) || types.includes('Files')) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
      setDropping(true);
    }
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDropping(false);
    const { dots } = pointAt(e.clientX, e.clientY);
    const at: Point = [Math.max(0, Math.round(dots[0])), Math.max(0, Math.round(dots[1]))];
    const preset = e.dataTransfer.getData(PRESET_MIME);
    if (preset) {
      props.onDropPreset(preset as EditorPreset, at);
      return;
    }
    const files = Array.from(e.dataTransfer.files ?? []).filter((f) => f.type.startsWith('image/') || /\.(png|jpe?g|bmp|gif|svg|webp)$/i.test(f.name));
    if (files.length) props.onDropFiles(files, at);
  };

  // --- Zeichnen ---------------------------------------------------------------
  const moveOffset: Point = drag?.kind === 'move' && drag.active ? drag.shown : [0, 0];
  const liveGuides = drag && drag.kind !== 'band' ? drag.guides : props.guides;
  const selBoxes = selection.map((id) => boxes[id]).filter((b): b is Box => b !== undefined);
  const groupBox = selectionBox(selection, boxes);
  const resizing = drag?.kind === 'resize' ? resizeBox(drag.box, drag.handle, drag.shown[0], drag.shown[1]) : null;
  const handleBox = resizing ?? (selection.length === 1 && movable(selection).length === 1 ? singleBox() : null);
  const lockedSel = selection.filter((id) => !movable([id]).length);

  const colors = canvasColors(surfaceRef.current);
  const gridLines: JSX.Element[] = [];
  if (props.grid) {
    const step = props.dotsPerMm;
    if (step * scale >= 4) {
      for (let x = step; x < widthDots; x += step) {
        gridLines.push(<Line key={`gx${x}`} points={[x * scale, 0, x * scale, H]} stroke={colors.select} opacity={(x / step) % 5 === 0 ? 0.28 : 0.12} strokeWidth={1} listening={false} />);
      }
      for (let y = step; y < heightDots; y += step) {
        gridLines.push(<Line key={`gy${y}`} points={[0, y * scale, W, y * scale]} stroke={colors.select} opacity={(y / step) % 5 === 0 ? 0.28 : 0.12} strokeWidth={1} listening={false} />);
      }
    }
  }

  const ghostBox = drag?.kind === 'move' && drag.active ? selectionBox(drag.ids, boxes) : drag?.kind === 'resize' ? drag.box : null;

  return (
    <div className={styles.frame}>
      <Ruler widthDots={widthDots} scale={scale} dotsPerMm={props.dotsPerMm} />
      <div
        ref={surfaceRef}
        className={mergeClasses(styles.surface, dropping && styles.dropping)}
        style={{ width: W, height: H, backgroundColor: props.background, cursor: drag?.kind === 'move' ? 'grabbing' : cursor }}
        tabIndex={0}
        role="application"
        aria-label={t('canvas.label')}
        aria-roledescription={t('canvas.role')}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={finish}
        onPointerCancel={finish}
        onKeyDown={props.onKeyDown}
        onDragOver={onDragOver}
        onDragLeave={() => setDropping(false)}
        onDrop={onDrop}
      >
        {overlay ? (
          <Stage width={W} height={H} listening={false}>
            <Layer imageSmoothingEnabled={false} listening={false}>
              {img ? <KImage image={img} x={0} y={0} width={W} height={H} /> : null}
            </Layer>
            <Layer listening={false}>
              {gridLines}
              {img && ghostBox && drag?.kind === 'move' ? (
                <KImage
                  image={img}
                  crop={{ x: ghostBox[0], y: ghostBox[1], width: Math.max(1, ghostBox[2]), height: Math.max(1, ghostBox[3]) }}
                  x={(ghostBox[0] + moveOffset[0]) * scale}
                  y={(ghostBox[1] + moveOffset[1]) * scale}
                  width={ghostBox[2] * scale}
                  height={ghostBox[3] * scale}
                  opacity={0.55}
                />
              ) : null}
              {img && ghostBox && resizing ? (
                <KImage
                  image={img}
                  crop={{ x: ghostBox[0], y: ghostBox[1], width: Math.max(1, ghostBox[2]), height: Math.max(1, ghostBox[3]) }}
                  x={resizing[0] * scale}
                  y={resizing[1] * scale}
                  width={resizing[2] * scale}
                  height={resizing[3] * scale}
                  opacity={0.55}
                />
              ) : null}
              {selBoxes.map((b, i) => (
                <Rect
                  key={`sel${selection[i]}`}
                  x={(b[0] + moveOffset[0]) * scale + 0.5}
                  y={(b[1] + moveOffset[1]) * scale + 0.5}
                  width={b[2] * scale}
                  height={b[3] * scale}
                  stroke={colors.select}
                  strokeWidth={1}
                  dash={lockedSel.includes(selection[i] ?? '') ? [4, 3] : undefined}
                />
              ))}
              {groupBox && selection.length > 1 ? (
                <Rect
                  x={(groupBox[0] + moveOffset[0]) * scale - 2}
                  y={(groupBox[1] + moveOffset[1]) * scale - 2}
                  width={groupBox[2] * scale + 4}
                  height={groupBox[3] * scale + 4}
                  stroke={colors.select}
                  strokeWidth={1}
                  dash={[6, 4]}
                />
              ) : null}
              {handleBox && drag?.kind !== 'move'
                ? Object.entries(handlePositions(handleBox)).map(([name, [hx, hy]]) => (
                    <Rect
                      key={`h${name}`}
                      x={hx * scale - HANDLE_PX / 2}
                      y={hy * scale - HANDLE_PX / 2}
                      width={HANDLE_PX}
                      height={HANDLE_PX}
                      cornerRadius={2}
                      fill={colors.handle}
                      stroke={colors.select}
                      strokeWidth={1.5}
                    />
                  ))
                : null}
              {resizing ? (
                <Rect x={resizing[0] * scale} y={resizing[1] * scale} width={resizing[2] * scale} height={resizing[3] * scale} stroke={colors.select} strokeWidth={1} dash={[4, 3]} />
              ) : null}
              {liveGuides.map((g, i) => (
                <Line
                  key={`g${i}`}
                  points={g.axis === 'x' ? [g.pos * scale, 0, g.pos * scale, H] : [0, g.pos * scale, W, g.pos * scale]}
                  stroke={colors.guide}
                  strokeWidth={1}
                  dash={g.label === 'grid' ? [2, 3] : undefined}
                />
              ))}
              {drag?.kind === 'band' ? (
                (() => {
                  const r = normRect(drag.start[0], drag.start[1], drag.cur[0], drag.cur[1]);
                  const box = { x: r[0] * scale, y: r[1] * scale, width: r[2] * scale, height: r[3] * scale };
                  return (
                    <>
                      <Rect {...box} fill={colors.select} opacity={0.12} />
                      <Rect {...box} stroke={colors.select} strokeWidth={1} dash={[4, 3]} />
                    </>
                  );
                })()
              ) : null}
            </Layer>
          </Stage>
        ) : (
          <div className={styles.placeholder} style={{ width: W, height: H }}>
            {t('canvas.rendering')}
          </div>
        )}
      </div>
    </div>
  );
}
