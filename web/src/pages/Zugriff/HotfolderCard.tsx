/** Karte „Hotfolder“: Ordnerüberwachung mit Zeitgrenzen. */
import { useId } from 'react';
import { Input, MessageBar, MessageBarBody } from '@fluentui/react-components';
import { Dismiss16Regular, Folder16Regular, FolderOpen16Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { FieldRow, FieldRows, InlineAction, ToggleControl } from '../../components/FieldRow';
import { Section } from '../../components/Section';
import { isAppWindow, openPath, pickFolder } from '../../platform';
import { CardActions } from './CardActions';
import { NumberInput } from './NumberInput';
import type { AccessHotfolder, AccessJson } from './types';
import { useSectionEdit } from './useSectionEdit';
import { useAccessSave } from './useAccessSave';

export function HotfolderCard(props: { data: AccessJson }): JSX.Element {
  const { t } = useTranslation('zugriff');
  const edit = useSectionEdit<AccessHotfolder>(props.data.hotfolder);
  const { save, saving, error } = useAccessSave();
  const v = edit.values;
  const idBase = useId();
  const title = t('hotfolder.title');
  const app = isAppWindow();
  const effectiveDir = props.data.hotfolder.effective_dir;

  const onSave = async () => {
    const ok = await save(edit.changes('hotfolder'), t('hotfolder.saveSuccess'));
    if (ok) edit.discard();
  };

  const chooseFolder = async () => {
    const picked = await pickFolder(t('hotfolder.dirLabel'));
    if (picked) edit.set('dir', picked);
  };

  const hasDir = v.dir !== null && v.dir !== '';
  const dirActions =
    app || hasDir ? (
      <>
        {app ? <InlineAction label={t('hotfolder.chooseDir')} icon={<Folder16Regular />} onClick={() => void chooseFolder()} /> : null}
        {app ? <InlineAction label={t('hotfolder.openDir')} icon={<FolderOpen16Regular />} onClick={() => void openPath(effectiveDir)} /> : null}
        {hasDir ? <InlineAction label={t('hotfolder.resetDir')} icon={<Dismiss16Regular />} onClick={() => edit.set('dir', null)} /> : null}
      </>
    ) : undefined;

  return (
    <Section
      id="hotfolder"
      title={title}
      actions={
        edit.dirty ? (
          <CardActions title={title} dirty={edit.dirty} saving={saving} onSave={() => void onSave()} onDiscard={edit.discard} />
        ) : undefined
      }
    >
      <FieldRows>
        <FieldRow
          htmlFor={`${idBase}-enabled`}
          label={t('hotfolder.enableLabel')}
          help={t('hotfolder.enableHint')}
          align="end"
          control={<ToggleControl id={`${idBase}-enabled`} checked={v.enabled} onChange={(on) => edit.set('enabled', on)} />}
        />
        <FieldRow
          htmlFor={`${idBase}-dir`}
          label={t('hotfolder.dirLabel')}
          help={[t('hotfolder.dirHint'), t('hotfolder.effectiveDir', { path: effectiveDir })].join(' ')}
          control={
            <Input
              id={`${idBase}-dir`}
              value={v.dir ?? ''}
              title={v.dir || undefined}
              placeholder={t('einstellungen:field.defaultValue', { value: effectiveDir })}
              contentAfter={dirActions}
              onChange={(_e, d) => edit.set('dir', d.value === '' ? null : d.value)}
            />
          }
        />
        <FieldRow
          htmlFor={`${idBase}-poll`}
          label={t('hotfolder.pollLabel')}
          help={t('hotfolder.pollHint')}
          control={
            <NumberInput
              id={`${idBase}-poll`}
              value={v.poll_s}
              min={0.5}
              max={60}
              step={0.5}
              unit={t('units.seconds')}
              onChange={(n) => edit.set('poll_s', n)}
            />
          }
        />
        <FieldRow
          htmlFor={`${idBase}-settle`}
          label={t('hotfolder.settleLabel')}
          help={t('hotfolder.settleHint')}
          control={
            <NumberInput
              id={`${idBase}-settle`}
              value={v.settle_s}
              min={0}
              max={60}
              step={0.5}
              unit={t('units.seconds')}
              onChange={(n) => edit.set('settle_s', n)}
            />
          }
        />
        <FieldRow
          htmlFor={`${idBase}-max`}
          label={t('hotfolder.maxBytesLabel')}
          help={t('hotfolder.maxBytesHint')}
          control={
            <NumberInput
              id={`${idBase}-max`}
              value={Math.round(v.max_bytes / 1000)}
              min={1}
              max={50000}
              integer
              unit={t('units.kilobytes')}
              onChange={(n) => edit.set('max_bytes', n * 1000)}
            />
          }
        />
      </FieldRows>
      {error ? (
        <MessageBar intent="error">
          <MessageBarBody>{error}</MessageBarBody>
        </MessageBar>
      ) : null}
    </Section>
  );
}
