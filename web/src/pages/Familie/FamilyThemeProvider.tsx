/**
 * Eigenes, schlankes Theme für die Familienseite: dieselbe Marken- und Dunkelmodus-Logik wie
 * `theme/ThemeProvider.tsx` (Funktionen von dort wiederverwendet), aber ohne dessen `useAppInfo()`
 * (das würde `/api/v1/app` mit dem Admin-Token aufrufen, was die Familienseite nie darf). Der Akzent
 * ist deshalb immer der Standardwert.
 */
import { useEffect, useMemo, type ReactNode } from 'react';
import { FluentProvider, makeStaticStyles, makeStyles, tokens } from '@fluentui/react-components';
import { buildTheme, FONT_FAMILY } from '../../theme/ThemeProvider';
import { useSystemDark } from '../../theme/useSystemDark';

// Dieselben Fokus-, Kontrastdesign- und Reduced-Motion-Regeln wie `theme/ThemeProvider.tsx`
// (Besonderheit der Familienseite: eigenes Theme), von dort übernommen.
const useGlobalStyles = makeStaticStyles({
  'html, body, #root': { height: '100%', margin: 0 },
  body: { WebkitFontSmoothing: 'antialiased', textRendering: 'optimizeLegibility' },
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
  // Kontrastdesigns von Windows: Rahmen statt Schatten, Fokus in Systemfarbe.
  '@media (forced-colors: active)': {
    '.fui-Card, .p12-card, .fui-Button, .fui-MessageBar': { border: '1px solid CanvasText' },
    ':focus-visible': { outline: '2px solid Highlight', outlineOffset: '2px' },
  },
  '@media (prefers-reduced-motion: reduce)': {
    '*, *::before, *::after': {
      animationDuration: '0.01ms !important',
      animationIterationCount: '1 !important',
      transitionDuration: '0.01ms !important',
      scrollBehavior: 'auto !important',
    },
  },
});

const useStyles = makeStyles({
  root: {
    minHeight: '100%',
    backgroundColor: tokens.colorNeutralBackground2,
    color: tokens.colorNeutralForeground1,
    fontFamily: FONT_FAMILY,
    colorScheme: 'light',
    '& ::selection': { backgroundColor: tokens.colorBrandBackground2 },
    '& *': { scrollbarWidth: 'thin', scrollbarColor: `${tokens.colorNeutralStroke1} transparent` },
  },
  dark: { colorScheme: 'dark' },
});

export function FamilyThemeProvider(props: { children: ReactNode }): JSX.Element {
  useGlobalStyles();
  const styles = useStyles();
  const dark = useSystemDark();
  const theme = useMemo(() => buildTheme(null, dark), [dark]);
  const mode = dark ? 'dark' : 'light';

  useEffect(() => {
    // `document.documentElement.lang` setzt `main.tsx` schon vor dem ersten Rendern aus der
    // aufgelösten Sprache (auf der Familienseite immer "auto"); hier nicht mit einem
    // festen Wert wie "de" überschreiben.
    document.documentElement.dataset.theme = mode;
    document.documentElement.style.colorScheme = mode;
    document.body.style.backgroundColor = theme.colorNeutralBackground2;
  }, [mode, theme]);

  return (
    <FluentProvider theme={theme} data-theme={mode} className={dark ? `${styles.root} ${styles.dark}` : styles.root}>
      {props.children}
    </FluentProvider>
  );
}
