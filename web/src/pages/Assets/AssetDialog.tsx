/** Dialog für „Neue Assets", „Vorhandene Nummer übernehmen" und „Bearbeiten". */
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
  Spinner,
} from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../api/client';
import { useNotify } from '../../components/NotifyProvider';
import { createAssets, importAsset, updateAsset } from './api';
import type { AssetJson } from './types';
import { useDialogFocusReturn } from '../../components/useDialogFocusReturn';

export type AssetDialogMode = 'create' | 'import' | 'edit';

interface FormState {
  id: string;
  count: string;
  bezeichnung: string;
  kategorie: string;
  standort: string;
  seriennummer: string;
  host: string;
  ziel: string;
  paperless_doc: string;
  notiz: string;
}

const EMPTY: FormState = {
  id: '',
  count: '1',
  bezeichnung: '',
  kategorie: '',
  standort: '',
  seriennummer: '',
  host: '',
  ziel: '',
  paperless_doc: '',
  notiz: '',
};

function fromAsset(asset: AssetJson): FormState {
  return {
    id: asset.id,
    count: '1',
    bezeichnung: asset.bezeichnung,
    kategorie: asset.kategorie,
    standort: asset.standort,
    seriennummer: asset.seriennummer,
    host: asset.host,
    ziel: asset.ziel ?? '',
    paperless_doc: asset.paperless_doc != null ? String(asset.paperless_doc) : '',
    notiz: asset.notiz,
  };
}

