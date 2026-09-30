/** Karte „Familienseite“: freigegebene Vorlagen, Kopiengrenze. */
import { useId } from 'react';
import { MessageBar, MessageBarBody } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { FieldRow, FieldRows } from '../../components/FieldRow';
import { Section } from '../../components/Section';
import { CardActions } from './CardActions';
import { NumberInput } from './NumberInput';
import { TemplatePicker } from './TemplatePicker';
import type { AccessFamily, AccessJson } from './types';
import { useSectionEdit } from './useSectionEdit';
import { useAccessSave } from './useAccessSave';

export function FamilyCard(props: { data: AccessJson }): JSX.Element {
  const { t } = useTranslation('zugriff');
  const edit = useSectionEdit<AccessFamily>(props.data.family);
  const { save, saving, error } = useAccessSave();
  const v = edit.values;
  const idBase = useId();
  const title = t('family.title');

  const onSave = async () => {
    const ok = await save(edit.changes('family'), t('family.saveSuccess'));
    if (ok) edit.discard();
  };

  return (
    <Section
      id="familie"
      title={title}
      description={t('family.linkHint')}
      actions={
        edit.dirty ? (
          <CardActions title={title} dirty={edit.dirty} saving={saving} onSave={() => void onSave()} onDiscard={edit.discard} />
        ) : undefined
      }
    >
      <FieldRows>
        <TemplatePicker
          label={t('family.templatesLabel')}
          help={t('family.templatesHint')}
          available={props.data.family.available}
          saved={props.data.family.templates}
          value={v.templates}
          onChange={(templates) => edit.set('templates', templates)}
        />
        <FieldRow
          htmlFor={`${idBase}-copies`}
          label={t('family.maxCopiesLabel')}
          help={t('family.copyLimitHint')}
          control={
            <NumberInput
              id={`${idBase}-copies`}
              value={v.max_copies}
              min={1}
              max={20}
              integer
              unit={t('units.copies')}
              onChange={(n) => edit.set('max_copies', n)}
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
