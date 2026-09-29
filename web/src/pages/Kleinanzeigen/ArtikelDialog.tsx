/** Gemeinsamer Dialog „Neuer Artikel" / „Artikel bearbeiten". */
import { useEffect, useState } from 'react';
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
import { ErrorMessage } from '../../components/ErrorMessage';
import { createArtikel, updateArtikel } from './api';
import type { ArtikelFormValues, ArtikelJson } from './types';
import { useDialogFocusReturn } from '../../components/useDialogFocusReturn';

const EMPTY: ArtikelFormValues = { titel: '', preis: '', anzeige: '', ort: '', notiz: '' };

function fromArtikel(a: ArtikelJson): ArtikelFormValues {
  return { titel: a.titel, preis: a.preis, anzeige: a.anzeige ?? '', ort: a.ort, notiz: a.notiz };
}

const useStyles = makeStyles({
  content: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM, minWidth: '280px' },
});

export function ArtikelDialog(props: {
  open: boolean;
  artikel: ArtikelJson | null;
  onClose: () => void;
  onSaved: (artikel: ArtikelJson, created: boolean) => void;
}): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('kleinanzeigen');
  const { t: tc } = useTranslation('common');
  const { open, artikel } = props;
  useDialogFocusReturn(open);
  const editing = artikel !== null;
  const [values, setValues] = useState<ArtikelFormValues>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    if (open) {
      setValues(artikel ? fromArtikel(artikel) : EMPTY);
      setError(null);
    }
  }, [open, artikel]);

  const set = (patch: Partial<ArtikelFormValues>): void => setValues((v) => ({ ...v, ...patch }));

  async function submit(): Promise<void> {
    if (!values.titel.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const body = {
        titel: values.titel.trim(),
        preis: values.preis.trim(),
        anzeige: values.anzeige.trim() ? values.anzeige.trim() : null,
        ort: values.ort.trim(),
        notiz: values.notiz.trim(),
      };
      const result = editing && artikel ? await updateArtikel(artikel.id, body) : await createArtikel(body);
      props.onSaved(result, !editing);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, 'Fehler', String(err))); // i18n-ignore (interner Fehler-Kind, nicht sichtbar)
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(_e, data) => !data.open && props.onClose()}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{editing ? t('dialogs.edit.title') : t('dialogs.new.title')}</DialogTitle>
          <DialogContent className={styles.content}>
            {error ? <ErrorMessage error={error} /> : null}
            <Field label={t('fields.title')} required>
              <Input value={values.titel} onChange={(_e, d) => set({ titel: d.value })} />
            </Field>
            <Field label={t('fields.price')}>
              <Input value={values.preis} placeholder={t('fields.pricePlaceholder')} onChange={(_e, d) => set({ preis: d.value })} />
            </Field>
            <Field label={t('fields.adUrl')}>
              <Input value={values.anzeige} placeholder={t('fields.adUrlPlaceholder')} onChange={(_e, d) => set({ anzeige: d.value })} />
            </Field>
            <Field label={t('fields.location')}>
              <Input value={values.ort} placeholder={t('fields.locationPlaceholder')} onChange={(_e, d) => set({ ort: d.value })} />
            </Field>
            <Field label={t('fields.note')}>
              <Textarea value={values.notiz} onChange={(_e, d) => set({ notiz: d.value })} />
            </Field>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!values.titel.trim() || saving} onClick={() => void submit()}>
              {saving ? t('actions.creating') : editing ? tc('actions.save') : t('actions.create')}
            </Button>
            <Button appearance="secondary" onClick={props.onClose}>
              {tc('actions.cancel')}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
