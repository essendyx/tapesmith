import { describe, expect, it } from 'vitest';
import { checkThemeContrast, contrastRatio, parseColor } from './contrast';
import { buildTheme } from './ThemeProvider';

const ACCENTS = ['#0078d4', '#e3008c', '#ffb900', '#00cc6a', '#ffffff', '#000000'];

describe('contrastRatio', () => {
  it('Schwarz auf Weiß ist 21:1, gleiche Farben 1:1', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 5);
    expect(contrastRatio('#fff', '#ffffff')).toBeCloseTo(1, 5);
  });

  it('bekannter Wert: #767676 auf Weiß knapp über 4.5', () => {
    expect(contrastRatio('#767676', '#ffffff')).toBeGreaterThan(4.5);
    expect(contrastRatio('#777777', '#ffffff')).toBeLessThan(4.5);
  });

  it('rgba mit Alpha wird über den Hintergrund gelegt', () => {
    expect(contrastRatio('rgba(0, 0, 0, 0)', '#ffffff')).toBeCloseTo(1, 5);
    expect(contrastRatio('rgba(0,0,0,1)', '#ffffff')).toBeCloseTo(21, 5);
    const half = contrastRatio('rgba(0, 0, 0, 0.5)', '#ffffff');
    expect(half).toBeGreaterThan(3);
    expect(half).toBeLessThan(5);
  });

  it('parseColor liest Hex und rgb()', () => {
    expect(parseColor('#0078d4')).toEqual({ r: 0, g: 120, b: 212, a: 1 });
    expect(parseColor('rgb(1, 2, 3)')).toEqual({ r: 1, g: 2, b: 3, a: 1 });
    expect(parseColor('transparent')).toBeNull();
  });
});

describe('checkThemeContrast', () => {
  for (const accent of ACCENTS) {
    for (const dark of [false, true]) {
      it(`${accent} ${dark ? 'dunkel' : 'hell'} besteht alle Paare`, () => {
        expect(checkThemeContrast(buildTheme(accent, dark))).toEqual([]);
      });
    }
  }

  it('meldet ein unlesbares Paar', () => {
    const t = { ...buildTheme('#0078d4', false), colorNeutralForeground3: '#eeeeee' };
    expect(checkThemeContrast(t).map((x) => x.pair)).toContain('colorNeutralForeground3 auf colorNeutralBackground1');
  });
});
