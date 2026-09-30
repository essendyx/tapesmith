/** Karte „Updates“: Version, Quelle, letzte Prüfung, verfügbares Update, Installieren, Rückstellung. */
import { useEffect, useState, type ReactElement } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Body1, Button, Caption1, MessageBar, MessageBarBody, Spinner, makeStyles, tokens } from '@fluentui/react-components';
import {
  ArrowDownload20Regular,
  ArrowSync20Regular,
  ArrowUndo20Regular,
  CheckmarkCircle20Regular,
  ErrorCircle20Regular,
} from '@fluentui/react-icons';
import { Section } from '../../../components/Section';
import { ErrorMessage } from '../../../components/ErrorMessage';
import { LoadingState } from '../../../components/LoadingState';
import { useConfirm } from '../../../components/ConfirmProvider';
import { useNotify } from '../../../components/NotifyProvider';
import { ApiError } from '../../../api/client';
import {
  UPDATE_BUSY_STATES,
  UPDATE_QUERY_KEY,
  checkUpdate,
  installUpdate,
  rollbackUpdate,
  useUpdateStatus,
  type UpdateState,
  type UpdateStatus,
} from '../../../api/update';
import { useFormat } from '../../../i18n/format';
import { useLayoutStyles } from '../../../theme/layout';
import { FieldRow, FieldRows } from '../../../components/FieldRow';

type Action = 'check' | 'install' | 'rollback';

const useStyles = makeStyles({
  state: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalS },
  ok: { color: tokens.colorPaletteGreenForeground1 },
  failed: { color: tokens.colorPaletteRedForeground1 },
  notes: { whiteSpace: 'pre-wrap', margin: 0, color: tokens.colorNeutralForeground2 },
  errors: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS },
});

function StateIcon(props: { state: UpdateState }): ReactElement {
  const styles = useStyles();
  if (UPDATE_BUSY_STATES.includes(props.state)) return <Spinner size="extra-tiny" aria-hidden="true" />;
  if (props.state === 'failed') return <ErrorCircle20Regular aria-hidden="true" className={styles.failed} />;
  if (props.state === 'ready') return <ArrowDownload20Regular aria-hidden="true" />;
  return <CheckmarkCircle20Regular aria-hidden="true" className={styles.ok} />;
}

/** Nach dem Start höchstens so lange nachfragen und sperren, auch wenn der Dienst schweigt. */
const START_WATCH_MS = 120_000;

interface StartMark {
  at: number;
  /** Fehler vor dem Start (Schlüssel), damit ein alter Fehler das Nachfragen nicht beendet. */
  error: string;
  /** Seit dem Start schon einen anderen Zustand als „failed“ gesehen. */
  sawOther: boolean;
}

function errorKey(status: UpdateStatus | undefined): string {
  return status?.error ? `${status.error.code}|${status.error.message}` : '';
}

function statusError(status: UpdateStatus): ApiError | null {
  if (!status.error) return null;
  return new ApiError(0, 'UpdateError', status.error.message, '', 1, null, status.error.code);
}

