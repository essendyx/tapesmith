/**
 * Hinweis auf verwaiste Entwürfe und Lebenszeichen der Oberfläche.
 * Beim Start, danach alle 30 s und beim Verlassen des Editors `listDrafts()`; gibt es verwaiste
 * Entwürfe und ist die Seite nicht der Editor, erscheint eine MessageBar mit „Im Editor
 * wiederherstellen“ und „Später“. Das Lebenszeichen geht sofort und dann alle 30 Sekunden an den
 * Dienst; Fehler bleiben still.
 */
import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  Button,
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  MessageBarTitle,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { DocumentArrowUp20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { heartbeat, listDrafts } from '../api/drafts';
import { motion } from '../theme/motion';

export const HEARTBEAT_MS = 30_000;
export const RESTORE_ROUTE = '/editor?wiederherstellen=1';

const useStyles = makeStyles({
  root: {
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalXL} 0`,
    ...motion.slideUp,
  },
});

/** Sendet sofort und dann alle 30 s ein Lebenszeichen, solange die Hülle offen ist. */
export function useHeartbeat(): void {
  useEffect(() => {
    const beat = () => {
      void heartbeat().catch(() => undefined);
    };
    beat();
    const timer = setInterval(beat, HEARTBEAT_MS);
    return () => clearInterval(timer);
  }, []);
}

export function RecoveryBanner(): JSX.Element | null {
  const styles = useStyles();
  const { t } = useTranslation('shell');
  const location = useLocation();
  const navigate = useNavigate();
  const [count, setCount] = useState(0);
  const [dismissed, setDismissed] = useState(false);

  const [tick, setTick] = useState(0);
  const onEditor = location.pathname === '/editor' || location.pathname.startsWith('/editor/');

  useHeartbeat();

  // Neu abfragen: alle 30 s (Entwürfe eines eben beendeten Fensters gelten erst nach 90 s ohne
  // Lebenszeichen als verwaist) und beim Verlassen des Editors (dort evtl. schon wiederhergestellt).
  useEffect(() => {
    const timer = setInterval(() => setTick((n) => n + 1), HEARTBEAT_MS);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (dismissed || onEditor) return undefined;
    const controller = new AbortController();
    listDrafts(controller.signal).then(
      (res) => {
        if (!controller.signal.aborted) setCount(res.orphaned?.length ?? 0);
      },
      () => undefined,
    );
    return () => controller.abort();
  }, [dismissed, onEditor, tick]);

  if (dismissed || count === 0 || onEditor) return null;

  return (
    <div className={styles.root}>
      <MessageBar intent="info" layout="multiline" icon={<DocumentArrowUp20Regular />} data-testid="recovery-banner">
        <MessageBarBody>
          <MessageBarTitle>{t('recovery.title', { count })}</MessageBarTitle>
          {t('recovery.body')}
        </MessageBarBody>
        <MessageBarActions>
          <Button
            appearance="primary"
            size="small"
            onClick={() => {
              setDismissed(true);
              navigate(RESTORE_ROUTE);
            }}
          >
            {t('recovery.restore')}
          </Button>
          <Button appearance="secondary" size="small" onClick={() => setDismissed(true)}>
            {t('recovery.later')}
          </Button>
        </MessageBarActions>
      </MessageBar>
    </div>
  );
}
