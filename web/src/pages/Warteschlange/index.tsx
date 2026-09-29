/**
 * Seite „Warteschlange": Aufträge des Druckdienstes, die auf den Drucker warten.
 * Countdown läuft nur, solange die Seite angezeigt wird; keine eigene IPC-Abfrage dafür.
 * Aktualisiert sich automatisch über SSE „queue" (invalidiert der Rahmen, `api/events.tsx`).
 */
import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Badge, Body1, Button, Caption1, Switch, makeStyles, tokens, type BadgeProps } from '@fluentui/react-components';
import {
  ArrowSync20Regular,
  CheckmarkCircle20Regular,
  DismissCircle20Regular,
  Warning20Regular,
} from '@fluentui/react-icons';
import { apiGet, apiPost, apiPut } from '../../api/client';
import { qk } from '../../api/core';
import type { QueueJson, QueuedJobJson } from '../../api/types';
import { EmptyState } from '../../components/EmptyState';
import { PageHeader } from '../../components/PageHeader';
import { Section } from '../../components/Section';
import { useConfirm } from '../../components/ConfirmProvider';
import { useNotify } from '../../components/NotifyProvider';
import { translateOr } from '../../i18n';
import { countdownText } from '../Verlauf/time';

const STATE_COLOR: Record<string, NonNullable<BadgeProps['color']>> = {
  wartet: 'warning',
  läuft: 'informative',
  fertig: 'success',
  fehler: 'danger',
  abgebrochen: 'subtle',
};
const STATE_ICON: Record<string, JSX.Element> = {
  wartet: <Warning20Regular />, // i18n-ignore (Symbol, kein Text)
  läuft: <ArrowSync20Regular />, // i18n-ignore (Symbol, kein Text)
  fertig: <CheckmarkCircle20Regular />, // i18n-ignore (Symbol, kein Text)
  fehler: <DismissCircle20Regular />, // i18n-ignore (Symbol, kein Text)
  abgebrochen: <Warning20Regular />, // i18n-ignore (Symbol, kein Text)
};

const useStyles = makeStyles({
  header: { display: 'flex', flexWrap: 'wrap', columnGap: tokens.spacingHorizontalXL, rowGap: tokens.spacingVerticalS, alignItems: 'center' },
  headerLine: { display: 'flex', flexWrap: 'wrap', columnGap: tokens.spacingHorizontalM, alignItems: 'center', color: tokens.colorNeutralForeground3 },
  toolbar: { display: 'flex', columnGap: tokens.spacingHorizontalM, marginTop: tokens.spacingVerticalM, marginBottom: tokens.spacingVerticalL, flexWrap: 'wrap', alignItems: 'center' },
  list: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  card: {
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    columnGap: tokens.spacingHorizontalL,
    padding: tokens.spacingVerticalM,
    borderRadius: tokens.borderRadiusXLarge,
    backgroundColor: tokens.colorNeutralBackground1,
    boxShadow: tokens.shadow4,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    flexWrap: 'wrap',
  },
  body: { flexGrow: 1, minWidth: 0, display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXS },
  head: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalS, flexWrap: 'wrap' },
  meta: { display: 'flex', columnGap: tokens.spacingHorizontalS, alignItems: 'center', flexWrap: 'wrap', color: tokens.colorNeutralForeground3 },
  error: { color: tokens.colorPaletteRedForeground1 },
  actions: { display: 'flex', columnGap: tokens.spacingHorizontalXS, flexWrap: 'wrap' },
});

