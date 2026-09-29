/**
 * Fluent-2-Theme: Akzent des Systems, Farbschema nach Einstellung `app.theme` (wie Windows, hell,
 * dunkel), geprüfte Kontraste, sichtbarer Fokus, Kontrastdesigns (forced-colors), Segoe UI Variable.
 */
import { useEffect, useMemo, type ReactNode } from 'react';
import {
  createDarkTheme,
  createLightTheme,
  FluentProvider,
  makeStaticStyles,
  makeStyles,
  tokens,
  type BrandVariants,
  type Theme,
} from '@fluentui/react-components';
import { useAppInfo } from '../api/core';
import { brandFromAccent, DEFAULT_ACCENT, normalizeHex } from './brand';
import { contrastRatio } from './contrast';
import { useColorScheme } from './useSystemDark';

export const FONT_FAMILY = '"Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif';
export const FONT_FAMILY_DISPLAY = '"Segoe UI Variable Display", "Segoe UI", system-ui, sans-serif';

const STEPS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160] as const;
type Step = (typeof STEPS)[number];
const MIN_TEXT = 4.5;
const ON_BRAND = '#ffffff';

function stepAt(i: number): Step {
  return STEPS[Math.min(STEPS.length - 1, Math.max(0, i))] as Step;
}

/** Rampe um `shift` Stufen dunkler (Stufe 10 bleibt die dunkelste). */
function shiftRamp(brand: BrandVariants, shift: number): BrandVariants {
  if (shift === 0) return brand;
  const out: Record<number, string> = {};
  STEPS.forEach((step, i) => {
    out[step] = brand[stepAt(i - shift)];
  });
  return out as unknown as BrandVariants;
}

/**
 * Erste Stufe ab `start` in Richtung `dir` (-1 dunkler, +1 heller), deren Farbe `ok` erfüllt;
 * sonst die letzte geprüfte Stufe.
 */
function pickStep(brand: BrandVariants, start: Step, dir: -1 | 1, ok: (color: string) => boolean): string {
  let i = STEPS.indexOf(start);
  for (; i >= 0 && i < STEPS.length; i += dir) {
    if (ok(brand[stepAt(i)])) return brand[stepAt(i)];
  }
  return brand[stepAt(i - dir)];
}

/**
 * Theme aus Akzent und Hell/Dunkel. Helle Akzente (Gelb, Hellgrün, Weiß) werden korrigiert, bis
 * Markentext auf den Flächen und weißer Text auf Markenflächen mindestens 4.5:1 erreichen.
 */
export function buildTheme(accent: string | null | undefined, dark: boolean): Theme {
  const brand = brandFromAccent(normalizeHex(accent) ?? DEFAULT_ACCENT);
  // Markenfläche: Fluent nutzt hell Stufe 80, dunkel Stufe 70. Bei zu wenig Kontrast zu weißem
  // Text wird die ganze Rampe dunkler verschoben, damit Hover- und Druckstufen stimmig bleiben.
  const bgIndex = STEPS.indexOf(dark ? 70 : 80);
  let shift = 0;
  while (bgIndex - shift > 0 && contrastRatio(ON_BRAND, brand[stepAt(bgIndex - shift)]) < MIN_TEXT) shift += 1;
  const ramp = shiftRamp(brand, shift);
  const base = dark ? createDarkTheme(ramp) : createLightTheme(ramp);
  const readable = (color: string) =>
    contrastRatio(color, base.colorNeutralBackground1) >= MIN_TEXT &&
    contrastRatio(color, base.colorNeutralBackground2) >= MIN_TEXT;
  if (dark) {
    const fg1 = pickStep(brand, 110, 1, readable);
    const fg1Index = STEPS.findIndex((s) => brand[s] === fg1);
    return {
      ...base,
      colorNeutralForegroundOnBrand: ON_BRAND,
      colorBrandForeground1: fg1,
      colorBrandForeground2: brand[stepAt(Math.max(fg1Index, STEPS.indexOf(110)) + 1)],
      fontFamilyBase: FONT_FAMILY,
    };
  }
  const fg1 = pickStep(brand, 80, -1, readable);
  const fg1Index = STEPS.findIndex((s) => brand[s] === fg1);
  return {
    ...base,
    colorNeutralForegroundOnBrand: ON_BRAND,
    colorBrandForeground1: fg1,
    colorBrandForeground2: brand[stepAt(Math.min(fg1Index, STEPS.indexOf(80)) - 1)],
    fontFamilyBase: FONT_FAMILY,
  };
}

