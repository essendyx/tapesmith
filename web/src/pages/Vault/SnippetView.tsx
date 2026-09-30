/** Reiter „Snippet“ der Vault-Seite: PNG und Markdown-Zeile aus dem Verlauf für eine Notiz. */
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
  MessageBar,
  MessageBarBody,
  Textarea,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { ArrowDownload20Regular, Copy20Regular, DocumentAdd20Regular, FolderArrowUp20Regular, History20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { ApiError, pngSrc } from '../../api/client';
import { EmptyState } from '../../components/EmptyState';
import { ErrorMessage } from '../../components/ErrorMessage';
import { LoadingState } from '../../components/LoadingState';
import { useNotify } from '../../components/NotifyProvider';
import { Section } from '../../components/Section';
import { useLayoutStyles } from '../../theme/layout';
import { postChangelog, postSnippet, useRecentHistory, useVaultNotes } from './api';
import type { SnippetJson } from './types';
import { useDialogFocusReturn } from '../../components/useDialogFocusReturn';

const useStyles = makeStyles({
  layout: {
    display: 'grid',
    gridTemplateColumns: 'minmax(220px, 320px) minmax(0, 1fr)',
    columnGap: tokens.spacingHorizontalXL,
    rowGap: tokens.spacingVerticalL,
    '@media (max-width: 760px)': { gridTemplateColumns: 'minmax(0, 1fr)' },
  },
  column: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalL, minWidth: 0 },
  list: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXXS, maxHeight: '520px', overflowY: 'auto' },
  entry: { justifyContent: 'flex-start', textAlign: 'left', minWidth: 0 },
  image: {
    maxWidth: '100%',
    imageRendering: 'pixelated',
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: tokens.colorNeutralBackgroundStatic,
    alignSelf: 'flex-start',
  },
  code: {
    fontFamily: tokens.fontFamilyMonospace,
    backgroundColor: tokens.colorNeutralBackground3,
    padding: tokens.spacingHorizontalS,
    borderRadius: tokens.borderRadiusMedium,
    wordBreak: 'break-all',
    margin: 0,
    whiteSpace: 'pre-wrap',
  },
  grow: { flexGrow: 1, minWidth: '200px' },
});

function b64ToBlob(b64: string, type: string): Blob {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type });
}

