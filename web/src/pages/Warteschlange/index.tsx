/**
 * Seite „Warteschlange": Aufträge des Druckdienstes, die auf den Drucker warten.
 * Countdown läuft nur, solange die Seite angezeigt wird; keine eigene IPC-Abfrage dafür.
 * Aktualisiert sich automatisch über SSE „queue" (invalidiert der Rahmen, `api/events.tsx`).
 *
 * Aufbau nach dem gemeinsamen Listenmuster: Seitenkopf mit Zustand und den Aktionen für alle
 * Aufträge, Werkzeugleiste mit den Schaltern, darunter `DataList` mit genau einem sichtbaren
 * Hauptknopf je Zeile („Jetzt versuchen“) und den übrigen Aktionen im „Mehr“-Menü.
 */
import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Badge, Button, Caption1, Switch, makeStyles, tokens, type BadgeProps } from '@fluentui/react-components';
import {
  ArrowDown20Regular,
  ArrowSync20Regular,
  ArrowUp20Regular,
  CheckmarkCircle20Regular,
  Copy20Regular,
  Dismiss20Regular,
  DismissCircle20Regular,
  Pause20Regular,
  Play20Regular,
  Warning20Regular,
} from '@fluentui/react-icons';
import { apiGet, apiPost, apiPut } from '../../api/client';
import { qk } from '../../api/core';
import type { QueueJson, QueuedJobJson } from '../../api/types';
import { DataList, type ListColumn } from '../../components/DataList';
import { EmptyState } from '../../components/EmptyState';
import { ListToolbar } from '../../components/ListToolbar';
import { PageHeader } from '../../components/PageHeader';
import { RowActions } from '../../components/RowActions';
import { useConfirm } from '../../components/ConfirmProvider';
import { useNotify } from '../../components/NotifyProvider';
import { translateOr } from '../../i18n';
import { displayTitle } from '../../i18n/systemTitle';
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
  statusLine: {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalXXS,
  },
  titleCell: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXXS, minWidth: 0 },
  title: { fontWeight: tokens.fontWeightSemibold, overflowWrap: 'anywhere' },
  sensitive: { color: tokens.colorNeutralForeground3 },
  error: { color: tokens.colorPaletteRedForeground1 },
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
  const titleOf = (job: QueuedJobJson): string => displayTitle(job.title);

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
      message: t('confirm.cancelMessage', { title: titleOf(job) }),
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
  const active = (job: QueuedJobJson): boolean => job.state === 'wartet' || job.state === 'läuft'; // i18n-ignore (Server-Werte)
  const activeCount = jobs.filter(active).length;

  const columns: ListColumn<QueuedJobJson>[] = [
    {
      id: 'position',
      header: t('columns.position'),
      kind: 'number',
      hideInCard: true,
      cell: (job) => (active(job) ? job.position + 1 : ''),
    },
    {
      id: 'title',
      header: t('columns.title'),
      kind: 'title',
      cell: (job) => (
        <div className={styles.titleCell}>
          <span className={styles.title}>{titleOf(job)}</span>
          {job.sensitive ? <Caption1 className={styles.sensitive}>{t('job.sensitiveShort')}</Caption1> : null}
          {job.last_error ? <Caption1 className={styles.error}>{job.last_error}</Caption1> : null}
        </div>
      ),
    },
    { id: 'source', header: t('columns.source'), cell: (job) => <Badge appearance="outline">{sourceLabel(job.source)}</Badge> },
    { id: 'attempts', header: t('columns.attempts'), kind: 'number', cell: (job) => job.attempts },
    {
      id: 'next',
      header: t('columns.nextTry'),
      cell: (job) => (job.state === 'wartet' && !data?.paused ? countdownText(job.next_try) : ''),
    },
    {
      id: 'state',
      header: t('columns.state'),
      kind: 'status',
      cell: (job) => (
        <Badge color={STATE_COLOR[job.state] ?? 'informative'} appearance="tint" icon={STATE_ICON[job.state]}>
          {stateLabel(job.state)}
        </Badge>
      ),
    },
    {
      id: 'actions',
      header: t('columns.actions'),
      kind: 'actions',
      cell: (job) => (
        <RowActions
          title={titleOf(job)}
          primary={
            job.state === 'wartet' ? (
              <Button
                icon={<ArrowSync20Regular />}
                aria-label={t('actions.for', { action: t('actions.retry'), title: titleOf(job) })}
                onClick={() => void retry(job)}
              >
                {t('actions.retry')}
              </Button>
            ) : undefined
          }
          actions={[
            {
              key: 'up',
              label: t('actions.up'),
              icon: <ArrowUp20Regular />,
              hidden: !active(job),
              disabled: job.position <= 0,
              onClick: () => void move(job, -1),
            },
            {
              key: 'down',
              label: t('actions.down'),
              icon: <ArrowDown20Regular />,
              hidden: !active(job),
              disabled: job.position >= activeCount - 1,
              onClick: () => void move(job, 1),
            },
            { key: 'duplicate', label: t('actions.duplicate'), icon: <Copy20Regular />, onClick: () => void duplicate(job) },
            {
              key: 'cancel',
              label: t('actions.cancelJob'),
              icon: <Dismiss20Regular />,
              danger: true,
              hidden: !active(job),
              onClick: () => void cancel(job),
            },
          ]}
        />
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title={t('title')}
        subtitle={
          <span className={styles.statusLine}>
            <Badge color={data?.paused ? 'subtle' : 'success'} appearance="tint">
              {data?.paused ? t('status.paused') : t('status.active')}
            </Badge>
            <span>{t('probe.label', { value: probeLabel(data?.probe) })}</span>
            {data && waitingCount > 0 && !data.paused && data.auto_retry ? (
              <span>{t('nextTry', { countdown: countdownText(data.next_try) })}</span>
            ) : null}
            {data?.waiting_reason ? <span>{data.waiting_reason}</span> : null}
          </span>
        }
        actions={
          <>
            <Button appearance="primary" icon={<ArrowSync20Regular />} disabled={waitingCount === 0} onClick={() => void retryAll()}>
              {t('actions.retryAll')}
            </Button>
            <Button icon={data?.paused ? <Play20Regular /> : <Pause20Regular />} onClick={() => void togglePause()}>
              {data?.paused ? t('actions.resume') : t('actions.pause')}
            </Button>
          </>
        }
      />

      <ListToolbar>
        <Switch
          label={t('autoRetry')}
          checked={data?.auto_retry ?? true}
          onChange={(_e, d) => void setAutoRetry(d.checked)}
        />
        <Switch label={t('actions.showDone')} checked={includeDone} onChange={(_e, d) => setIncludeDone(d.checked)} />
      </ListToolbar>

      <DataList
        items={jobs}
        columns={columns}
        getKey={(job) => job.id}
        label={t('listLabel')}
        loading={queueQuery.isLoading}
        error={queueQuery.error}
        onRetry={() => void queueQuery.refetch()}
        empty={<EmptyState title={t('empty.title')} body={t('empty.body')} />}
      />
    </>
  );
}