/** Globale Regeln (exportiert für Tests). */
export const GLOBAL_STYLES: Exclude<Parameters<typeof makeStaticStyles>[0], unknown[]> = {
  'html, body, #root': { height: '100%', margin: 0 },
  body: { overflow: 'hidden', WebkitFontSmoothing: 'antialiased', textRendering: 'optimizeLegibility' },
  // Fluent überträgt die className des FluentProvider (Höhe 100 %, Hintergrund) auf seine
  // Portal-Container unter <body>. Ohne diese Regel liegt der Container als deckende Fläche über
  // der ganzen Seite, sobald ein Toast, Tooltip oder Dialog eingehängt ist.
  'body > [data-portal-node].fui-FluentProvider': {
    height: 'auto',
    minHeight: 0,
    backgroundColor: 'transparent',
  },
  '.p12-visually-hidden': {
    position: 'absolute',
    width: '1px',
    height: '1px',
    padding: 0,
    margin: '-1px',
    overflow: 'hidden',
    clip: 'rect(0, 0, 0, 0)',
    whiteSpace: 'nowrap',
    border: 0,
  },
  // Sichtbarer Fokus für eigene Elemente. `:where` hat keine Spezifität, Fluent-Bausteine behalten
  // so ihren eigenen Fokusrahmen.
  ':where(:focus-visible)': {
    outline: `2px solid ${tokens.colorStrokeFocus2}`,
    outlineOffset: '2px',
  },
  // Überschriften, die nur per Programm den Fokus bekommen (Sprungziele, tabindex -1), ohne Rahmen:
  // Screenreader lesen sie trotzdem vor, sichtbar ist nur der Sprung.
  ':where(h1, h2, h3)[tabindex="-1"]:focus, :where(h1, h2, h3)[tabindex="-1"]:focus-visible': {
    outline: 'none',
  },
  // Kontrastdesigns von Windows: Rahmen statt Schatten, Fokus in Systemfarbe, Bandvorschau in echten Farben.
  '@media (forced-colors: active)': {
    '.fui-Card, .p12-card, .fui-Button, .fui-MessageBar': { border: '1px solid CanvasText' },
    ':focus-visible': { outline: '2px solid Highlight', outlineOffset: '2px' },
    '.p12-tape-image': { forcedColorAdjust: 'none' },
  },
  '@media (prefers-reduced-motion: reduce)': {
    '*, *::before, *::after': {
      animationDuration: '0.01ms !important',
      animationIterationCount: '1 !important',
      transitionDuration: '0.01ms !important',
      scrollBehavior: 'auto !important',
    },
  },
};
const useGlobalStyles = makeStaticStyles(GLOBAL_STYLES);

const useStyles = makeStyles({
  root: {
    height: '100%',
    backgroundColor: tokens.colorNeutralBackground2,
    color: tokens.colorNeutralForeground1,
    fontFamily: FONT_FAMILY,
    colorScheme: 'light',
    '& ::selection': { backgroundColor: tokens.colorBrandBackground2 },
    '& *': { scrollbarWidth: 'thin', scrollbarColor: `${tokens.colorNeutralStroke1} transparent` },
  },
  dark: { colorScheme: 'dark' },
});

export function ThemeProvider(props: { children: ReactNode }): JSX.Element {
  useGlobalStyles();
  const styles = useStyles();
  const app = useAppInfo();
  const dark = useColorScheme(app.data?.theme);
  const accent = app.data?.accent ?? null;
  const theme = useMemo(() => buildTheme(accent, dark), [accent, dark]);
  const mode = dark ? 'dark' : 'light';

  useEffect(() => {
    document.documentElement.dataset.theme = mode;
    document.documentElement.style.colorScheme = mode;
    document.body.style.backgroundColor = theme.colorNeutralBackground2;
  }, [mode, theme]);

  return (
    <FluentProvider
      theme={theme}
      data-theme={mode}
      className={dark ? `${styles.root} ${styles.dark}` : styles.root}
    >
      {props.children}
    </FluentProvider>
  );
}
