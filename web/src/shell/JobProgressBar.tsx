/** Druckfortschritt: dünne Leiste oben, solange ein Auftrag läuft; Esc bricht ab. */
import { useState } from 'react';
import { Button, ProgressBar, makeStyles, tokens } from '@fluentui/react-components';
import { Dismiss16Regular, Print20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { useServerEvent } from '../api/events';
import { cancelPrint } from '../api/labels';
import { useShortcut } from '../commands/shortcuts';
import { motion } from '../theme/motion';

interface JobEvent {
  job_key: string;
  phase: 'angenommen' | 'läuft' | 'fertig'; // i18n-ignore (Server-Werte)
  status?: string;
  source?: string;
  title?: string;
  queue_id?: number | null;
}

interface ProgressEvent {
  job_key: string;
  done: number;
  total: number;
}

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    backgroundColor: tokens.colorNeutralBackground1,
    borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    ...motion.fadeIn,
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    columnGap: tokens.spacingHorizontalM,
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalXL}`,
    fontSize: tokens.fontSizeBase300,
  },
  icon: { color: tokens.colorBrandForeground1, flexShrink: 0 },
  text: { flexGrow: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  percent: { fontVariantNumeric: 'tabular-nums', color: tokens.colorNeutralForeground2 },
});

export function JobProgressBar(): JSX.Element | null {
  const styles = useStyles();
  const { t } = useTranslation('shell');
  const [job, setJob] = useState<{ key: string; title: string } | null>(null);
  const [progress, setProgress] = useState<{ key: string; done: number; total: number } | null>(null);

  useServerEvent<JobEvent>('job', (e) => {
    if (e.phase === 'läuft') { // i18n-ignore (Server-Wert)
      setJob({ key: e.job_key, title: e.title ?? '' });
      setProgress((p) => (p && p.key === e.job_key ? p : null));
    } else if (e.phase === 'fertig') {
      setJob((j) => (j && j.key !== e.job_key ? j : null));
      setProgress((p) => (p && p.key !== e.job_key ? p : null));
    }
  });
  useServerEvent<ProgressEvent>('progress', (e) => {
    setProgress({ key: e.job_key, done: e.done, total: e.total });
  });

  const visible = job !== null;
  const cancel = () => {
    if (job) void cancelPrint(job.key).catch(() => undefined);
  };
  useShortcut('Escape', cancel, { enabled: visible });

  if (!job) return null;
  const current = progress && progress.key === job.key && progress.total > 0 ? progress : null;
  const fraction = current ? Math.min(1, Math.max(0, current.done / current.total)) : undefined;
  const percent = fraction !== undefined ? Math.round(fraction * 100) : null;
  const key = `progress.printing${job.title ? 'Titled' : ''}${percent !== null ? 'Percent' : ''}`;
  const label = t(key, { title: job.title, percent });

  return (
    <div className={styles.root} role="status" aria-live="polite" data-testid="job-progress">
      <ProgressBar
        thickness="medium"
        value={percent ?? undefined}
        max={100}
        aria-label={t('progress.label')}
        aria-valuetext={percent !== null ? `${percent} %` : undefined}
        shape="square"
      />
      <div className={styles.row}>
        <Print20Regular className={styles.icon} aria-hidden="true" />
        <span className={styles.text}>{label}</span>
        <Button size="small" appearance="subtle" icon={<Dismiss16Regular />} onClick={cancel} aria-keyshortcuts="Escape">
          {t('progress.cancel')}
        </Button>
      </div>
    </div>
  );
}
