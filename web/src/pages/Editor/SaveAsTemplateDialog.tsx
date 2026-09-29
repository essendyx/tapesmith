/** Als Vorlage speichern: Name, Beschreibung, Kategorie, Stichworte; Konflikt bietet „Überschreiben“. */
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
  Textarea,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../api/client';
import { qk } from '../../api/core';
import type { LabelDocumentJson } from '../../api/types';
import { ErrorMessage } from '../../components/ErrorMessage';
import { useNotify } from '../../components/NotifyProvider';
import { saveAsTemplate } from './editorApi';

const useStyles = makeStyles({
  surface: { maxWidth: '520px', width: 'calc(100vw - 32px)' },
  form: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
});

export function SaveAsTemplateDialog(props: { open: boolean; document: LabelDocumentJson; initialName: string; onClose: () => void }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('editor');
  const notify = useNotify();
  const queryClient = useQueryClient();
  const [name, setName] = useState(props.initialName);
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState(() => t('template.categoryDefault'));
  const [tags, setTags] = useState('');
  const [conflict, setConflict] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const save = async (overwrite: boolean) => {
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await saveAsTemplate({
        name: name.trim(),
        description: description.trim(),
        category: category.trim(),
        tags: tags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
        document: props.document,
        overwrite,
      });
      void queryClient.invalidateQueries({ queryKey: qk.templates });
      void queryClient.invalidateQueries({ queryKey: qk.gallery });
      notify({ intent: 'success', title: t('template.saved', { name: name.trim() }) });
      props.onClose();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422 && /gibt es schon/i.test(err.message)) { // i18n-ignore (Servertext)
        setConflict(err.message);
      } else {
        setError(err);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={props.open} onOpenChange={(_e, d) => (d.open ? undefined : props.onClose())}>
      <DialogSurface className={styles.surface}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void save(false);
          }}
        >
          <DialogBody>
            <DialogTitle>{t('template.title')}</DialogTitle>
            <DialogContent className={styles.form}>
              <Field label={t('template.name')} required>
                <Input
                  autoFocus
                  value={name}
                  onChange={(_e, d) => {
                    setName(d.value);
                    setConflict(null);
                  }}
                />
              </Field>
              <Field label={t('template.description')}>
                <Textarea value={description} onChange={(_e, d) => setDescription(d.value)} />
              </Field>
              <Field label={t('template.category')}>
                <Input value={category} onChange={(_e, d) => setCategory(d.value)} />
              </Field>
              <Field label={t('template.tags')} hint={t('template.tagsHint')}>
                <Input value={tags} onChange={(_e, d) => setTags(d.value)} />
              </Field>
              {conflict ? (
                <MessageBar intent="warning" layout="multiline">
                  <MessageBarBody>{t('template.conflict', { message: conflict })}</MessageBarBody>
                </MessageBar>
              ) : null}
              {error ? <ErrorMessage error={error} title={t('template.error')} /> : null}
            </DialogContent>
            <DialogActions>
              {conflict ? (
                <Button appearance="primary" disabled={busy} onClick={() => void save(true)}>
                  {t('template.overwrite')}
                </Button>
              ) : (
                <Button appearance="primary" type="submit" disabled={busy || !name.trim()}>
                  {t('template.save')}
                </Button>
              )}
              <Button onClick={props.onClose}>{t('template.cancel')}</Button>
            </DialogActions>
          </DialogBody>
        </form>
      </DialogSurface>
    </Dialog>
  );
}