export default function WarteschlangePage(): JSX.Element {
  const { t } = useTranslation('warteschlange');
  const styles = useStyles();
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const notify = useNotify();
  const [includeDone, setIncludeDone] = useState(false);
  const [, setTick] = useState(0);

  const queryKey = [...qk.queue, includeDone];
  const queueQuery = useQuery({
    queryKey,
    queryFn: ({ signal }) => apiGet<QueueJson>(`/api/v1/queue?include_done=${includeDone}`, signal),
  });
  const data = queueQuery.data;
  const jobs = data?.jobs ?? [];

  useEffect(() => {
    const id = setInterval(() => setTick((tick) => tick + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const refetch = (): void => void queryClient.invalidateQueries({ queryKey: qk.queue });

  const stateLabel = (state: string): string => translateOr(`warteschlange:state.${state}`, state);
  const sourceLabel = (source: string): string => translateOr(`warteschlange:source.${source}`, source);
  const probeLabel = (probe: string | undefined): string =>
    probe ? translateOr(`warteschlange:probe.${probe}`, probe) : t('probe.unknown');

  const move = async (job: QueuedJobJson, delta: number): Promise<void> => {
    const position = Math.max(0, Math.min(jobs.length - 1, job.position + delta));
    if (position === job.position) return;
    try {
      await apiPost(`/api/v1/queue/${job.id}/move`, { position });
      refetch();
    } catch (err) {
      notify({ intent: 'error', title: t('notify.moveFailed'), body: err instanceof Error ? err.message : String(err) });
    }
  };

  const duplicate = async (job: QueuedJobJson): Promise<void> => {
    try {
      const res = await apiPost<{ id: number }>(`/api/v1/queue/${job.id}/duplicate`, {});
      refetch();
      notify({ intent: 'success', title: t('notify.duplicated', { id: job.id, newId: res.id }) });
    } catch (err) {
      notify({ intent: 'error', title: t('notify.duplicateFailed'), body: err instanceof Error ? err.message : String(err) });
    }
  };

  const retry = async (job: QueuedJobJson): Promise<void> => {
    try {
      await apiPost(`/api/v1/queue/${job.id}/retry`, {});
      refetch();
    } catch (err) {
      notify({ intent: 'error', title: t('notify.retryFailed'), body: err instanceof Error ? err.message : String(err) });
    }
  };

  const cancel = async (job: QueuedJobJson): Promise<void> => {
    const ok = await confirm({
      title: t('confirm.cancelTitle'),
      message: t('confirm.cancelMessage', { title: job.title }),
      confirmText: t('confirm.cancelConfirm'),
      danger: true,
    });
    if (!ok) return;
    try {
      await apiPost(`/api/v1/queue/${job.id}/cancel`, {});
      refetch();
    } catch (err) {
      notify({ intent: 'error', title: t('notify.cancelFailed'), body: err instanceof Error ? err.message : String(err) });
    }
  };

  const retryAll = async (): Promise<void> => {
    try {
      await apiPost('/api/v1/queue/retry-all', {});
      refetch();
    } catch (err) {
      notify({ intent: 'error', title: t('notify.actionFailed'), body: err instanceof Error ? err.message : String(err) });
    }
  };

  const togglePause = async (): Promise<void> => {
    try {
      await apiPost(data?.paused ? '/api/v1/queue/resume' : '/api/v1/queue/pause', {});
      refetch();
    } catch (err) {
      notify({ intent: 'error', title: t('notify.actionFailed'), body: err instanceof Error ? err.message : String(err) });
    }
  };

  const setAutoRetry = async (on: boolean): Promise<void> => {
    try {
      const next = await apiPut<QueueJson>('/api/v1/queue/auto-retry', { on });
      queryClient.setQueryData(queryKey, next);
    } catch (err) {
      notify({ intent: 'error', title: t('notify.autoRetryFailed'), body: err instanceof Error ? err.message : String(err) });
    }
  };

  const waitingCount = jobs.filter((j) => j.state === 'wartet').length;

  return (
    <>
      <PageHeader title={t('title')} />
      <Section>
        <div className={styles.header}>
          <Badge size="large" color={data?.paused ? 'subtle' : 'success'} appearance="tint">
            {data?.paused ? t('status.paused') : t('status.active')}
          </Badge>
          <Switch
            label={t('autoRetry')}
            checked={data?.auto_retry ?? true}
            onChange={(_e, d) => void setAutoRetry(d.checked)}
          />
        </div>
        <div className={styles.headerLine}>
          <Caption1>{t('probe.label', { value: probeLabel(data?.probe) })}</Caption1>
          {data && waitingCount > 0 && !data.paused && data.auto_retry ? (
            <Caption1>{t('nextTry', { countdown: countdownText(data.next_try) })}</Caption1>
          ) : null}
          {data?.waiting_reason ? <Caption1>{data.waiting_reason}</Caption1> : null}
        </div>
      </Section>

      <div className={styles.toolbar}>
        <Button appearance="secondary" onClick={() => void togglePause()}>
          {data?.paused ? t('actions.resume') : t('actions.pause')}
        </Button>
        <Button appearance="secondary" onClick={() => void retryAll()}>
          {t('actions.retryAll')}
        </Button>
        <Switch label={t('actions.showDone')} checked={includeDone} onChange={(_e, d) => setIncludeDone(d.checked)} />
      </div>

      {jobs.length === 0 ? (
        <EmptyState title={t('empty.title')} body={t('empty.body')} />
      ) : (
        <div className={styles.list}>
          {jobs.map((job) => (
            <article key={job.id} className={styles.card}>
              <div className={styles.body}>
                <div className={styles.head}>
                  <Body1>
                    <strong>{job.title}</strong>
                    {job.sensitive ? t('job.sensitive') : ''}
                  </Body1>
                  <Badge color={STATE_COLOR[job.state] ?? 'informative'} appearance="tint" icon={STATE_ICON[job.state]}>
                    {stateLabel(job.state)}
                  </Badge>
                </div>
                <div className={styles.meta}>
                  <Badge appearance="outline">{sourceLabel(job.source)}</Badge>
                  <Caption1>{t('job.attempts', { count: job.attempts })}</Caption1>
                  {job.state === 'wartet' && !data?.paused ? (
                    <Caption1>{t('nextTry', { countdown: countdownText(job.next_try) })}</Caption1>
                  ) : null}
                </div>
                {job.last_error ? <Caption1 className={styles.error}>{job.last_error}</Caption1> : null}
              </div>
              <div className={styles.actions}>
                <Button appearance="secondary" onClick={() => void move(job, -1)}>
                  {t('actions.up')}
                </Button>
                <Button appearance="secondary" onClick={() => void move(job, 1)}>
                  {t('actions.down')}
                </Button>
                <Button appearance="secondary" onClick={() => void duplicate(job)}>
                  {t('actions.duplicate')}
                </Button>
                <Button appearance="secondary" onClick={() => void retry(job)}>
                  {t('actions.retry')}
                </Button>
                <Button appearance="secondary" onClick={() => void cancel(job)}>
                  {t('common:actions.cancel')}
                </Button>
              </div>
            </article>
          ))}
        </div>
      )}
    </>
  );
}
