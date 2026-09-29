/** Fluent-Markenrampe (16 Stufen) aus einer Akzentfarbe. */
import type { BrandVariants } from '@fluentui/react-components';

export const DEFAULT_ACCENT = '#0078d4';

const STEPS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160] as const;
const ACCENT_INDEX = 7; // Stufe 80

interface Hsl {
  h: number;
  s: number;
  l: number;
}

export function normalizeHex(hex: string | null | undefined): string | null {
  if (!hex) return null;
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
  if (!m?.[1]) return null;
  let v = m[1].toLowerCase();
  if (v.length === 3) v = v.split('').map((c) => c + c).join('');
  return `#${v}`;
}

function hexToHsl(hex: string): Hsl {
  const n = parseInt(hex.slice(1), 16);
  const r = ((n >> 16) & 255) / 255;
  const g = ((n >> 8) & 255) / 255;
  const b = (n & 255) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return { h: 0, s: 0, l };
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h: number;
  if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  return { h: h * 60, s, l };
}

function hslToHex({ h, s, l }: Hsl): string {
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = l - c / 2;
  let rgb: [number, number, number];
  if (h < 60) rgb = [c, x, 0];
  else if (h < 120) rgb = [x, c, 0];
  else if (h < 180) rgb = [0, c, x];
  else if (h < 240) rgb = [0, x, c];
  else if (h < 300) rgb = [x, 0, c];
  else rgb = [c, 0, x];
  return `#${rgb
    .map((v) => Math.round(Math.min(1, Math.max(0, v + m)) * 255).toString(16).padStart(2, '0'))
    .join('')}`;
}

/** Relative Helligkeit (0 bis 1) einer Farbe "#rrggbb". */
export function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  const lin = (v: number) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
}

/**
 * 16 Stufen 10 bis 160 nach Fluent-Konvention: 10 ist die dunkelste, 160 die hellste Stufe,
 * Stufe 80 ist genau der Akzent. Darunter wird über HSL abgedunkelt, darüber aufgehellt.
 */
export function brandFromAccent(hex: string): BrandVariants {
  const accent = normalizeHex(hex) ?? DEFAULT_ACCENT;
  const base = hexToHsl(accent);
  const darkest = Math.min(0.06, base.l * 0.5);
  const lightest = Math.max(0.96, base.l);
  const out: Record<number, string> = {};
  STEPS.forEach((step, i) => {
    if (i === ACCENT_INDEX) {
      out[step] = accent;
      return;
    }
    let l: number;
    let s = base.s;
    if (i < ACCENT_INDEX) {
      const t = i / ACCENT_INDEX;
      l = darkest + (base.l - darkest) * t;
    } else {
      const t = (i - ACCENT_INDEX) / (STEPS.length - 1 - ACCENT_INDEX);
      l = base.l + (lightest - base.l) * t;
      s = base.s * (1 - 0.25 * t);
    }
    out[step] = hslToHex({ h: base.h, s, l });
  });
  return out as unknown as BrandVariants;
}
