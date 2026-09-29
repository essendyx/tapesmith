/** Schneidpause: Leiste mit „Weiter“, Leertaste wirkt nur während der Pause. */
import { useEffect, useState } from 'react';
import {
  Button,
  MessageBar,
  MessageBarActions,
  MessageBarBody,
  MessageBarTitle,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Cut20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { useServerEvent } from '../api/events';
import { continueCut } from '../api/labels';
import { useShortcut } from '../commands/shortcuts';

interface CutPauseEvent {
  job_key: string;
  state: 'start' | 'end';
  done: number;
  total: number;
  seconds: number;
}

const useStyles = makeStyles({
  root: { padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalXL} 0` },
  count: { fontVariantNumeric: 'tabular-nums' },
});

export function CutPauseBar(): JSX.Element | null {
  const styles = useStyles();
  const { t } = useTranslation('shell');
  const [pause, setPause] = useState<(CutPauseEvent & { until: number | null }) | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useServerEvent<CutPauseEvent>('cut_pause', (e) => {
    if (e.state === 'start') setPause({ ...e, until: e.seconds > 0 ? Date.now() + e.seconds * 1000 : null });
    else setPause((p) => (p && p.job_key !== e.job_key ? p : null));
  });
  useServerEvent<{ job_key: string; phase: string }>('job', (e) => {
    if (e.phase === 'fertig') setPause((p) => (p && p.job_key === e.job_key ? null : p));
  });

  const until = pause?.until ?? null;
  useEffect(() => {
    if (until === null) return undefined;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(timer);
  }, [until]);

  const next = () => {
    void continueCut().catch(() => undefined);
    setPause(null);
  };
  useShortcut('Space', next, { enabled: pause !== null });

  if (!pause) return null;
  const remaining = until !== null ? Math.max(0, Math.ceil((until - now) / 1000)) : null;

  return (
    <div className={styles.root}>
      <MessageBar intent="info" icon={<Cut20Regular />} layout="multiline" data-testid="cut-pause" aria-live="polite">
        <MessageBarBody>
          <MessageBarTitle>{t('cutPause.title', { done: pause.done, total: pause.total })}</MessageBarTitle>
          {remaining !== null ? (
            <span className={styles.count}>{t('cutPause.countdown', { seconds: remaining })}</span>
          ) : (
            t('cutPause.hint')
          )}
        </MessageBarBody>
        <MessageBarActions>
          <Button appearance="primary" size="small" onClick={next} aria-keyshortcuts="Space">
            {t('cutPause.next')}
          </Button>
        </MessageBarActions>
      </MessageBar>
    </div>
  );
}
