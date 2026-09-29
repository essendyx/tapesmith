/**
 * Karte „Sicherung“: tägliche Sicherung und Anzahl (Felder des Abschnitts `sicherung`), Jetzt sichern,
 * Liste und Probelauf für die Wiederherstellung. Der Sicherungsordner steht unter „Erweitert“.
 */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Body1, Button, Caption1, MessageBar, MessageBarBody, Spinner, makeStyles, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { Section } from '../../../components/Section';
import { useNotify } from '../../../components/NotifyProvider';
import { postBackupNow, postBackupRestore, useBackups } from '../api';
import { formatBytes } from '../format';
import { useFormat } from '../../../i18n/format';
import { FieldRow, FieldRows } from '../FieldRow';
import { useSettingsEdit } from '../context';
import { useSaveSection } from '../useSaveSection';
import { SettingFieldRow } from '../fields/SettingFieldRow';
import type { SettingsSection } from '../../../api/types';

const useStyles = makeStyles({
  hint: { color: tokens.colorNeutralForeground3 },
  lines: { fontFamily: tokens.fontFamilyMonospace, fontSize: tokens.fontSizeBase200, whiteSpace: 'pre-wrap', margin: 0 },
  command: {
    fontFamily: tokens.fontFamilyMonospace,
    backgroundColor: tokens.colorNeutralBackground3,
    borderRadius: tokens.borderRadiusSmall,
    padding: `${tokens.spacingVerticalXS} ${tokens.spacingHorizontalS}`,
    display: 'inline-block',
  },
});

export function BackupCard(props: { section?: SettingsSection }): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const styles = useStyles();
  const { formatDateTime } = useFormat();
  const client = useQueryClient();
  const notify = useNotify();
  const backups = useBackups();
  const [saving, setSaving] = useState(false);
  const [restorePreview, setRestorePreview] = useState<{ name: string; lines: string[] } | null>(null);
  const [busyName, setBusyName] = useState<string | null>(null);
  const edit = useSettingsEdit();
  const saveSection = useSaveSection();
  const section = props.section;
  const keys = section?.fields.map((f) => f.key) ?? [];
  const dirty = keys.some((k) => edit.isChanged(k));
  const savingFields = section !== undefined && edit.savingSection === section.id;
  const fieldsError = section ? edit.errorFor(section.id) : null;

  const onBackupNow = async () => {
    setSaving(true);
    try {
      await postBackupNow();
      await client.invalidateQueries({ queryKey: ['backups'] });
      notify({ intent: 'success', title: t('backup.notify.created') });
    } catch (err) {
      notify({ intent: 'error', title: t('backup.notify.createFailed'), body: err instanceof Error ? err.message : String(err) });
    } finally {
      setSaving(false);
    }
  };

  const onRestorePreview = async (name: string) => {
    setBusyName(name);
    try {
      const r = await postBackupRestore({ name, dry_run: true });
      setRestorePreview({ name, lines: r.lines });
    } catch (err) {
      notify({ intent: 'error', title: t('backup.notify.previewFailed'), body: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusyName(null);
    }
  };

  const command = restorePreview ? `p12 daemon stop && p12 backup restore ${restorePreview.name}` : '';

  return (
    <div id="sicherung">
      <Section
        title={t('backup.title')}
        description={backups.data?.dir ? t('backup.dir', { dir: backups.data.dir }) : undefined}
        actions={
          <>
            {dirty && section ? (
              <>
                {savingFields ? <Spinner size="tiny" /> : null}
                <Button appearance="secondary" disabled={savingFields} onClick={() => edit.discard(keys)}>
                  {t('generic.discard')}
                </Button>
                <Button appearance="primary" disabled={savingFields} onClick={() => void saveSection(section, t('backup.title'))}>
                  {t('generic.save')}
                </Button>
              </>
            ) : null}
            <Button
              appearance={dirty ? 'secondary' : 'primary'}
              disabled={saving}
              icon={saving ? <Spinner size="tiny" /> : undefined}
              onClick={() => void onBackupNow()}
            >
              {t('backup.now')}
            </Button>
          </>
        }
      >
        {fieldsError ? (
          <MessageBar intent="error">
            <MessageBarBody>{fieldsError}</MessageBarBody>
          </MessageBar>
        ) : null}
        {section && section.fields.length > 0 ? (
          <FieldRows>
            {section.fields.map((field) => (
              <SettingFieldRow key={field.key} field={field} />
            ))}
          </FieldRows>
        ) : null}
        {backups.data && backups.data.backups.length === 0 ? <Body1>{t('backup.empty')}</Body1> : null}
        {(backups.data?.backups ?? []).length > 0 ? (
          <FieldRows>
            {(backups.data?.backups ?? []).map((b) => (
              <FieldRow
                key={b.name}
                label={formatDateTime(b.created)}
                help={formatBytes(b.size_bytes)}
                control={
                  <Button appearance="secondary" disabled={busyName === b.name} onClick={() => void onRestorePreview(b.name)}>
                    {t('backup.restore')}
                  </Button>
                }
              />
            ))}
          </FieldRows>
        ) : null}

        {restorePreview ? (
          <>
            <MessageBar intent="warning">
              <MessageBarBody>
                {t('backup.previewTitle', { name: restorePreview.name })}
                <br />
                <span className={styles.command}>{command}</span>
              </MessageBarBody>
            </MessageBar>
            {restorePreview.lines.length > 0 ? <pre className={styles.lines}>{restorePreview.lines.join('\n')}</pre> : null}
          </>
        ) : null}

        <Caption1 className={styles.hint}>{t('backup.hint')}</Caption1>
      </Section>
    </div>
  );
}
