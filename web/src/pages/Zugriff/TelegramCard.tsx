/** Karte „Telegram“: Meldungen, Schwellen, Ruhezeiten, Token, Testnachricht. */
import { useId, useState } from 'react';
import { Badge, Button, Input, MessageBar, MessageBarBody, Spinner } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { FieldRow, FieldRows, ToggleControl } from '../../components/FieldRow';
import { Section } from '../../components/Section';
import { useNotify } from '../../components/NotifyProvider';
import { ApiError } from '../../api/client';
import { CardActions } from './CardActions';
import { NumberInput } from './NumberInput';
import { SecretDialog } from './SecretDialog';
import { telegramTest } from './api';
import type { AccessJson, AccessTelegram } from './types';
import { useSectionEdit } from './useSectionEdit';
import { useAccessSave } from './useAccessSave';

function splitQuietHours(v: string | null): { start: string; end: string } {
  if (!v) return { start: '22:00', end: '07:00' };
  const [start, end] = v.split('-');
  return { start: start ?? '22:00', end: end ?? '07:00' };
}

type NotifyKey = 'notify_error' | 'notify_offline' | 'notify_queue' | 'notify_roll';

export function TelegramCard(props: { data: AccessJson }): JSX.Element {
  const { t } = useTranslation('zugriff');
  const notify = useNotify();
  const edit = useSectionEdit<AccessTelegram>(props.data.telegram);
  const { save, saving, error } = useAccessSave();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [testing, setTesting] = useState(false);
  const idBase = useId();
  const v = edit.values;
  const quiet = splitQuietHours(v.quiet_hours);
  const quietActive = v.quiet_hours !== null;
  const canSetToken = (v.token_ref ?? '').startsWith('keyring:');
  const title = t('telegram.title');

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

  const toggleRow = (key: NotifyKey, label: string, help: string) => (
    <FieldRow
      htmlFor={`${idBase}-${key}`}
      label={label}
      help={help}
      align="end"
      control={<ToggleControl id={`${idBase}-${key}`} checked={v[key]} onChange={(on) => edit.set(key, on)} />}
    />
  );

  return (
    <Section
      id="telegram"
      title={title}
      actions={
        <CardActions title={title} dirty={edit.dirty} saving={saving} onSave={() => void onSave()} onDiscard={edit.discard}>
          <Button
            appearance="secondary"
            disabled={testing}
            icon={testing ? <Spinner size="tiny" /> : undefined}
            aria-busy={testing}
            onClick={() => void runTest()}
          >
            {t('telegram.sendTest')}
          </Button>
        </CardActions>
      }
    >
      <FieldRows>
        <FieldRow
          htmlFor={`${idBase}-enabled`}
          label={t('telegram.enableLabel')}
          help={t('telegram.enableHint')}
          align="end"
          control={<ToggleControl id={`${idBase}-enabled`} checked={v.enabled} onChange={(on) => edit.set('enabled', on)} />}
        />
        <FieldRow
          label={t('telegram.tokenLabel')}
          badges={
            <Badge appearance="tint" size="small" color={v.token_set ? 'success' : 'warning'}>
              {v.token_set ? t('telegram.tokenSet') : t('telegram.tokenMissing')}
            </Badge>
          }
          help={
            canSetToken
              ? t('secret.storage', { source: v.token_describe })
              : v.token_ref
                ? t('telegram.tokenFromSource', { source: v.token_describe })
                : t('telegram.tokenNoSource')
          }
          control={
            canSetToken ? (
              <Button appearance="secondary" onClick={() => setDialogOpen(true)}>
                {t('telegram.setToken')}
              </Button>
            ) : undefined
          }
        />
        <FieldRow
          htmlFor={`${idBase}-chat`}
          label={t('telegram.chatIdLabel')}
          help={t('telegram.chatIdHint')}
          control={
            <Input
              id={`${idBase}-chat`}
              value={v.chat_id === null ? '' : String(v.chat_id)}
              placeholder={t('einstellungen:field.notSet')}
              onChange={(_e, d) => edit.set('chat_id', d.value === '' ? null : d.value)}
            />
          }
        />

        <FieldRow labelAs="h3" label={t('telegram.notifyTypesTitle')} help={t('telegram.notifyTypesHint')} />
        {toggleRow('notify_error', t('telegram.notifyError'), t('telegram.notifyErrorHint'))}
        {toggleRow('notify_offline', t('telegram.notifyOffline'), t('telegram.notifyOfflineHint'))}
        <FieldRow
          htmlFor={`${idBase}-offline`}
          label={t('telegram.offlineMinLabel')}
          help={t('telegram.offlineMinHint')}
          control={
            <NumberInput
              id={`${idBase}-offline`}
              value={v.offline_min}
              min={1}
              max={1440}
              integer
              unit={t('units.minutes')}
              onChange={(n) => edit.set('offline_min', n)}
            />
          }
        />
        {toggleRow('notify_queue', t('telegram.notifyQueue'), t('telegram.notifyQueueHint'))}
        <FieldRow
          htmlFor={`${idBase}-queue`}
          label={t('telegram.queueStuckMinLabel')}
          help={t('telegram.queueStuckMinHint')}
          control={
            <NumberInput
              id={`${idBase}-queue`}
              value={v.queue_stuck_min}
              min={1}
              max={1440}
              integer
              unit={t('units.minutes')}
              onChange={(n) => edit.set('queue_stuck_min', n)}
            />
          }
        />
        {toggleRow('notify_roll', t('telegram.notifyRoll'), t('telegram.notifyRollHint'))}
        <FieldRow
          htmlFor={`${idBase}-roll`}
          label={t('telegram.rollLowLabel')}
          help={t('telegram.rollLowHint')}
          control={
            <NumberInput
              id={`${idBase}-roll`}
              value={v.roll_low_m}
              min={0}
              max={30}
              step={0.1}
              unit={t('units.meters')}
              onChange={(n) => edit.set('roll_low_m', n)}
            />
          }
        />

        <FieldRow
          htmlFor={`${idBase}-quiet`}
          label={t('telegram.quietHoursTitle')}
          help={quietActive ? t('telegram.quietHoursHint') : t('telegram.quietHoursNone')}
          align="end"
          control={
            <ToggleControl
              id={`${idBase}-quiet`}
              checked={quietActive}
              onChange={(on) => edit.set('quiet_hours', on ? `${quiet.start}-${quiet.end}` : null)}
            />
          }
        />
        {quietActive ? (
          <FieldRow
            labelId={`${idBase}-period`}
            label={t('telegram.quietPeriodLabel')}
            help={t('telegram.quietPeriodHint')}
            control={
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
            }
          />
        ) : null}
      </FieldRows>
      {error ? (
        <MessageBar intent="error">
          <MessageBarBody>{error}</MessageBarBody>
        </MessageBar>
      ) : null}
      <SecretDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        name="telegram"
        title={t('telegram.secretDialogTitle')}
        fieldLabel={t('telegram.secretFieldLabel')}
      />
    </Section>
  );
}
