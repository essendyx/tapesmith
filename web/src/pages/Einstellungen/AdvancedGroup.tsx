/**
 * Abschnitt „Erweitert“ am Ende der Einstellungsseite: eingeklappt, bis man ihn öffnet. Den Zustand
 * merkt sich die Seite je Browser (`sectionIds.readAdvancedOpen`), ein Deep-Link `?abschnitt=` auf
 * eine Karte darin öffnet ihn automatisch.
 */
import type { ReactNode } from 'react';
import { Button, makeStyles, tokens } from '@fluentui/react-components';
import { ChevronDown20Regular, ChevronUp20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { Section } from '../../components/Section';
import { ADVANCED_ID } from './sectionIds';

const useStyles = makeStyles({
  content: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalL, minWidth: 0 },
});

export function AdvancedGroup(props: { open: boolean; onToggle: (open: boolean) => void; children: ReactNode }): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const styles = useStyles();
  const contentId = `${ADVANCED_ID}-inhalt`;
  return (
    <>
      <div id={ADVANCED_ID}>
        <Section
          title={t('advanced.title')}
          description={t('advanced.description')}
          actions={
            <Button
              appearance="secondary"
              icon={props.open ? <ChevronUp20Regular /> : <ChevronDown20Regular />}
              iconPosition="after"
              aria-expanded={props.open}
              aria-controls={props.open ? contentId : undefined}
              onClick={() => props.onToggle(!props.open)}
            >
              {props.open ? t('advanced.hide') : t('advanced.show')}
            </Button>
          }
        />
      </div>
      {props.open ? (
        <div id={contentId} className={styles.content}>
          {props.children}
        </div>
      ) : null}
    </>
  );
}
