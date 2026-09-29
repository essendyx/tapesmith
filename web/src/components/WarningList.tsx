import { makeStyles, MessageBar, MessageBarBody, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS, margin: 0, padding: 0, listStyleType: 'none' },
  item: { margin: 0, padding: 0 },
});

type Level = 'error' | 'warning' | 'info';

const PREFIX_KEY: Record<Level, string> = { error: 'warnings.error', warning: 'warnings.warning', info: 'warnings.note' };

/**
 * Fehler, Warnungen und Hinweise als Fluent-MessageBars in einer Liste: Symbol der Stufe plus
 * unsichtbarer Stufentext für Screenreader (Text statt nur Farbe). Die Texte selbst kommen vom Server.
 */
export function WarningList(props: { errors?: string[]; warnings?: string[]; notes?: string[] }): JSX.Element | null {
  const styles = useStyles();
  const { t } = useTranslation('components');
  const items: { intent: Level; text: string }[] = [
    ...(props.errors ?? []).map((text) => ({ intent: 'error' as const, text })),
    ...(props.warnings ?? []).map((text) => ({ intent: 'warning' as const, text })),
    ...(props.notes ?? []).map((text) => ({ intent: 'info' as const, text })),
  ];
  if (items.length === 0) return null;
  return (
    <ul className={styles.root} role="list" aria-label={t('warnings.label')}>
      {items.map((item, i) => (
        <li key={`${item.intent}-${i}`} className={styles.item}>
          <MessageBar intent={item.intent} layout="multiline" data-level={item.intent}>
            <MessageBarBody>
              <span className="p12-visually-hidden">{t('warnings.prefixed', { prefix: t(PREFIX_KEY[item.intent]) })}</span>
              {item.text}
            </MessageBarBody>
          </MessageBar>
        </li>
      ))}
    </ul>
  );
}
