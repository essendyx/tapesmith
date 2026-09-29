/** Dialog zum Setzen eines Geheimnisses (MQTT-Passwort, Telegram-Token): nie den alten Wert anzeigen. */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  Spinner,
} from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../api/client';
import { useNotify } from '../../components/NotifyProvider';
import { ACCESS_KEY, putAccessSecret } from './api';
import { useDialogFocusReturn } from '../../components/useDialogFocusReturn';

export function SecretDialog(props: {
  open: boolean;
  onClose: () => void;
  name: 'mqtt' | 'telegram';
  title: string;
  fieldLabel: string;
}): JSX.Element {
  const { t } = useTranslation('zugriff');
  const notify = useNotify();
  const queryClient = useQueryClient();
  const [value, setValue] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useDialogFocusReturn(props.open);

  const close = () => {
    setValue('');
    setBusy(false);
    setError(null);
    props.onClose();
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await putAccessSecret(props.name, value);
      void queryClient.invalidateQueries({ queryKey: ACCESS_KEY });
      notify({ intent: 'success', title: t('secretDialog.saved', { title: props.title }) });
      close();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={props.open}
      onOpenChange={(_e, data) => {
        if (!data.open) close();
      }}
    >
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{props.title}</DialogTitle>
          <DialogContent>
            <Field label={props.fieldLabel}>
              <Input type="password" value={value} onChange={(_e, d) => setValue(d.value)} autoComplete="off" autoFocus />
            </Field>
            {error ? (
              <MessageBar intent="error">
                <MessageBarBody>{error}</MessageBarBody>
              </MessageBar>
            ) : null}
          </DialogContent>
          <DialogActions>
            <Button
              appearance="primary"
              disabled={value === '' || busy}
              icon={busy ? <Spinner size="tiny" /> : undefined}
              aria-busy={busy}
              onClick={() => void submit()}
            >
              {t('common:actions.save')}
            </Button>
            <Button appearance="secondary" onClick={close}>
              {t('common:actions.cancel')}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