export function UpdateCard(): JSX.Element {
  const { t } = useTranslation('update');
  const styles = useStyles();
  const layout = useLayoutStyles();
  const { formatRelative } = useFormat();
  const client = useQueryClient();
  const confirm = useConfirm();
  const notify = useNotify();
  const location = useLocation();
  const [running, setRunning] = useState<Action | null>(null);
  // Nach dem Start einer Installation bzw. Rückstellung: weiter nachfragen und die Knöpfe sperren, bis
  // der Dienst „installing“ oder „failed“ meldet (er bereitet das Update im Hintergrund vor und meldet
  // direkt nach 202 oft noch den alten Zustand).
  const [start, setStart] = useState<StartMark | null>(null);
  const started = start !== null;
  const query = useUpdateStatus({ poll: started });
  const latest = query.data;
  const reportedAt = query.dataUpdatedAt;
  useEffect(() => {
    if (!start || !latest || reportedAt <= start.at) return;
    if (latest.state !== 'failed') {
      if (latest.state === 'installing') setStart(null);
      else if (!start.sawOther) setStart({ ...start, sawOther: true });
      return;
    }
    // Ein Fehler zählt erst, wenn er neu ist (nicht der alte Zustand von vor dem Start).
    if (start.sawOther || errorKey(latest) !== start.error) setStart(null);
  }, [start, latest, reportedAt]);
  const startAt = start?.at ?? null;
  useEffect(() => {
    if (startAt === null) return undefined;
    const timer = setTimeout(() => setStart(null), START_WATCH_MS);
    return () => clearTimeout(timer);
  }, [startAt]);
  const [actionError, setActionError] = useState<{ action: Action; error: unknown } | null>(null);

  const refresh = () => client.invalidateQueries({ queryKey: UPDATE_QUERY_KEY });

  const onCheck = async () => {
    setRunning('check');
    setActionError(null);
    try {
      const status = await checkUpdate();
      client.setQueryData(UPDATE_QUERY_KEY, status);
    } catch (err) {
      setActionError({ action: 'check', error: err });
      await refresh();
    } finally {
      setRunning(null);
    }
  };

  const onInstall = async (version: string) => {
    const ok = await confirm({
      title: t('confirm.installTitle', { version }),
      message: t('confirm.installMessage'),
      confirmText: t('confirm.installConfirm'),
      cancelText: t('common:actions.cancel'),
    });
    if (!ok) return;
    setRunning('install');
    setActionError(null);
    try {
      await installUpdate(version, location.pathname + location.search);
      setStart({ at: Date.now(), error: errorKey(query.data), sawOther: false });
      notify({ intent: 'info', title: t('notify.installStarted') });
      await refresh();
    } catch (err) {
      setActionError({ action: 'install', error: err });
    } finally {
      setRunning(null);
    }
  };

  const onRollback = async (previous: string) => {
    const ok = await confirm({
      title: t('confirm.rollbackTitle', { version: previous }),
      message: t('confirm.rollbackMessage'),
      confirmText: t('confirm.rollbackConfirm'),
      cancelText: t('common:actions.cancel'),
    });
    if (!ok) return;
    setRunning('rollback');
    setActionError(null);
    try {
      await rollbackUpdate(location.pathname + location.search);
      setStart({ at: Date.now(), error: errorKey(query.data), sawOther: false });
      notify({ intent: 'info', title: t('notify.rollbackStarted') });
      await refresh();
    } catch (err) {
      setActionError({ action: 'rollback', error: err });
    } finally {
      setRunning(null);
    }
  };

  const data = query.data;
  const serverBusy = started || (data ? UPDATE_BUSY_STATES.includes(data.state) : false);
  const checkButton = (
    <Button
      appearance="secondary"
      icon={running === 'check' ? <Spinner size="tiny" /> : <ArrowSync20Regular />}
      disabled={running !== null || serverBusy}
      aria-busy={running === 'check' || undefined}
      onClick={() => void onCheck()}
    >
      {t('actions.check')}
    </Button>
  );

  let body: ReactElement;
  if (query.isLoading) {
    body = <LoadingState variant="section" rows={3} />;
  } else if (query.isError || !data) {
    body = <ErrorMessage error={query.error} onRetry={() => void query.refetch()} />;
  } else {
    const error = statusError(data);
    body = (
      <>
        {data.installed ? null : (
          <MessageBar intent="info">
            <MessageBarBody>{t('notInstalled')}</MessageBarBody>
          </MessageBar>
        )}
        <FieldRows>
          <FieldRow
            label={t(data.installed ? 'info.version' : 'info.versionPortable', { version: data.current })}
            help={`${t('info.source', { source: data.source })} · ${t('info.channel', { channel: t(`channel.${data.channel}`) })}`}
            details={
              <>
                <Caption1 className={layout.muted}>
                  {data.last_check ? t('info.lastCheck', { when: formatRelative(data.last_check) }) : t('info.neverChecked')}
                </Caption1>
                {data.installed ? (
                  <Caption1 className={layout.muted}>{t(data.auto_install ? 'info.autoOn' : 'info.autoOff')}</Caption1>
                ) : null}
              </>
            }
            control={
              <div className={styles.state} role="status" aria-live="polite">
                <StateIcon state={data.state} />
                <Body1>{t(`state.${data.state}`)}</Body1>
              </div>
            }
          />
          {data.available ? (
            <FieldRow
              labelAs="h3"
              label={t('available.title', { version: data.available.version })}
              details={data.available.notes ? <p className={styles.notes}>{data.available.notes}</p> : undefined}
              control={
                data.installed ? (
                  <Button
                    appearance="primary"
                    icon={running === 'install' ? <Spinner size="tiny" /> : <ArrowDownload20Regular />}
                    disabled={running !== null || serverBusy}
                    aria-busy={running === 'install' || undefined}
                    onClick={() => void onInstall(data.available?.version ?? '')}
                  >
                    {t('actions.install')}
                  </Button>
                ) : undefined
              }
            />
          ) : data.last_check && data.state !== 'failed' ? (
            <FieldRow label={t('available.none')} />
          ) : null}
          {data.installed && data.can_rollback && data.previous ? (
            <FieldRow
              label={t('rollback.label', { version: data.previous })}
              help={t('rollback.help')}
              control={
                <Button
                  appearance="secondary"
                  icon={running === 'rollback' ? <Spinner size="tiny" /> : <ArrowUndo20Regular />}
                  disabled={running !== null || serverBusy}
                  aria-busy={running === 'rollback' || undefined}
                  onClick={() => void onRollback(data.previous ?? '')}
                >
                  {t('actions.rollback')}
                </Button>
              }
            />
          ) : null}
        </FieldRows>

        {error || actionError ? (
          <div className={styles.errors}>
            {error ? <ErrorMessage error={error} /> : null}
            {actionError ? <ErrorMessage error={actionError.error} title={t(`errors.${actionError.action}`)} /> : null}
          </div>
        ) : null}
      </>
    );
  }

  return (
    <Section id="updates" title={t('title')} description={t('description')} actions={checkButton}>
      {body}
    </Section>
  );
}
