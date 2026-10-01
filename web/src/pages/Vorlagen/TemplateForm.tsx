/** Formular aus den Vorlagenfeldern: Eingabefelder editierbar, berechnete Felder lesend. */
import { useId, useState } from 'react';
import {
  Button,
  Combobox,
  Field,
  Input,
  Option,
  Textarea,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Eye20Regular, EyeOff20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import type { FieldJson } from '../../api/types';
import { TextSizeSelect } from '../../components/TextSizeSelect';
import { templateFieldId } from './templateText';

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalL },
  /** Alle Eingaben gleich breit (volle Formularbreite), auch Combobox/Dropdown mit eigener Mindestbreite. */
  control: { width: '100%', minWidth: 0, maxWidth: '100%' },
  textarea: { width: '100%' },
  passwordRow: { display: 'flex', columnGap: tokens.spacingHorizontalXS, alignItems: 'center' },
});

function SecretInput(props: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  onBlur?: () => void;
  maxLen: number | null;
}): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('vorlagen');
  const [visible, setVisible] = useState(false);
  return (
    <div className={styles.passwordRow}>
      <Input
        id={props.id}
        type={visible ? 'text' : 'password'}
        value={props.value}
        maxLength={props.maxLen ?? undefined}
        onChange={(_e, d) => props.onChange(d.value)}
        onBlur={props.onBlur}
        style={{ flexGrow: 1, minWidth: 0 }}
      />
      <Button
        appearance="subtle"
        icon={visible ? <EyeOff20Regular /> : <Eye20Regular />}
        aria-label={visible ? t('form.secretHide') : t('form.secretShow')}
        aria-pressed={visible}
        onClick={() => setVisible((v) => !v)}
      />
    </div>
  );
}

export function TemplateForm(props: {
  fields: FieldJson[];
  values: Record<string, string>;
  computed: Record<string, string> | null;
  onChange: (id: string, value: string) => void;
  /** Feld verlassen (für Pflichtfeld-Hinweise erst nach der ersten Eingabe). */
  onBlur?: (id: string) => void;
  /** Fehlertext je Feld-ID; nur gesetzte Einträge werden am Feld gezeigt. */
  errors?: Record<string, string>;
  /** Präfix der Element-IDs (Standard: eigene ID), siehe `templateFieldId`. */
  idPrefix?: string;
  /** Feld „Schriftgröße“ (role text_size) nicht hier zeigen (die Seite zeigt es bei den Druckoptionen). */
  omitTextSize?: boolean;
  /** Beispiel je Feld als Platzhalter (z. B. „Max Mustermann“). */
  samples?: Record<string, string>;
}): JSX.Element {
  const styles = useStyles();
  const { t, i18n } = useTranslation('vorlagen');
  const ownId = useId();
  const idBase = props.idPrefix ?? ownId;
  const numberFormat = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 4 });
  /** Platzhalter für leere Felder: Standardwert (z. B. „Standard: 15,875“), sonst das Beispiel („z. B. Max Mustermann“). */
  const hintFor = (field: FieldJson): string | undefined => {
    if (field.default_hint) {
      const n = Number(field.default_hint);
      return t('form.defaultHint', { value: Number.isFinite(n) ? numberFormat.format(n) : field.default_hint });
    }
    const sample = props.samples?.[field.id];
    return sample ? t('form.sampleHint', { value: sample }) : undefined;
  };
  const { values, computed, onChange, errors } = props;
  const fields = props.omitTextSize ? props.fields.filter((f) => f.role !== 'text_size') : props.fields;
  const blur = (id: string) => () => props.onBlur?.(id);
  const validation = (id: string) =>
    errors?.[id] ? { validationState: 'error' as const, validationMessage: errors[id] } : {};

  return (
    <div className={styles.root} data-testid="template-form">
      {fields.map((field) => {
        const fieldId = templateFieldId(idBase, field.id);
        if (field.type !== 'input') {
          const text = computed?.[field.id] ?? '';
          return (
            <Field key={field.id} label={field.label} hint={t('form.computedHint')}>
              <Input id={fieldId} className={styles.control} value={text} readOnly appearance="filled-darker" />
            </Field>
          );
        }
        const value = values[field.id] ?? '';
        // Den Pflicht-Stern setzt Fluent über `required` selbst (sonst stünde „* *“ da).
        const label = field.label;
        if (field.role === 'text_size') {
          return (
            <Field key={field.id} label={t('components:textSize.label')}>
              <TextSizeSelect id={fieldId} value={value} choices={field.choices} onChange={(v) => onChange(field.id, v)} />
            </Field>
          );
        }
        if (field.secret) {
          return (
            <Field key={field.id} label={label} required={field.required} {...validation(field.id)}>
              <SecretInput
                id={fieldId}
                value={value}
                maxLen={field.max_len}
                onChange={(v) => onChange(field.id, v)}
                onBlur={blur(field.id)}
              />
            </Field>
          );
        }
        if (field.multiline) {
          return (
            <Field key={field.id} label={label} required={field.required} {...validation(field.id)}>
              <Textarea
                id={fieldId}
                className={styles.textarea}
                rows={4}
                value={value}
                placeholder={hintFor(field)}
                maxLength={field.max_len ?? undefined}
                resize="vertical"
                onChange={(_e, d) => onChange(field.id, d.value)}
                onBlur={blur(field.id)}
              />
            </Field>
          );
        }
        if (field.choices.length > 0) {
          const choiceLabel = (c: string): string => field.choice_labels?.[c] ?? c;
          return (
            <Field key={field.id} label={label} required={field.required} {...validation(field.id)}>
              <Combobox
                id={fieldId}
                className={styles.control}
                freeform
                value={choiceLabel(value)}
                placeholder={hintFor(field)}
                selectedOptions={value ? [value] : []}
                onOptionSelect={(_e, d) => onChange(field.id, d.optionValue ?? d.optionText ?? '')}
                onInput={(e) => onChange(field.id, (e.target as HTMLInputElement).value)}
                onBlur={blur(field.id)}
              >
                {field.choices.map((c) => (
                  <Option key={c} value={c} text={choiceLabel(c)}>
                    {choiceLabel(c)}
                  </Option>
                ))}
              </Combobox>
            </Field>
          );
        }
        return (
          <Field key={field.id} label={label} required={field.required} {...validation(field.id)}>
            <Input
              id={fieldId}
              className={styles.control}
              value={value}
              placeholder={hintFor(field)}
              maxLength={field.max_len ?? undefined}
              onChange={(_e, d) => onChange(field.id, d.value)}
              onBlur={blur(field.id)}
            />
          </Field>
        );
      })}
    </div>
  );
}
