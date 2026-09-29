/** Verlauf: alle Schritte, aktueller markiert, Klick springt. */
import { Button, makeStyles, mergeClasses, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';

const useStyles = makeStyles({
  list: { listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXXS },
  item: { width: '100%', justifyContent: 'flex-start', fontWeight: tokens.fontWeightRegular },
  current: { backgroundColor: tokens.colorBrandBackground2, fontWeight: tokens.fontWeightSemibold },
  future: { color: tokens.colorNeutralForeground4 },
});

export function HistoryPanel(props: { labels: string[]; index: number; onJump: (i: number) => void }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('editor');
  return (
    <ul className={styles.list} aria-label={t('history.label')}>
      {props.labels.map((label, i) => (
        <li key={`${i}-${label}`}>
          <Button
            appearance="subtle"
            className={mergeClasses(styles.item, i === props.index && styles.current, i > props.index && styles.future)}
            aria-current={i === props.index ? 'step' : undefined}
            onClick={() => props.onJump(i)}
          >
            {label}
          </Button>
        </li>
      ))}
    </ul>
  );
}
