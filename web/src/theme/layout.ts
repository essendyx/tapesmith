/**
 * Einheitliche Abstände und Layout-Klassen: Abstände nur aus Fluent-Tokens. Einzige
 * Ausnahme sind die Maße des Formularrasters (`form`), die Fluent nicht als Token kennt.
 */
import { makeStyles, tokens } from '@fluentui/react-components';

export const space = {
  /** Außenabstand einer Seite und Abstand zwischen großen Blöcken. */
  page: tokens.spacingVerticalXXL,
  /** Abstand zwischen Karten (Section) bzw. nach dem Seitenkopf. */
  section: tokens.spacingVerticalXL,
  /** Abstand zwischen Formularfeldern. */
  field: tokens.spacingVerticalM,
  /** Abstand zwischen Elementen in einer Zeile (Knöpfe, Chips). */
  inline: tokens.spacingHorizontalS,
  /** Enger Abstand (Beschriftung und Wert). */
  tight: tokens.spacingVerticalXS,
} as const;

/**
 * Raster der Einstellungszeilen (Stil Windows-11-Einstellungen): links Beschriftung mit Hilfetext,
 * rechts eine Steuerspalte fester Breite, die jedes Eingabefeld, jede Auswahlliste und jeder
 * Einzelknopf exakt ausfüllt. Unter `narrow` stehen Beschriftung und Steuerelement untereinander.
 */
export const form = {
  /** Breite der Steuerspalte. */
  controlWidth: '300px',
  /** Mindesthöhe einer Zeile (Steuerelement Größe medium plus Innenabstand). */
  rowMinHeight: '56px',
  /** Ab hier untereinander statt nebeneinander. */
  narrow: '@media (max-width: 640px)',
} as const;

export const useLayoutStyles = makeStyles({
  stack: { display: 'flex', flexDirection: 'column', rowGap: space.section, minWidth: 0 },
  stackTight: { display: 'flex', flexDirection: 'column', rowGap: space.tight, minWidth: 0 },
  row: { display: 'flex', alignItems: 'center', columnGap: space.inline, minWidth: 0 },
  rowWrap: { display: 'flex', alignItems: 'center', flexWrap: 'wrap', columnGap: space.inline, rowGap: space.tight },
  grid2: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 320px), 1fr))',
    gap: space.section,
  },
  grid3: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 240px), 1fr))',
    gap: space.section,
  },
  formGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 260px), 1fr))',
    columnGap: tokens.spacingHorizontalL,
    rowGap: space.field,
  },
  actions: {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    justifyContent: 'flex-end',
    columnGap: space.inline,
    rowGap: space.tight,
  },
  muted: { color: tokens.colorNeutralForeground3 },
});
