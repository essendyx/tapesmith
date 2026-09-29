/** Dialog „Neue Box": ID, Ort, Notiz. 422 vom Server erscheint als Meldung am ID-Feld. */
import { useState } from 'react';
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
  Textarea,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../api/client';
import { createBox } from './api';
import type { BoxJson } from '../../api/types';

const useStyles = makeStyles({
  content: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
});

export function NewBoxDialog(props: { open: boolean; onClose: () => void; onCreated: (box: BoxJson) => void }): JSX.Element {
  const { t } = useTranslation('inventar');
  const styles = useStyles();
  const [id, setId] = useState('');
  const [location, setLocation] = useState('');
  const [note, setNote] = useState('');
  const [idError, setIdError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setId('');
    setLocation('');
    setNote('');
    setIdError(null);
  };

  const close = () => {
    reset();
    props.onClose();
  };

  const submit = async () => {
    setBusy(true);
    setIdError(null);
    try {
      const box = await createBox({ id, location, note });
      reset();
      props.onCreated(box);
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setIdError(err.message);
      } else {
        setIdError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={props.open} onOpenChange={(_e, data) => !data.open && close()}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{t('newBox.title')}</DialogTitle>
          <DialogContent className={styles.content}>
            <Field label={t('newBox.id')} validationState={idError ? 'error' : undefined} validationMessage={idError ?? undefined}>
              <Input value={id} onChange={(_e, d) => setId(d.value)} placeholder={t('newBox.idPlaceholder')} />
            </Field>
            <Field label={t('newBox.location')}>
              <Input value={location} onChange={(_e, d) => setLocation(d.value)} placeholder={t('newBox.locationPlaceholder')} />
            </Field>
            <Field label={t('newBox.note')}>
              <Textarea value={note} onChange={(_e, d) => setNote(d.value)} resize="vertical" />
            </Field>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={busy || !id.trim()} onClick={() => void submit()}>
              {t('newBox.create')}
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
