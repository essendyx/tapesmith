/** Objekt-Palette: Klick fügt ein, Ziehen auf die Leinwand setzt die Position. */
import { Button, Tooltip, makeStyles, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import type { EditorPreset } from '../../api/types';
import { PALETTE, PRESET_MIME } from './presets';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    rowGap: tokens.spacingVerticalXS,
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalXS}`,
    backgroundColor: tokens.colorNeutralBackground1,
    borderRadius: tokens.borderRadiusXLarge,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    boxShadow: tokens.shadow4,
  },
  rootRow: { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center' },
  item: { position: 'relative', minWidth: '44px', height: '44px', padding: 0 },
  letter: {
    position: 'absolute',
    right: '3px',
    bottom: '1px',
    fontSize: tokens.fontSizeBase100,
    lineHeight: tokens.lineHeightBase100,
    color: tokens.colorNeutralForeground3,
    pointerEvents: 'none',
  },
});

export function Palette(props: { onPick: (preset: EditorPreset) => void; horizontal?: boolean }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('editor');
  return (
    <nav className={props.horizontal ? `${styles.root} ${styles.rootRow}` : styles.root} aria-label={t('palette.label')}>
      {PALETTE.map((item) => {
        const Icon = item.icon;
        const label = t(`palette.${item.preset}`);
        return (
          <Tooltip key={item.preset} content={t('palette.insert', { label, key: item.key })} relationship="description" positioning="after">
            <Button
              className={styles.item}
              appearance="subtle"
              aria-label={label}
              aria-keyshortcuts={item.key}
              icon={<Icon />}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData(PRESET_MIME, item.preset);
                e.dataTransfer.effectAllowed = 'copy';
              }}
              onClick={() => props.onPick(item.preset)}
            >
              <span className={styles.letter} aria-hidden="true">
                {item.key}
              </span>
            </Button>
          </Tooltip>
        );
      })}
    </nav>
  );
}
