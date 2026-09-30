/** Startansicht: Raster großer Kacheln, eine je freigegebener Vorlage. */
import { Body1, makeStyles, tokens } from '@fluentui/react-components';
import type { FamilyTemplate } from './types';

const useStyles = makeStyles({
  grid: {
    display: 'grid',
    // minmax(0, 1fr): sonst wächst eine Spalte auf die Breite der längsten (nicht umbrechenden)
    // Beschreibung und die Seite läuft auf dem Handy seitlich über.
    gridTemplateColumns: 'minmax(0, 1fr)',
    gap: tokens.spacingHorizontalM,
    '@media (min-width: 480px)': { gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' },
    '@media (min-width: 800px)': { gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' },
    '@media (min-width: 1100px)': { gridTemplateColumns: 'repeat(4, minmax(0, 1fr))' },
  },
  tile: {
    minHeight: '72px',
    minWidth: 0,
    display: 'flex',
    flexDirection: 'column',
    justifyContent: 'center',
    rowGap: tokens.spacingVerticalXS,
    borderRadius: tokens.borderRadiusXLarge,
    backgroundColor: tokens.colorNeutralBackground1,
    boxShadow: tokens.shadow4,
    padding: tokens.spacingVerticalM,
    boxSizing: 'border-box',
    border: 'none',
    cursor: 'pointer',
    textAlign: 'left',
    font: 'inherit',
    color: 'inherit',
  },
  /** Titel ruhig und lesbar: halbfett in Grundschrift, höchstens drei Zeilen. */
  title: {
    fontSize: tokens.fontSizeBase400,
    lineHeight: tokens.lineHeightBase400,
    fontWeight: tokens.fontWeightSemibold,
    display: '-webkit-box',
    WebkitLineClamp: 3,
    WebkitBoxOrient: 'vertical',
    overflow: 'hidden',
  },
  description: {
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    color: tokens.colorNeutralForeground2,
  },
});

export function TemplateGrid(props: { templates: FamilyTemplate[]; onSelect: (name: string) => void }): JSX.Element {
  const styles = useStyles();
  return (
    <div className={styles.grid}>
      {props.templates.map((t) => (
        <button key={t.name} type="button" className={styles.tile} onClick={() => props.onSelect(t.name)}>
          <span className={styles.title}>{t.title}</span>
          {t.description && t.description !== t.title ? <Body1 className={styles.description}>{t.description}</Body1> : null}
        </button>
      ))}
    </div>
  );
}
