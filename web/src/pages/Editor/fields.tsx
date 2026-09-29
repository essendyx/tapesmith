/** Kleine Formularbausteine des Eigenschaften-Panels (entprellt, Fluent v9). */
import {
  Checkbox,
  Dropdown,
  Field,
  Input,
  Option,
  SpinButton,
  Switch,
  Textarea,
  makeStyles,
  tokens,
  type SpinButtonOnChangeData,
} from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { useDraft } from './useDraft';

const useStyles = makeStyles({
  numberRow: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalS },
  spin: { width: '100%', minWidth: '72px' },
  hint: { color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200, whiteSpace: 'nowrap' },
});

export function TextField(props: {
  label: string;
  value: string;
  onCommit: (v: string) => void;
  multiline?: boolean;
  maxLines?: number;
  hint?: string;
  placeholder?: string;
}): JSX.Element {
  const [draft, change, flush] = useDraft(props.value, props.onCommit);
  const maxLines = props.maxLines ?? 1;
  return (
    <Field label={props.label} hint={props.hint}>
      {props.multiline ? (
        <Textarea
          value={draft}
          resize="vertical"
          rows={Math.min(3, Math.max(2, draft.split('\n').length))}
          placeholder={props.placeholder}
          onChange={(_e, d) => {
            if (d.value.split('\n').length > maxLines) return;
            change(d.value);
          }}
          onBlur={flush}
        />
      ) : (
        <Input value={draft} placeholder={props.placeholder} onChange={(_e, d) => change(d.value)} onBlur={flush} />
      )}
    </Field>
  );
}

function clamp(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v));
}

/** Zahl mit Grenzen; `auto` erlaubt „leer“ (null) über ein Kästchen. `unitHint` zeigt z. B. mm neben Punkten. */
export function NumberField(props: {
  label: string;
  value: number | null;
  min: number;
  max: number;
  step?: number;
  onCommit: (v: number | null) => void;
  auto?: { label: string; fallback: number };
  unitHint?: (v: number) => string;
  disabled?: boolean;
}): JSX.Element {
  const styles = useStyles();
  const [draft, change] = useDraft<number | null>(props.value, props.onCommit);
  const onSpin = (_e: unknown, data: SpinButtonOnChangeData) => {
    const raw = data.value ?? (data.displayValue !== undefined ? parseFloat(data.displayValue.replace(',', '.')) : NaN);
    if (raw === null || raw === undefined || Number.isNaN(raw)) return;
    change(clamp(raw, props.min, props.max));
  };
  const isAuto = props.auto !== undefined && draft === null;
  return (
    <Field label={props.label}>
      <div className={styles.numberRow}>
        {isAuto ? null : (
          <SpinButton
            className={styles.spin}
            value={draft ?? props.min}
            min={props.min}
            max={props.max}
            step={props.step ?? 1}
            disabled={props.disabled}
            onChange={onSpin}
          />
        )}
        {props.auto ? (
          <Checkbox
            label={props.auto.label}
            checked={isAuto}
            disabled={props.disabled}
            onChange={(_e, d) => change(d.checked ? null : props.auto!.fallback)}
          />
        ) : null}
        {props.unitHint && draft !== null ? <span className={styles.hint}>{props.unitHint(draft)}</span> : null}
      </div>
    </Field>
  );
}

export function ChoiceField<T extends string | number>(props: {
  label: string;
  value: T | null;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  placeholder?: string;
  disabled?: boolean;
}): JSX.Element {
  const { t } = useTranslation('editor');
  const selected = props.options.find((o) => o.value === props.value);
  return (
    <Field label={props.label}>
      <Dropdown
        value={selected?.label ?? ''}
        placeholder={props.placeholder ?? t('fields.mixedPlaceholder')}
        selectedOptions={selected ? [String(selected.value)] : []}
        disabled={props.disabled}
        onOptionSelect={(_e, d) => {
          const choice = props.options.find((o) => String(o.value) === d.optionValue);
          if (choice) props.onChange(choice.value);
        }}
      >
        {props.options.map((o) => (
          <Option key={String(o.value)} value={String(o.value)}>
            {o.label}
          </Option>
        ))}
      </Dropdown>
    </Field>
  );
}

export function SwitchField(props: { label: string; checked: boolean | null; onChange: (v: boolean) => void; disabled?: boolean }): JSX.Element {
  const { t } = useTranslation('editor');
  return (
    <Switch
      label={props.checked === null ? t('fields.mixed', { label: props.label }) : props.label}
      checked={props.checked ?? false}
      disabled={props.disabled}
      onChange={(_e, d) => props.onChange(d.checked)}
    />
  );
}
