/**
 * Formularzeile für einen Geheimwert (Token, Passwort): Zustand als Plakette, Kennwortfeld mit
 * „Speichern“ bzw. „Ersetzen“, „Entfernen“ und bei externer Quelle „In Tapesmith übernehmen“.
 * Der gespeicherte Wert wird nie angezeigt; gespeichert wird in den Windows-Anmeldeinformationen.
 */
import { useId, useState, type ReactNode } from 'react';
import { Badge, Button, Input, Spinner, makeStyles, tokens } from '@fluentui/react-components';
import { ArrowDownload20Regular, Delete20Regular } from '@fluentui/react-icons';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../api/client';
import { adoptSecret, deleteSecret, putSecret, refreshSecretViews, useSecrets, type SecretSlot } from '../api/secrets';
import { useConfirm } from './ConfirmProvider';
import { FieldRow } from './FieldRow';
import { useNotify } from './NotifyProvider';

const useStyles = makeStyles({
  control: { display: 'flex', columnGap: tokens.spacingHorizontalS, width: '100%', minWidth: 0 },
  input: { flex: '1 1 auto', minWidth: 0 },
  save: { flex: '0 0 auto' },
  actions: { display: 'flex', columnGap: tokens.spacingHorizontalS, rowGap: tokens.spacingVerticalXS, flexWrap: 'wrap' },
});

export function SecretStateBadge(props: { slot: SecretSlot | undefined }): JSX.Element | null {
  const { t } = useTranslation('secrets');
  const slot = props.slot;
  if (!slot) return null;
  if (slot.source === 'extern') {
    return (
      <Badge appearance="tint" size="small" color={slot.set ? 'informative' : 'warning'}>
        {slot.set ? t('state.external') : t('state.externalMissing')}
      </Badge>
    );
  }
  return (
    <Badge appearance="tint" size="small" color={slot.set ? 'success' : 'warning'}>
      {slot.set ? t('state.saved') : t('state.notSet')}
    </Badge>
  );
}

export function SecretField(props: {
  /** Slot-Kennung wie in `/api/v1/secrets` (`telegram`, `paperless`, `proxmox:pve1`). */
  slotId: string;
  label: ReactNode;
  help?: ReactNode;
}): JSX.Element {
  const { t } = useTranslation('secrets');
  const styles = useStyles();
  const notify = useNotify();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const secrets = useSecrets();
  const inputId = useId();
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const slot = secrets.data?.slots.find((s) => s.id === props.slotId);
  // Name des Dienstes aus dem Slot („Paperless“, „Proxmox pve1“) statt der Zeilenbeschriftung („Token“).
  const labelText = slot?.label ?? (typeof props.label === 'string' ? props.label : t('fallbackLabel'));

  const run = async (action: () => Promise<SecretSlot>, success: string) => {
    setBusy(true);
    try {
      const result = await action();
      queryClient.setQueryData<{ slots: SecretSlot[] }>(['secrets'], (old) =>
        old ? { slots: old.slots.map((s) => (s.id === result.id ? result : s)) } : old,
      );
      refreshSecretViews(queryClient);
      setValue('');
      notify({ intent: 'success', title: success });
    } catch (err) {
      notify({
        intent: 'error',
        title: t('errorTitle', { label: labelText }),
        body: err instanceof ApiError || err instanceof Error ? err.message : String(err),
        hint: err instanceof ApiError ? err.hint || undefined : undefined,
      });
    } finally {
      setBusy(false);
    }
  };

  const save = () => void run(() => putSecret(props.slotId, value), t('savedTitle', { label: labelText }));
  const adopt = () => void run(() => adoptSecret(props.slotId), t('adoptedTitle', { label: labelText }));
  const remove = async () => {
    const ok = await confirm({
      title: t('removeConfirmTitle', { label: labelText }),
      message: slot?.source === 'extern' ? t('removeConfirmExternal') : t('removeConfirmMessage'),
      confirmText: t('remove'),
      danger: true,
    });
    if (ok) void run(() => deleteSecret(props.slotId), t('removedTitle', { label: labelText }));
  };

  const helpLines: ReactNode[] = [];
  if (props.help) helpLines.push(props.help);
  if (slot?.source === 'extern') helpLines.push(t('externalHelp'));
  const canRemove = slot !== undefined && (slot.set || slot.source === 'extern');
  const details =
    slot?.source === 'extern' || canRemove ? (
      <div className={styles.actions}>
        {slot?.source === 'extern' ? (
          <Button
            size="small"
            icon={<ArrowDownload20Regular />}
            aria-label={t('adoptAria', { name: labelText })}
            disabled={busy || !slot.set}
            onClick={adopt}
          >
            {t('adopt')}
          </Button>
        ) : null}
        {canRemove ? (
          <Button
            size="small"
            appearance="subtle"
            icon={<Delete20Regular />}
            aria-label={t('removeAria', { name: labelText })}
            disabled={busy}
            onClick={() => void remove()}
          >
            {t('remove')}
          </Button>
        ) : null}
      </div>
    ) : undefined;

  return (
    <FieldRow
      htmlFor={inputId}
      label={props.label}
      badges={<SecretStateBadge slot={slot} />}
      help={helpLines.length > 1 ? <>{helpLines.map((line, i) => <span key={i}>{line} </span>)}</> : helpLines[0]}
      details={details}
      control={
        <div className={styles.control}>
          <Input
            id={inputId}
            className={styles.input}
            type="password"
            autoComplete="new-password"
            value={value}
            placeholder={slot?.set ? t('placeholderReplace') : t('placeholderNew')}
            onChange={(_e, d) => setValue(d.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && value.trim() !== '' && !busy) save();
            }}
          />
          <Button
            className={styles.save}
            appearance="primary"
            disabled={busy || value.trim() === ''}
            icon={busy ? <Spinner size="tiny" /> : undefined}
            aria-busy={busy}
            aria-label={slot?.set ? t('replaceAria', { name: labelText }) : t('saveAria', { name: labelText })}
            onClick={save}
          >
            {slot?.set ? t('replace') : t('save')}
          </Button>
        </div>
      }
    />
  );
}