function downloadPng(snippet: SnippetJson): void {
  const url = URL.createObjectURL(b64ToBlob(snippet.png, 'image/png'));
  try {
    const a = document.createElement('a');
    a.href = url;
    a.download = snippet.file_name;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

export function SnippetView(): JSX.Element {
  const styles = useStyles();
  const layout = useLayoutStyles();
  const { t } = useTranslation('vault');
  const { t: tc } = useTranslation('common');
  const notify = useNotify();
  const history = useRecentHistory();
  const notes = useVaultNotes('');
  const [selected, setSelected] = useState<number | null>(null);
  const [snippet, setSnippet] = useState<SnippetJson | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [target, setTarget] = useState('');
  const [status, setStatus] = useState<string[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [clTitle, setClTitle] = useState('');
  const [clEntry, setClEntry] = useState('');
  useDialogFocusReturn(dialogOpen);

  const entries = (history.data?.entries ?? []).filter((e) => e.has_head);

  const run = async (historyId: number, saveAttachment: boolean, appendTo: string | null) => {
    setBusy(true);
    setError(null);
    try {
      const result = await postSnippet({ history_id: historyId, save_attachment: saveAttachment, append_to: appendTo });
      setSnippet(result);
      const notes: string[] = [...result.warnings];
      if (result.saved_path) notes.push(t('snippet.savedTo', { path: result.saved_path }));
      if (result.appended && appendTo) notes.push(t('snippet.appendedTo', { path: appendTo }));
      setStatus(notes);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const onSelect = (id: number) => {
    setSelected(id);
    setSnippet(null);
    setStatus([]);
    void run(id, false, null);
  };

  const onCopy = async () => {
    if (!snippet) return;
    try {
      await navigator.clipboard.writeText(snippet.markdown);
      notify({ intent: 'success', title: t('snippet.copiedMarkdownTitle') });
    } catch {
      notify({ intent: 'error', title: t('snippet.copyFailedTitle'), body: t('snippet.copyFailedBody') });
    }
  };

  const openChangelog = () => {
    if (!snippet) return;
    setClTitle(`Label gedruckt: ${snippet.summary}`.slice(0, 120)); // i18n-ignore (Server-Text: Zusammenfassung)
    setClEntry(snippet.changelog_md);
    setDialogOpen(true);
  };

  const onChangelog = async () => {
    try {
      await postChangelog(clTitle.trim(), clEntry);
      setDialogOpen(false);
      notify({ intent: 'success', title: t('snippet.changelogCreatedTitle') });
    } catch (err) {
      const api = err instanceof ApiError ? err : null;
      notify({ intent: 'error', title: api ? api.message : t('snippet.changelogFailedTitle'), hint: api?.hint || undefined });
    }
  };

  return (
    <div className={styles.layout}>
      <div className={styles.column}>
        <Section title={t('snippet.recentTitle')} description={t('snippet.recentDescription')}>
          {history.isLoading ? <LoadingState variant="inline" /> : null}
          {history.error ? <ErrorMessage error={history.error} title={t('snippet.notLoadedTitle')} /> : null}
          {history.data && entries.length === 0 ? <EmptyState icon={<History20Regular />} title={t('snippet.empty')} /> : null}
          <div className={styles.list} role="group" aria-label={t('snippet.ariaLabel')}>
            {entries.map((entry) => (
              <Button
                key={entry.id}
                className={styles.entry}
                appearance={entry.id === selected ? 'primary' : 'subtle'}
                onClick={() => onSelect(entry.id)}
              >
                #{entry.id} {entry.title}
              </Button>
            ))}
          </div>
        </Section>
      </div>
      <div className={styles.column}>
        {error ? <ErrorMessage error={error} /> : null}
        {!snippet && !busy ? <EmptyState title={t('snippet.noSelection.title')} body={t('snippet.noSelection.body')} /> : null}
        {busy ? <LoadingState variant="inline" label={t('snippet.generating')} /> : null}
        {snippet ? (
          <Section title={t('snippet.sectionTitle')} description={snippet.file_name}>
            <img className={styles.image} alt={t('snippet.imageAlt')} src={pngSrc(snippet.png)} />
            <pre className={styles.code} aria-label={t('snippet.markdownAriaLabel')}>
              {snippet.markdown}
            </pre>
            <div className={layout.rowWrap}>
              <Button icon={<Copy20Regular />} onClick={() => void onCopy()}>
                {t('snippet.copyMarkdown')}
              </Button>
              <Button icon={<ArrowDownload20Regular />} onClick={() => downloadPng(snippet)}>
                {t('snippet.downloadPng')}
              </Button>
              <Button icon={<FolderArrowUp20Regular />} disabled={busy} onClick={() => void run(snippet.history_id, true, null)}>
                {t('snippet.saveToVault')}
              </Button>
              <Button icon={<DocumentAdd20Regular />} onClick={openChangelog}>
                {t('snippet.changelogEntry')}
              </Button>
            </div>
            <div className={layout.rowWrap}>
              <Field label={t('snippet.note')} className={styles.grow}>
                <Input list="vault-notes" value={target} onChange={(_e, d) => setTarget(d.value)} placeholder={t('snippet.notePlaceholder')} />
              </Field>
              <datalist id="vault-notes">
                {(notes.data?.notes ?? []).map((n) => (
                  <option key={n} value={n} />
                ))}
              </datalist>
              <Button disabled={busy || !target.trim()} onClick={() => void run(snippet.history_id, false, target.trim())}>
                {t('snippet.appendToNote')}
              </Button>
            </div>
            {status.map((line) => (
              <MessageBar key={line} intent={line.startsWith('obsidian.') ? 'warning' : 'success'}>
                <MessageBarBody>{line}</MessageBarBody>
              </MessageBar>
            ))}
          </Section>
        ) : null}
      </div>
      <Dialog open={dialogOpen} onOpenChange={(_e, d) => setDialogOpen(d.open)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{t('changelogDialog.title')}</DialogTitle>
            <DialogContent>
              <Field label={t('changelogDialog.titleField')}>
                <Input value={clTitle} maxLength={120} onChange={(_e, d) => setClTitle(d.value)} />
              </Field>
              <Field label={t('changelogDialog.entryField')}>
                <Textarea value={clEntry} maxLength={4000} rows={4} onChange={(_e, d) => setClEntry(d.value)} />
              </Field>
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" disabled={!clTitle.trim() || !clEntry.trim()} onClick={() => void onChangelog()}>
                {t('changelogDialog.submit')}
              </Button>
              <Button appearance="secondary" onClick={() => setDialogOpen(false)}>
                {tc('actions.cancel')}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </div>
  );
}
