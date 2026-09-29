/** Karte „Telegram“: Meldungen, Ruhezeiten, Token, Testnachricht. */
import { useState } from 'react';
import {
  Body1,
  Body1Strong,
  Button,
  Checkbox,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  Spinner,
  SpinButton,
  Switch,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { Section } from '../../components/Section';
import { useNotify } from '../../components/NotifyProvider';
import { ApiError } from '../../api/client';
import { SecretDialog } from './SecretDialog';
import { telegramTest } from './api';
import type { AccessJson, AccessTelegram } from './types';
import { useSectionEdit } from './useSectionEdit';
import { useAccessSave } from './useAccessSave';

const useStyles = makeStyles({
  grid: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  row: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalS, flexWrap: 'wrap', rowGap: tokens.spacingVerticalXS },
  // Lange Pfade (Secret-Referenzen) umbrechen statt die Karte auf dem Handy zu sprengen.
  wrap: { overflowWrap: 'anywhere', minWidth: 0 },
  switches: { display: 'flex', flexDirection: 'column' },
  // Eigene Gruppe statt Fluent-`Field`: mehrere Bedienelemente dürfen nicht dieselbe generierte
  // Kennung teilen (jedes Element trägt seine eigene sichtbare Beschriftung).
  group: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXS },
});

function splitQuietHours(v: string | null): { start: string; end: string } {
  if (!v) return { start: '22:00', end: '07:00' };
  const [start, end] = v.split('-');
  return { start: start ?? '22:00', end: end ?? '07:00' };
}

