/** Karte „Familienseite“: freigegebene Vorlagen, Kopiengrenze. */
import { Body1, Body1Strong, Button, Checkbox, Field, MessageBar, MessageBarBody, SpinButton, makeStyles, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { Section } from '../../components/Section';
import type { AccessFamily, AccessJson } from './types';
import { useSectionEdit } from './useSectionEdit';
import { useAccessSave } from './useAccessSave';

const useStyles = makeStyles({
  grid: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  // Eigene Gruppe statt Fluent-`Field`: mehrere Kontrollkästchen dürfen nicht dieselbe generierte
  // Kennung teilen (jedes Kästchen trägt seine eigene sichtbare Beschriftung).
  group: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXS },
  checks: { display: 'flex', flexDirection: 'column' },
});

function toggleTemplate(templates: string[], name: string, checked: boolean): string[] {
  if (checked) return templates.includes(name) ? templates : [...templates, name];
  return templates.filter((t) => t !== name);
}

export function FamilyCard(props: { data: AccessJson }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('zugriff');
  const edit = useSectionEdit<AccessFamily>(props.data.family);
  const { save, saving, error } = useAccessSave();
  const v = edit.values;

  const onSave = async () => {
    const ok = await save(edit.changes('family'), t('family.saveSuccess'));
    if (ok) edit.discard();
  };

  return (
    <Section
      id="familie"
      title={t('family.title')}
      actions={
        edit.dirty ? (
          <>
            <Button appearance="secondary" disabled={saving} onClick={edit.discard}>
              {t('common:actions.cancel')}
            </Button>
            <Button appearance="primary" disabled={saving} aria-busy={saving} onClick={() => void onSave()}>
              {t('common:actions.save')}
            </Button>
          </>
        ) : undefined
      }
    >
      <div className={styles.grid}>
        <div className={styles.group}>
          <Body1Strong>{t('family.templatesLabel')}</Body1Strong>
          <div className={styles.checks}>
            {props.data.family.available.map((a) => (
              <Checkbox
                key={a.name}
                label={a.description ? `${a.name} (${a.description})` : a.name}
                checked={v.templates.includes(a.name)}
                onChange={(_e, d) => edit.set('templates', toggleTemplate(v.templates, a.name, Boolean(d.checked)))}
              />
            ))}
          </div>
        </div>

        <Field label={t('family.maxCopiesLabel')}>
          <SpinButton
            value={v.max_copies}
            min={1}
            max={20}
            onChange={(_e, d) => {
              const n = d.value ?? (d.displayValue ? Number(d.displayValue) : null);
              if (n !== null && Number.isFinite(n)) edit.set('max_copies', Math.min(20, Math.max(1, Math.round(n))));
            }}
          />
        </Field>
        <Body1>{t('family.copyLimitHint')}</Body1>
        <Body1>{t('family.linkHint')}</Body1>

        {error ? (
          <MessageBar intent="error">
            <MessageBarBody>{error}</MessageBarBody>
          </MessageBar>
        ) : null}
      </div>
    </Section>
  );
}
