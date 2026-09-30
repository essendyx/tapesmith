/** Karte „Hotfolder“: Ordnerüberwachung mit Zeitgrenzen. */
import { Button, Field, Input, MessageBar, MessageBarBody, SpinButton, Switch, makeStyles, tokens } from '@fluentui/react-components';
import { FolderOpen20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { Section } from '../../components/Section';
import { isAppWindow, openPath } from '../../platform';
import type { AccessHotfolder, AccessJson } from './types';
import { useSectionEdit } from './useSectionEdit';
import { useAccessSave } from './useAccessSave';

const useStyles = makeStyles({
  grid: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  row: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalS },
});

function numberFrom(value: number | null | undefined, displayValue: string | undefined): number | null {
  if (value !== undefined && value !== null) return value;
  const raw = (displayValue ?? '').trim().replace(',', '.');
  return raw === '' ? null : Number(raw);
}

export function HotfolderCard(props: { data: AccessJson }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('zugriff');
  const edit = useSectionEdit<AccessHotfolder>(props.data.hotfolder);
  const { save, saving, error } = useAccessSave();
  const v = edit.values;

  const onSave = async () => {
    const ok = await save(edit.changes('hotfolder'), t('hotfolder.saveSuccess'));
    if (ok) edit.discard();
  };

  return (
    <Section
      id="hotfolder"
      title={t('hotfolder.title')}
      actions={
        edit.dirty ? (
          <>
            <Button appearance="primary" disabled={saving} aria-busy={saving} onClick={() => void onSave()}>
              {t('common:actions.save')}
            </Button>
            <Button appearance="secondary" disabled={saving} onClick={edit.discard}>
              {t('common:actions.cancel')}
            </Button>
          </>
        ) : undefined
      }
    >
      <div className={styles.grid}>
        <Field label={t('hotfolder.enableLabel')}>
          <Switch checked={v.enabled} onChange={(_e, d) => edit.set('enabled', d.checked)} />
        </Field>

        <Field label={t('hotfolder.dirLabel')} hint={t('hotfolder.dirHint')}>
          <div className={styles.row}>
            <Input
              value={v.dir ?? ''}
              placeholder={props.data.hotfolder.effective_dir}
              onChange={(_e, d) => edit.set('dir', d.value === '' ? null : d.value)}
            />
            {isAppWindow() ? (
              <Button icon={<FolderOpen20Regular />} onClick={() => void openPath(props.data.hotfolder.effective_dir)}>
                {t('hotfolder.openDir')}
              </Button>
            ) : null}
          </div>
        </Field>

        <Field label={t('hotfolder.pollLabel')}>
          <SpinButton
            value={v.poll_s}
            min={0.5}
            max={60}
            step={0.5}
            onChange={(_e, d) => {
              const n = numberFrom(d.value, d.displayValue);
              if (n !== null && Number.isFinite(n)) edit.set('poll_s', Math.min(60, Math.max(0.5, n)));
            }}
          />
        </Field>

        <Field label={t('hotfolder.settleLabel')}>
          <SpinButton
            value={v.settle_s}
            min={0}
            max={60}
            step={0.5}
            onChange={(_e, d) => {
              const n = numberFrom(d.value, d.displayValue);
              if (n !== null && Number.isFinite(n)) edit.set('settle_s', Math.min(60, Math.max(0, n)));
            }}
          />
        </Field>

        <Field label={t('hotfolder.maxBytesLabel')}>
          <SpinButton
            value={Math.round(v.max_bytes / 1000)}
            min={1}
            max={50000}
            onChange={(_e, d) => {
              const n = numberFrom(d.value, d.displayValue);
              if (n !== null && Number.isFinite(n)) edit.set('max_bytes', Math.round(Math.min(50000, Math.max(1, n)) * 1000));
            }}
          />
        </Field>

        {error ? (
          <MessageBar intent="error">
            <MessageBarBody>{error}</MessageBarBody>
          </MessageBar>
        ) : null}
      </div>
    </Section>
  );
}