export function AssetDialog(props: {
  mode: AssetDialogMode | null;
  asset?: AssetJson | null;
  onClose: () => void;
  onCreated?: (assets: AssetJson[]) => void;
  onImported?: (asset: AssetJson) => void;
  onUpdated?: (asset: AssetJson, warnings: string[]) => void;
}): JSX.Element {
  const { t } = useTranslation('assets');
  const notify = useNotify();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [busy, setBusy] = useState(false);
  const mode = props.mode;
  useDialogFocusReturn(mode !== null);

  const TITLES: Record<AssetDialogMode, string> = {
    create: t('dialog.titles.create'),
    import: t('dialog.titles.import'),
    edit: t('dialog.titles.edit'),
  };

  useEffect(() => {
    if (mode === 'edit' && props.asset) {
      setForm(fromAsset(props.asset));
    } else if (mode) {
      setForm(EMPTY);
    }
  }, [mode, props.asset]);

  const set = (patch: Partial<FormState>) => setForm((prev) => ({ ...prev, ...patch }));

  const paperlessId = form.paperless_doc.trim() ? Number.parseInt(form.paperless_doc, 10) : null;
  const paperlessInvalid = form.paperless_doc.trim() !== '' && !Number.isFinite(paperlessId);

  const submit = async (): Promise<void> => {
    if (!mode) return;
    setBusy(true);
    try {
      if (mode === 'create') {
        const count = Math.max(1, Number.parseInt(form.count, 10) || 1);
        const res = await createAssets({
          count,
          bezeichnung: form.bezeichnung,
          kategorie: form.kategorie,
          standort: form.standort,
          seriennummer: form.seriennummer,
          host: form.host,
          ziel: form.ziel.trim() ? form.ziel.trim() : null,
          paperless_doc: paperlessId,
          notiz: form.notiz,
        });
        notify({ intent: 'success', title: t('dialog.notify.created', { count: res.assets.length }) });
        props.onCreated?.(res.assets);
      } else if (mode === 'import') {
        const asset = await importAsset({
          id: form.id,
          bezeichnung: form.bezeichnung,
          kategorie: form.kategorie,
          standort: form.standort,
          seriennummer: form.seriennummer,
          host: form.host,
          ziel: form.ziel.trim() ? form.ziel.trim() : null,
          paperless_doc: paperlessId,
          notiz: form.notiz,
        });
        notify({ intent: 'success', title: t('dialog.notify.imported', { id: asset.id }) });
        props.onImported?.(asset);
      } else if (mode === 'edit' && props.asset) {
        const res = await updateAsset(props.asset.id, {
          bezeichnung: form.bezeichnung,
          kategorie: form.kategorie,
          standort: form.standort,
          seriennummer: form.seriennummer,
          host: form.host,
          ziel: form.ziel.trim() ? form.ziel.trim() : null,
          paperless_doc: paperlessId,
          notiz: form.notiz,
        });
        const { warnings, ...asset } = res;
        notify({ intent: 'success', title: t('dialog.notify.updated', { id: asset.id }) });
        props.onUpdated?.(asset, warnings);
      }
      props.onClose();
    } catch (err) {
      notify({
        intent: 'error',
        title: err instanceof ApiError ? err.message : t('dialog.notify.failed'),
        hint: err instanceof ApiError ? err.hint || undefined : undefined,
      });
    } finally {
      setBusy(false);
    }
  };

  const canSubmit =
    !busy && !paperlessInvalid && (mode !== 'import' || form.id.trim() !== '') && (mode !== 'create' || Number(form.count) >= 1);

  return (
    <Dialog open={mode !== null} onOpenChange={(_e, d) => !d.open && props.onClose()}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{mode ? TITLES[mode] : ''}</DialogTitle>
          <DialogContent>
            {mode === 'edit' && props.asset ? (
              <Field label={t('dialog.fields.id')}>
                <Input value={props.asset.id} disabled />
              </Field>
            ) : null}
            {mode === 'import' ? (
              <Field label={t('dialog.fields.id')} required>
                <Input value={form.id} onChange={(_e, d) => set({ id: d.value })} autoFocus />
              </Field>
            ) : null}
            {mode === 'create' ? (
              <Field label={t('dialog.fields.count')} required>
                <Input
                  type="number"
                  min={1}
                  max={200}
                  value={form.count}
                  onChange={(_e, d) => set({ count: d.value })}
                  autoFocus
                />
              </Field>
            ) : null}
            <Field label={t('dialog.fields.bezeichnung')}>
              <Input value={form.bezeichnung} onChange={(_e, d) => set({ bezeichnung: d.value })} />
            </Field>
            <Field label={t('dialog.fields.kategorie')}>
              <Input value={form.kategorie} onChange={(_e, d) => set({ kategorie: d.value })} />
            </Field>
            <Field label={t('dialog.fields.standort')}>
              <Input value={form.standort} onChange={(_e, d) => set({ standort: d.value })} />
            </Field>
            <Field label={t('dialog.fields.seriennummer')}>
              <Input value={form.seriennummer} onChange={(_e, d) => set({ seriennummer: d.value })} />
            </Field>
            <Field label={t('dialog.fields.host')}>
              <Input value={form.host} onChange={(_e, d) => set({ host: d.value })} />
            </Field>
            <Field label={t('dialog.fields.ziel')}>
              <Input value={form.ziel} placeholder="https://…" onChange={(_e, d) => set({ ziel: d.value })} />
            </Field>
            <Field
              label={t('dialog.fields.paperlessDoc')}
              validationState={paperlessInvalid ? 'error' : 'none'}
              validationMessage={paperlessInvalid ? t('dialog.paperlessInvalid') : undefined}
            >
              <Input value={form.paperless_doc} onChange={(_e, d) => set({ paperless_doc: d.value })} />
            </Field>
            <Field label={t('dialog.fields.notiz')}>
              <Input value={form.notiz} onChange={(_e, d) => set({ notiz: d.value })} />
            </Field>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!canSubmit} aria-busy={busy} onClick={() => void submit()}>
              {busy ? <Spinner size="tiny" /> : t('common:actions.save')}
            </Button>
            <Button appearance="secondary" onClick={props.onClose} disabled={busy}>
              {t('common:actions.cancel')}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
