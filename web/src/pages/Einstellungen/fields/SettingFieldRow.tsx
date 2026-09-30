/** Erzeugt für ein Schema-Feld die passende Zeile (Zurück auf `FieldRow`, Steuerelement je Typ). */
import { useEffect, useId, useState } from 'react';
import { Input, Select, Textarea, makeStyles, tokens } from '@fluentui/react-components';
import { Dismiss16Regular, Folder16Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { useSettingsEdit } from '../context';
import { FieldRow, InlineAction, ToggleControl } from '../../../components/FieldRow';
import { hotkeyFromEvent } from '../format';
import { translateOr } from '../../../i18n';
import { isAppWindow, pickFolder } from '../../../platform';
import type { SettingField, TemplateSummary, TransportChoice } from '../../../api/types';
import { SshHostsEditor } from './SshHostsEditor';
import { TrayFavoritesEditor } from './TrayFavoritesEditor';
import { choiceValue } from './choiceValue';
import { formatNumberText, parseNumberText } from './numberText';

const useStyles = makeStyles({
  json: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXS },
  unit: { color: tokens.colorNeutralForeground2, whiteSpace: 'nowrap' },
});

function domId(key: string): string {
  return `field-${key.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
}

/** `app.language` -> `app_language` (Unterstrich statt Punkt, wie für Übersetzungsschlüssel gefordert). */
function fieldNsKey(key: string): string {
  return key.replace(/\./g, '_');
}

function fieldLabel(field: SettingField): string {
  return translateOr(`einstellungen:fields.${fieldNsKey(field.key)}.label`, field.label);
}

function fieldHelp(field: SettingField): string {
  return field.help ? translateOr(`einstellungen:fields.${fieldNsKey(field.key)}.help`, field.help) : '';
}

function choiceLabel(field: SettingField, value: string | number | null, fallback: string): string {
  const choiceKey = value === null ? 'none' : String(value);
  return translateOr(`einstellungen:fields.${fieldNsKey(field.key)}.choices.${choiceKey}`, fallback);
}

function BoolControl(props: { id: string; value: unknown; onChange: (v: boolean) => void }): JSX.Element {
  return <ToggleControl id={props.id} checked={Boolean(props.value)} onChange={props.onChange} />;
}

function clampToField(field: SettingField, n: number): number {
  let clamped = n;
  if (typeof field.min === 'number') clamped = Math.max(field.min, clamped);
  if (typeof field.max === 'number') clamped = Math.min(field.max, clamped);
  return field.type === 'int' ? Math.round(clamped) : clamped;
}

/** Einheit im Eingabefeld, übersetzt (`einstellungen:units.<einheit>`). */
export function UnitText(props: { unit?: string | null; id?: string }): JSX.Element | null {
  const styles = useStyles();
  if (!props.unit) return null;
  return (
    <span id={props.id} className={styles.unit}>
      {translateOr(`einstellungen:units.${props.unit}`, props.unit)}
    </span>
  );
}

/**
 * Zahlenfeld mit Einheit im Feld (wie „Gemessene Länge“): Text mit Komma oder Punkt, Pfeiltasten
 * zählen um `step` weiter, beim Verlassen wird auf die Grenzen geklemmt.
 */
function NumberControl(props: { id: string; field: SettingField; value: unknown; onChange: (v: number | null) => void }): JSX.Element {
  const { t, i18n } = useTranslation('einstellungen');
  const { field } = props;
  const lang = i18n.language;
  const current = typeof props.value === 'number' ? props.value : null;
  const [text, setText] = useState(() => formatNumberText(current, lang));
  const [editing, setEditing] = useState(false);
  const unitId = `${props.id}-einheit`;
  useEffect(() => {
    if (!editing) setText(formatNumberText(current, lang));
  }, [current, editing, lang]);
  const step = field.step ?? 1;
  const commit = (raw: string) => {
    const parsed = parseNumberText(raw);
    if (parsed === null) {
      if (field.nullable) props.onChange(null);
      else setText(formatNumberText(current, lang));
      return;
    }
    if (!Number.isFinite(parsed)) {
      setText(formatNumberText(current, lang));
      return;
    }
    const next = clampToField(field, parsed);
    props.onChange(next);
    setText(formatNumberText(next, lang));
  };
  return (
    <Input
      id={props.id}
      role="spinbutton"
      inputMode="decimal"
      aria-valuenow={current ?? undefined}
      aria-valuemin={field.min ?? undefined}
      aria-valuemax={field.max ?? undefined}
      aria-describedby={field.unit ? unitId : undefined}
      value={text}
      placeholder={emptyPlaceholder(field, t)}
      contentAfter={<UnitText unit={field.unit} id={unitId} />}
      onFocus={() => setEditing(true)}
      onBlur={(e) => {
        setEditing(false);
        commit(e.currentTarget.value);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter') commit(text);
        if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
        e.preventDefault();
        const base = parseNumberText(text);
        const start = base !== null && Number.isFinite(base) ? base : (current ?? field.min ?? 0);
        const next = clampToField(field, start + (e.key === 'ArrowUp' ? step : -step));
        setText(formatNumberText(next, lang));
        props.onChange(next);
      }}
      onChange={(_e, d) => {
        setText(d.value);
        const parsed = parseNumberText(d.value);
        if (parsed !== null && Number.isFinite(parsed)) props.onChange(parsed);
      }}
    />
  );
}

function ChoiceControl(props: {
  id: string;
  field: SettingField;
  value: unknown;
  ports?: TransportChoice[];
  onChange: (v: unknown) => void;
}): JSX.Element {
  const { field } = props;
  if (field.key === 'transport') {
    const listId = `${props.id}-liste`;
    return (
      <>
        <Input id={props.id} list={listId} value={String(props.value ?? '')} onChange={(_e, d) => props.onChange(d.value)} />
        <datalist id={listId}>
          {(props.ports ?? []).map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </datalist>
      </>
    );
  }
  const current = props.value === null || props.value === undefined ? '' : String(props.value);
  return (
    <Select id={props.id} value={current} onChange={(_e, d) => props.onChange(choiceValue(field, d.value))}>
      {(field.choices ?? []).map((c) => (
        <option key={String(c.value)} value={c.value === null ? '' : String(c.value)}>
          {choiceLabel(field, c.value, c.label)}
        </option>
      ))}
    </Select>
  );
}

function valueToText(value: unknown): string {
  return value === null || value === undefined ? '' : String(value);
}

/** Platzhalter für leere Textfelder: der Standardwert, falls bekannt, sonst „Nicht gesetzt“. */
function emptyPlaceholder(field: SettingField, t: (key: string, opts?: Record<string, unknown>) => string): string {
  const fallback = field.default;
  if (typeof fallback === 'string' && fallback.trim() !== '') return t('field.defaultValue', { value: fallback });
  if (typeof fallback === 'number') return t('field.defaultValue', { value: String(fallback) });
  return t('field.notSet');
}

function StringControl(props: { id: string; field: SettingField; value: unknown; onChange: (v: string | null) => void }): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const { field } = props;
  const text = valueToText(props.value);
  const chooseFolder = async () => {
    const picked = await pickFolder(fieldLabel(field));
    if (picked) props.onChange(picked);
  };
  const canPick = field.type === 'path' && isAppWindow();
  const canReset = field.nullable && props.value !== null && props.value !== undefined && props.value !== '';
  const after =
    canPick || canReset ? (
      <>
        {canPick ? <InlineAction label={t('field.chooseFolder')} icon={<Folder16Regular />} onClick={() => void chooseFolder()} /> : null}
        {canReset ? <InlineAction label={t('field.reset')} icon={<Dismiss16Regular />} onClick={() => props.onChange(null)} /> : null}
      </>
    ) : undefined;
  return (
    <Input
      id={props.id}
      value={text}
      placeholder={emptyPlaceholder(field, t)}
      title={text || undefined}
      contentAfter={after}
      onChange={(_e, d) => props.onChange(d.value)}
    />
  );
}

function HotkeyControl(props: { id: string; value: unknown; onChange: (v: string) => void }): JSX.Element {
  const { t } = useTranslation('einstellungen');
  return (
    <Input
      id={props.id}
      value={valueToText(props.value)}
      placeholder={t('field.hotkeyPlaceholder')}
      onKeyDown={(e) => {
        const combo = hotkeyFromEvent(e);
        if (combo) {
          e.preventDefault();
          props.onChange(combo);
        }
      }}
      onChange={() => {
        // Nur über Tastendruck (onKeyDown) änderbar, Freitext wird ignoriert.
      }}
    />
  );
}

function RawJsonControl(props: { id: string; value: unknown; onChange: (v: unknown) => void }): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const styles = useStyles();
  const [text, setText] = useState(() => JSON.stringify(props.value ?? null, null, 2));
  const [error, setError] = useState<string | null>(null);
  return (
    <div id={props.id} className={styles.json}>
      <Textarea
        value={text}
        rows={4}
        resize="vertical"
        onChange={(_e, d) => setText(d.value)}
        onBlur={() => {
          try {
            props.onChange(JSON.parse(text));
            setError(null);
          } catch {
            setError(t('field.invalidJson'));
          }
        }}
      />
      {error ? <span role="alert">{error}</span> : null}
    </div>
  );
}

function JsonControl(props: {
  id: string;
  field: SettingField;
  value: unknown;
  templates: TemplateSummary[];
  onChange: (v: unknown) => void;
}): JSX.Element {
  const { field } = props;
  if (field.key === 'ssh.hosts') {
    return <SshHostsEditor fieldId={props.id} value={props.value} onChange={props.onChange} />;
  }
  if (field.key === 'tray.favorites') {
    return <TrayFavoritesEditor fieldId={props.id} value={props.value} templates={props.templates} onChange={props.onChange} />;
  }
  return <RawJsonControl id={props.id} value={props.value} onChange={props.onChange} />;
}

export function SettingFieldRow(props: {
  field: SettingField;
  ports?: TransportChoice[];
  templates?: TemplateSummary[];
}): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const edit = useSettingsEdit();
  const reactId = useId();
  const { field } = props;
  const id = domId(`${field.key}-${reactId}`);
  const value = edit.isChanged(field.key) ? edit.pending[field.key] : field.value;
  const onChange = (v: unknown) => edit.setValue(field.key, v);
  const common = {
    label: fieldLabel(field),
    help: fieldHelp(field),
    experimental: field.experimental,
    restart: field.restart,
  };

  if (field.type === 'json') {
    // Listen-Editoren in voller Breite unter der Beschriftung.
    const help = common.help || (field.key === 'ssh.hosts' ? t('sshHosts.hint') : '');
    return (
      <FieldRow {...common} help={help} layout="stacked">
        <JsonControl id={id} field={field} value={value} templates={props.templates ?? []} onChange={onChange} />
      </FieldRow>
    );
  }

  let control: JSX.Element;
  switch (field.type) {
    case 'bool':
      control = <BoolControl id={id} value={value} onChange={onChange} />;
      break;
    case 'int':
    case 'float':
      control = <NumberControl id={id} field={field} value={value} onChange={onChange} />;
      break;
    case 'choice':
      control = <ChoiceControl id={id} field={field} value={value} ports={props.ports} onChange={onChange} />;
      break;
    case 'hotkey':
      control = <HotkeyControl id={id} value={value} onChange={onChange} />;
      break;
    default:
      control = <StringControl id={id} field={field} value={value} onChange={onChange} />;
      break;
  }

  return <FieldRow {...common} htmlFor={id} align={field.type === 'bool' ? 'end' : 'fill'} control={control} />;
}
