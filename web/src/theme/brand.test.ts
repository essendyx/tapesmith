import { describe, expect, it } from 'vitest';
import { brandFromAccent, DEFAULT_ACCENT, luminance } from './brand';

const STEPS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160] as const;

describe('brandFromAccent', () => {
  it('liefert 16 Stufen, Stufe 80 ist der Akzent', () => {
    const b = brandFromAccent('#0078d4');
    expect(Object.keys(b)).toHaveLength(16);
    expect(b[80]).toBe('#0078d4');
    for (const s of STEPS) expect(b[s]).toMatch(/^#[0-9a-f]{6}$/);
  });

  it('Stufen sind nach Fluent-Konvention geordnet: 10 dunkel, 160 hell', () => {
    const b = brandFromAccent('#0078d4');
    const lum = STEPS.map((s) => luminance(b[s]));
    for (let i = 1; i < lum.length; i += 1) expect(lum[i]!).toBeGreaterThan(lum[i - 1]!);
  });

  it('ungültige Farbe fällt auf den Standard-Akzent zurück, kurze Form wird erweitert', () => {
    expect(brandFromAccent('kein')[80]).toBe(DEFAULT_ACCENT);
    expect(brandFromAccent('#F00')[80]).toBe('#ff0000');
  });
});
