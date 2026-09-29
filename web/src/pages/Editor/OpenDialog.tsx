/** Öffnen (Server-Dokumente oder .p12doc.json hochladen) und „Speichern unter“ (Name). */
import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Caption1,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { ArrowUpload20Regular, Delete20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { qk } from '../../api/core';
import type { LabelDocumentJson } from '../../api/types';
import { useConfirm } from '../../components/ConfirmProvider';
import { formatDateTime } from '../../i18n/format';
import { DRAFT_NAME, deleteDocument, listDocuments } from './editorApi';

const useStyles = makeStyles({
  surface: { maxWidth: '640px', width: 'calc(100vw - 32px)' },
  saveSurface: { maxWidth: '440px' },
  tableWrap: { maxHeight: '50vh', overflowY: 'auto' },
  row: { cursor: 'pointer' },
  selected: { backgroundColor: tokens.colorBrandBackground2 },
  muted: { color: tokens.colorNeutralForeground3 },
  error: { color: tokens.colorPaletteRedForeground1 },
  hidden: { position: 'absolute', width: '1px', height: '1px', opacity: 0, overflow: 'hidden' },
});

export function OpenDialog(props: {
  open: boolean;
  onClose: () => void;
  onOpen: (name: string) => void;
  onUpload: (doc: LabelDocumentJson, name: string) => void;
}): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('editor');
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const [chosen, setChosen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const docs = useQuery({ queryKey: qk.documents, queryFn: ({ signal }) => listDocuments(signal), enabled: props.open });
  const list = (docs.data?.documents ?? []).filter((d) => d.name !== DRAFT_NAME);

  const upload = async (file: File) => {
    setError(null);
    try {
      const parsed = JSON.parse(await file.text()) as LabelDocumentJson;
      if (!parsed || typeof parsed !== 'object' || !Array.isArray(parsed.objects)) throw new Error('invalid');
      props.onUpload(parsed, file.name.replace(/\.p12doc\.json$|\.json$/i, ''));
    } catch {
      setError(t('open.invalid'));
    }
  };

  const remove = async (name: string) => {
    const ok = await confirm({ title: t('open.deleteTitle', { name }), message: t('open.deleteBody'), confirmText: t('open.deleteConfirm'), cancelText: t('open.cancel'), danger: true });
    if (!ok) return;
    await deleteDocument(name);
    if (chosen === name) setChosen(null);
    void queryClient.invalidateQueries({ queryKey: qk.documents });
  };

  return (
    <Dialog open={props.open} onOpenChange={(_e, d) => (d.open ? undefined : props.onClose())}>
      <DialogSurface className={styles.surface}>
        <DialogBody>
          <DialogTitle>{t('open.title')}</DialogTitle>
          <DialogContent>
            {docs.isLoading ? <Spinner size="small" label={t('open.loading')} /> : null}
            {docs.data && list.length === 0 ? <Caption1 className={styles.muted}>{t('open.empty')}</Caption1> : null}
            {list.length > 0 ? (
              <div className={styles.tableWrap}>
                <Table size="small" aria-label={t('open.table')}>
                  <TableHeader>
                    <TableRow>
                      <TableHeaderCell>{t('open.name')}</TableHeaderCell>
                      <TableHeaderCell>{t('open.modified')}</TableHeaderCell>
                      <TableHeaderCell>{t('open.objects')}</TableHeaderCell>
                      <TableHeaderCell aria-label={t('open.actions')} />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {list.map((d) => (
                      <TableRow
                        key={d.name}
                        className={chosen === d.name ? `${styles.row} ${styles.selected}` : styles.row}
                        aria-selected={chosen === d.name}
                        onClick={() => setChosen(d.name)}
                        onDoubleClick={() => props.onOpen(d.name)}
                      >
                        <TableCell>{d.name}</TableCell>
                        <TableCell>{formatDateTime(d.modified)}</TableCell>
                        <TableCell>{d.objects}</TableCell>
                        <TableCell>
                          <Button
                            appearance="subtle"
                            size="small"
                            icon={<Delete20Regular />}
                            aria-label={t('open.delete', { name: d.name })}
                            onClick={(e) => {
                              e.stopPropagation();
                              void remove(d.name);
                            }}
                          />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : null}
            {error ? <Caption1 className={styles.error}>{error}</Caption1> : null}
            <input
              ref={fileRef}
              className={styles.hidden}
              type="file"
              accept=".json,application/json"
              aria-label={t('open.file')}
              tabIndex={-1}
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = '';
                if (file) void upload(file);
              }}
            />
          </DialogContent>
          <DialogActions fluid>
            <Button icon={<ArrowUpload20Regular />} onClick={() => fileRef.current?.click()}>
              {t('open.upload')}
            </Button>
            <Button appearance="primary" disabled={!chosen} onClick={() => chosen && props.onOpen(chosen)}>
              {t('open.open')}
            </Button>
            <Button onClick={props.onClose}>{t('open.cancel')}</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

export function SaveAsDialog(props: { open: boolean; initial: string; onClose: () => void; onSave: (name: string) => Promise<boolean> }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('editor');
  const [name, setName] = useState(props.initial);
  const [busy, setBusy] = useState(false);
  const valid = name.trim().length > 0 && !name.trim().startsWith('_');
  const submit = async () => {
    if (!valid || busy) return;
    setBusy(true);
    try {
      await props.onSave(name.trim());
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={props.open} onOpenChange={(_e, d) => (d.open ? undefined : props.onClose())}>
      <DialogSurface className={styles.saveSurface}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <DialogBody>
            <DialogTitle>{t('saveAs.title')}</DialogTitle>
            <DialogContent>
              <Field label={t('saveAs.name')} hint={t('saveAs.hint')} validationMessage={name.trim().startsWith('_') ? t('saveAs.reserved') : undefined}>
                <Input autoFocus value={name} onChange={(_e, d) => setName(d.value)} />
              </Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" type="submit" disabled={!valid || busy}>
                {t('saveAs.save')}
              </Button>
              <Button onClick={props.onClose}>{t('saveAs.cancel')}</Button>
            </DialogActions>
          </DialogBody>
        </form>
      </DialogSurface>
    </Dialog>
  );
}
