/** WCAG-2.1-Kontrastprüfung für Themes: Paare aus Vorder- und Hintergrund-Token. */
import type { Theme } from '@fluentui/react-components';

interface Rgba {
  r: number;
  g: number;
  b: number;
  a: number;
}

function clamp255(v: number): number {
  return Math.min(255, Math.max(0, v));
}

/** Liest "#rgb", "#rrggbb", "#rrggbbaa", "rgb(...)" und "rgba(...)"; sonst null. */
export function parseColor(value: string): Rgba | null {
  const v = value.trim().toLowerCase();
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/.exec(v);
  if (hex?.[1]) {
    let h = hex[1];
    if (h.length === 3) h = h.split('').map((c) => c + c).join('');
    const n = (i: number) => parseInt(h.slice(i, i + 2), 16);
    return { r: n(0), g: n(2), b: n(4), a: h.length === 8 ? n(6) / 255 : 1 };
  }
  const fn = /^rgba?\(([^)]+)\)$/.exec(v);
  if (fn?.[1]) {
    const parts = fn[1].split(/[\s,/]+/).filter(Boolean);
    if (parts.length < 3) return null;
    const num = (p: string | undefined, scale: number) => {
      if (p === undefined) return 1;
      return p.endsWith('%') ? (parseFloat(p) / 100) * scale : parseFloat(p);
    };
    const c = { r: num(parts[0], 255), g: num(parts[1], 255), b: num(parts[2], 255), a: num(parts[3], 1) };
    if ([c.r, c.g, c.b, c.a].some((x) => Number.isNaN(x))) return null;
    return { r: clamp255(c.r), g: clamp255(c.g), b: clamp255(c.b), a: Math.min(1, Math.max(0, c.a)) };
  }
  return null;
}

function over(top: Rgba, bottom: Rgba): Rgba {
  const a = top.a;
  return {
    r: top.r * a + bottom.r * (1 - a),
    g: top.g * a + bottom.g * (1 - a),
    b: top.b * a + bottom.b * (1 - a),
    a: 1,
  };
}

function relLuminance(c: Rgba): number {
  const lin = (v: number) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b);
}

const WHITE: Rgba = { r: 255, g: 255, b: 255, a: 1 };

/**
 * Kontrastverhältnis nach WCAG 2.1 (1 bis 21). Ein Vordergrund mit Alpha wird über den
 * Hintergrund gelegt, ein Hintergrund mit Alpha über Weiß. Unlesbare Farben ergeben 1.
 */
export function contrastRatio(fg: string, bg: string): number {
  const b0 = parseColor(bg);
  const f0 = parseColor(fg);
  if (!b0 || !f0) return 1;
  const b = b0.a < 1 ? over(b0, WHITE) : b0;
  const f = f0.a < 1 ? over(f0, b) : f0;
  const l1 = relLuminance(f);
  const l2 = relLuminance(b);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

type ThemeKey = keyof Theme;

/** Geprüfte Paare: [Vordergrund, Hintergrund, Mindestkontrast]. 4.5 für Text, 3 für Fokus und Symbole. */
export const CONTRAST_PAIRS: readonly [ThemeKey, ThemeKey, number][] = [
  ['colorNeutralForeground1', 'colorNeutralBackground1', 4.5],
  ['colorNeutralForeground1', 'colorNeutralBackground2', 4.5],
  ['colorNeutralForeground1', 'colorNeutralBackground3', 4.5],
  ['colorNeutralForeground2', 'colorNeutralBackground1', 4.5],
  ['colorNeutralForeground2', 'colorNeutralBackground2', 4.5],
  ['colorNeutralForeground2', 'colorNeutralBackground3', 4.5],
  ['colorNeutralForeground3', 'colorNeutralBackground1', 4.5],
  ['colorNeutralForeground3', 'colorNeutralBackground2', 4.5],
  ['colorNeutralForeground3', 'colorNeutralBackground3', 4.5],
  ['colorBrandForeground1', 'colorNeutralBackground1', 4.5],
  ['colorBrandForeground1', 'colorNeutralBackground2', 4.5],
  ['colorNeutralForegroundOnBrand', 'colorBrandBackground', 4.5],
  ['colorPaletteRedForeground1', 'colorNeutralBackground1', 4.5],
  ['colorPaletteDarkOrangeForeground1', 'colorNeutralBackground1', 4.5],
  ['colorPaletteGreenForeground1', 'colorNeutralBackground1', 4.5],
  ['colorStrokeFocus2', 'colorNeutralBackground2', 3],
];

/** Alle Paare unter ihrem Mindestkontrast (leer heißt: Theme besteht). */
export function checkThemeContrast(theme: Theme): { pair: string; ratio: number }[] {
  const out: { pair: string; ratio: number }[] = [];
  for (const [fg, bg, min] of CONTRAST_PAIRS) {
    const ratio = contrastRatio(String(theme[fg]), String(theme[bg]));
    if (ratio < min) out.push({ pair: `${String(fg)} auf ${String(bg)}`, ratio: Math.round(ratio * 100) / 100 });
  }
  return out;
}
