/** Karte „Konfiguration als Code“: Export/Import von Konfiguration und Vorlagen. */
import { useId, useState } from 'react';
import { Body1, Button, Input, MessageBar, MessageBarBody, makeStyles, tokens } from '@fluentui/react-components';
import { Folder16Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { Section } from '../../../components/Section';
import { useConfirm } from '../../../components/ConfirmProvider';
import { useNotify } from '../../../components/NotifyProvider';
import { isAppWindow, pickFolder } from '../../../platform';
import { postConfigExport, postConfigImport } from '../api';
import { FieldRow, FieldRows, InlineAction, ToggleControl } from '../../../components/FieldRow';
import { CONFIG_CODE_ID } from '../sectionIds';

const useStyles = makeStyles({
  files: { fontFamily: tokens.fontFamilyMonospace, fontSize: tokens.fontSizeBase200, whiteSpace: 'pre-wrap', margin: 0 },
  importNow: { alignSelf: 'flex-start' },
});

export function ConfigCodeCard(): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const styles = useStyles();
  const confirm = useConfirm();
  const notify = useNotify();
  const [dir, setDir] = useState('');
  const [includeTemplates, setIncludeTemplates] = useState(true);
  const [stripSecrets, setStripSecrets] = useState(true);
  const [exportedFiles, setExportedFiles] = useState<string[] | null>(null);
  const [importPreview, setImportPreview] = useState<{ changes: string[]; warnings: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const dirId = useId();
  const templatesId = useId();
  const secretsId = useId();

  const chooseFolder = async () => {
    const picked = await pickFolder(t('configCode.chooseFolderDialog'));
    if (picked) setDir(picked);
  };

  const onExport = async () => {
    setError(null);
    try {
      const r = await postConfigExport({ dir, include_templates: includeTemplates, strip_secrets: stripSecrets });
      setExportedFiles(r.files);
      notify({ intent: 'success', title: t('configCode.notify.exported') });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const onImportPreview = async () => {
    setError(null);
    try {
      const r = await postConfigImport({ dir, dry_run: true, include_templates: includeTemplates });
      setImportPreview({ changes: r.changes, warnings: r.warnings });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const onImportNow = async () => {
    const ok = await confirm({
      title: t('configCode.confirm.title'),
      message: t('configCode.confirm.message'),
      confirmText: t('configCode.confirm.confirm'),
    });
    if (!ok) return;
    try {
      await postConfigImport({ dir, dry_run: false, include_templates: includeTemplates });
      setImportPreview(null);
      notify({ intent: 'success', title: t('configCode.notify.imported') });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div id={CONFIG_CODE_ID}>
      <Section
        title={t('configCode.title')}
        description={t('configCode.description')}
        actions={
          <>
            <Button appearance="secondary" onClick={() => void onExport()}>
              {t('configCode.export')}
            </Button>
            <Button appearance="secondary" onClick={() => void onImportPreview()}>
              {t('configCode.import')}
            </Button>
          </>
        }
      >
        {error ? (
          <MessageBar intent="error">
            <MessageBarBody>{error}</MessageBarBody>
          </MessageBar>
        ) : null}

        <FieldRows>
          <FieldRow
            htmlFor={dirId}
            label={t('configCode.folderLabel')}
            help={t('configCode.folderHelp')}
            control={
              <Input
                id={dirId}
                value={dir}
                onChange={(_e, d) => setDir(d.value)}
                placeholder={t('configCode.folderPlaceholder')}
                title={dir || undefined}
                contentAfter={
                  isAppWindow() ? (
                    <InlineAction label={t('configCode.chooseFolder')} icon={<Folder16Regular />} onClick={() => void chooseFolder()} />
                  ) : undefined
                }
              />
            }
          />
          <FieldRow
            htmlFor={templatesId}
            label={t('configCode.includeTemplates')}
            align="end"
            control={<ToggleControl id={templatesId} checked={includeTemplates} onChange={setIncludeTemplates} />}
          />
          <FieldRow
            htmlFor={secretsId}
            label={t('configCode.stripSecrets')}
            help={t('configCode.stripSecretsHelp')}
            align="end"
            control={<ToggleControl id={secretsId} checked={stripSecrets} onChange={setStripSecrets} />}
          />
        </FieldRows>

        {exportedFiles ? <pre className={styles.files}>{exportedFiles.join('\n')}</pre> : null}

        {importPreview ? (
          <>
            {importPreview.warnings.length > 0 ? (
              <MessageBar intent="warning">
                <MessageBarBody>{importPreview.warnings.join('\n')}</MessageBarBody>
              </MessageBar>
            ) : null}
            <Body1>{t('configCode.changes')}</Body1>
            <pre className={styles.files}>{importPreview.changes.join('\n')}</pre>
            <Button className={styles.importNow} appearance="primary" onClick={() => void onImportNow()}>
              {t('configCode.importNow')}
            </Button>
          </>
        ) : null}
      </Section>
    </div>
  );
}