export function TelegramCard(props: { data: AccessJson }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('zugriff');
  const notify = useNotify();
  const edit = useSectionEdit<AccessTelegram>(props.data.telegram);
  const { save, saving, error } = useAccessSave();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [testing, setTesting] = useState(false);
  const v = edit.values;
  const quiet = splitQuietHours(v.quiet_hours);
  const quietActive = v.quiet_hours !== null;
  const canSetToken = (v.token_ref ?? '').startsWith('keyring:');
  const secretDialogTitle = t('telegram.secretDialogTitle');

  const onSave = async () => {
    const ok = await save(edit.changes('telegram'), t('telegram.saveSuccess'));
    if (ok) edit.discard();
  };

  const runTest = async () => {
    setTesting(true);
    try {
      const r = await telegramTest();
      if (r.ok) notify({ intent: 'success', title: t('telegram.testSuccess') });
      else notify({ intent: 'error', title: t('telegram.testErrorTitle'), body: r.error ?? undefined });
    } catch (err) {
      notify({
        intent: 'error',
        title: t('telegram.testErrorTitle'),
        body: err instanceof ApiError || err instanceof Error ? err.message : String(err),
      });
    } finally {
      setTesting(false);
    }
  };

  return (
    <Section
      id="telegram"
      title={t('telegram.title')}
      actions={
        edit.dirty ? (
          <>
            <Button appearance="secondary" disabled={saving} onClick={edit.discard}>
              {t('common:actions.cancel')}
            </Button>
            <Button appearance="primary" disabled={saving} aria-busy={saving} onClick={() => void onSave()}>
              {t('common:actions.save')}
            </Button>
          </>
        ) : undefined
      }
    >
      <div className={styles.grid}>
        <Field label={t('telegram.enableLabel')}>
          <Switch checked={v.enabled} onChange={(_e, d) => edit.set('enabled', d.checked)} />
        </Field>

        <Field label={t('telegram.chatIdLabel')}>
          <Input
            value={v.chat_id === null ? '' : String(v.chat_id)}
            onChange={(_e, d) => edit.set('chat_id', d.value === '' ? null : d.value)}
          />
        </Field>

        <div className={styles.group}>
          <Body1Strong>{t('telegram.quietHoursTitle')}</Body1Strong>
          <div className={styles.row}>
            <Checkbox
              label={t('telegram.quietHoursActive')}
              checked={quietActive}
              onChange={(_e, d) => edit.set('quiet_hours', d.checked ? `${quiet.start}-${quiet.end}` : null)}
            />
            {quietActive ? (
              <>
                <Input
                  type="time"
                  aria-label={t('telegram.quietStartAria')}
                  value={quiet.start}
                  onChange={(_e, d) => edit.set('quiet_hours', `${d.value}-${quiet.end}`)}
                />
                <Input
                  type="time"
                  aria-label={t('telegram.quietEndAria')}
                  value={quiet.end}
                  onChange={(_e, d) => edit.set('quiet_hours', `${quiet.start}-${d.value}`)}
                />
              </>
            ) : (
              <Body1>{t('telegram.quietHoursNone')}</Body1>
            )}
          </div>
        </div>

        <Field label={t('telegram.offlineMinLabel')}>
          <SpinButton
            value={v.offline_min}
            min={1}
            max={1440}
            onChange={(_e, d) => {
              const n = d.value ?? (d.displayValue ? Number(d.displayValue) : null);
              if (n !== null && Number.isFinite(n)) edit.set('offline_min', Math.min(1440, Math.max(1, Math.round(n))));
            }}
          />
        </Field>

        <Field label={t('telegram.queueStuckMinLabel')}>
          <SpinButton
            value={v.queue_stuck_min}
            min={1}
            max={1440}
            onChange={(_e, d) => {
              const n = d.value ?? (d.displayValue ? Number(d.displayValue) : null);
              if (n !== null && Number.isFinite(n)) edit.set('queue_stuck_min', Math.min(1440, Math.max(1, Math.round(n))));
            }}
          />
        </Field>

        <Field label={t('telegram.rollLowLabel')}>
          <SpinButton
            value={v.roll_low_m}
            min={0}
            max={30}
            step={0.1}
            onChange={(_e, d) => {
              const n = d.value ?? (d.displayValue ? Number(d.displayValue.replace(',', '.')) : null);
              if (n !== null && Number.isFinite(n)) edit.set('roll_low_m', Math.min(30, Math.max(0, n)));
            }}
          />
        </Field>

        <div className={styles.group}>
          <Body1Strong>{t('telegram.notifyTypesTitle')}</Body1Strong>
          <div className={styles.switches}>
            <Switch label={t('telegram.notifyQueue')} checked={v.notify_queue} onChange={(_e, d) => edit.set('notify_queue', d.checked)} />
            <Switch label={t('telegram.notifyOffline')} checked={v.notify_offline} onChange={(_e, d) => edit.set('notify_offline', d.checked)} />
            <Switch label={t('telegram.notifyError')} checked={v.notify_error} onChange={(_e, d) => edit.set('notify_error', d.checked)} />
            <Switch label={t('telegram.notifyRoll')} checked={v.notify_roll} onChange={(_e, d) => edit.set('notify_roll', d.checked)} />
          </div>
        </div>

        <Field label={t('telegram.tokenLabel')}>
          <div className={styles.row}>
            <Body1 className={styles.wrap}>
              {v.token_set ? t('telegram.tokenSet') : t('telegram.tokenMissing')} ({v.token_describe})
            </Body1>
            {canSetToken ? (
              <Button appearance="secondary" onClick={() => setDialogOpen(true)}>
                {t('telegram.setToken')}
              </Button>
            ) : (
              <Body1 className={styles.wrap}>{t('telegram.tokenFromSource', { source: v.token_describe })}</Body1>
            )}
          </div>
        </Field>

        <div>
          <Button
            appearance="secondary"
            disabled={testing}
            icon={testing ? <Spinner size="tiny" /> : undefined}
            aria-busy={testing}
            onClick={() => void runTest()}
          >
            {t('telegram.sendTest')}
          </Button>
        </div>

        {error ? (
          <MessageBar intent="error">
            <MessageBarBody>{error}</MessageBarBody>
          </MessageBar>
        ) : null}
      </div>
      <SecretDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        name="telegram"
        title={secretDialogTitle}
        fieldLabel={t('telegram.secretFieldLabel')}
      />
    </Section>
  );
}
