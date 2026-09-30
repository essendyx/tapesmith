/** Karte für einen generischen Abschnitt aus `GET /settings`: Zeilen je Feld, Speichern/Verwerfen. */
import type { ReactNode } from 'react';
import { Button, MessageBar, MessageBarBody, Spinner, makeStyles, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { Section } from '../../components/Section';
import { translateOr } from '../../i18n';
import { useSettingsEdit } from './context';
import { useSaveSection } from './useSaveSection';
import { SettingFieldRow } from './fields/SettingFieldRow';
import { FieldRows } from '../../components/FieldRow';
import type { SettingsSection, TemplateSummary, TransportChoice } from '../../api/types';

const useStyles = makeStyles({
  actions: { display: 'flex', columnGap: tokens.spacingHorizontalS, alignItems: 'center' },
});

export function GenericSectionCard(props: {
  section: SettingsSection;
  searchTerm?: string;
  ports?: TransportChoice[];
  templates?: TemplateSummary[];
  before?: ReactNode;
  /** Überschreibt die Element-ID (Standard: `section.id`), z. B. um eine Kollision mit einer eigenen Karte zu vermeiden. */
  domId?: string;
  /** Überschreibt den Titel (Standard: übersetzter Server-Titel), z. B. für eine zweite Karte desselben Abschnitts. */
  titleOverride?: string;
  /** Beschreibung unter dem Titel. */
  description?: ReactNode;
}): JSX.Element | null {
  const { t } = useTranslation('einstellungen');
  const styles = useStyles();
  const edit = useSettingsEdit();
  const saveSection = useSaveSection();
  const { section } = props;
  const title = props.titleOverride ?? translateOr(`einstellungen:sections.${section.id}`, section.title);
  const term = (props.searchTerm ?? '').trim().toLowerCase();
  const fields = term
    ? section.fields.filter((f) => f.label.toLowerCase().includes(term) || f.key.toLowerCase().includes(term))
    : section.fields;
  if (term && fields.length === 0 && !props.before) return null;

  const keys = section.fields.map((f) => f.key);
  const changedKeys = keys.filter((k) => edit.isChanged(k));
  const dirty = changedKeys.length > 0;
  const saving = edit.savingSection === section.id;
  const error = edit.errorFor(section.id);

  const onSave = async () => {
    await saveSection(section, title);
  };

  return (
    <div id={props.domId ?? section.id}>
      <Section
        title={title}
        description={props.description}
        actions={
          dirty ? (
            <div className={styles.actions}>
              {saving ? <Spinner size="tiny" /> : null}
              <Button appearance="secondary" disabled={saving} onClick={() => edit.discard(keys)}>
                {t('generic.discard')}
              </Button>
              <Button appearance="primary" disabled={saving} onClick={() => void onSave()}>
                {t('generic.save')}
              </Button>
            </div>
          ) : undefined
        }
      >
        {props.before}
        {error ? (
          <MessageBar intent="error">
            <MessageBarBody>{error}</MessageBarBody>
          </MessageBar>
        ) : null}
        {fields.length > 0 ? (
          <FieldRows>
            {fields.map((field) => (
              <SettingFieldRow key={field.key} field={field} ports={props.ports} templates={props.templates} />
            ))}
          </FieldRows>
        ) : null}
      </Section>
    </div>
  );
}
