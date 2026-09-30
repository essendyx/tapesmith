/**
 * Zahlenfeld der Zugriffsseite im Stil der Einstellungen: Einheit im Feld, Komma oder Punkt,
 * Pfeiltasten zählen um `step` weiter, beim Verlassen und mit Enter wird auf die Grenzen geklemmt.
 */
import { useEffect, useState } from 'react';
import { Input, makeStyles, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { formatNumberText, parseNumberText } from '../Einstellungen/fields/numberText';

const useStyles = makeStyles({
  unit: { color: tokens.colorNeutralForeground2, whiteSpace: 'nowrap' },
});

export function NumberInput(props: {
  id: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  /** Ganzzahl erzwingen (Port, Minuten, Kopien). */
  integer?: boolean;
  /** Bereits übersetzte Einheit, steht rechts im Feld. */
  unit?: string;
  onChange: (value: number) => void;
}): JSX.Element {
  const styles = useStyles();
  const { i18n } = useTranslation();
  const lang = i18n.language;
  const [text, setText] = useState(() => formatNumberText(props.value, lang));
  const [editing, setEditing] = useState(false);
  const unitId = `${props.id}-einheit`;
  const step = props.step ?? 1;

  useEffect(() => {
    if (!editing) setText(formatNumberText(props.value, lang));
  }, [props.value, editing, lang]);

  const clamp = (n: number): number => {
    const bounded = Math.min(props.max, Math.max(props.min, n));
    return props.integer ? Math.round(bounded) : Math.round(bounded * 1000) / 1000;
  };

  const commit = (raw: string) => {
    const parsed = parseNumberText(raw);
    if (parsed === null || !Number.isFinite(parsed)) {
      setText(formatNumberText(props.value, lang));
      return;
    }
    const next = clamp(parsed);
    props.onChange(next);
    setText(formatNumberText(next, lang));
  };

  return (
    <Input
      id={props.id}
      role="spinbutton"
      inputMode={props.integer ? 'numeric' : 'decimal'}
      aria-valuenow={props.value}
      aria-valuemin={props.min}
      aria-valuemax={props.max}
      aria-describedby={props.unit ? unitId : undefined}
      value={text}
      contentAfter={
        props.unit ? (
          <span id={unitId} className={styles.unit}>
            {props.unit}
          </span>
        ) : undefined
      }
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
        const start = base !== null && Number.isFinite(base) ? base : props.value;
        const next = clamp(start + (e.key === 'ArrowUp' ? step : -step));
        setText(formatNumberText(next, lang));
        props.onChange(next);
      }}
      onChange={(_e, d) => {
        setText(d.value);
        const parsed = parseNumberText(d.value);
        if (parsed !== null && Number.isFinite(parsed) && parsed >= props.min && parsed <= props.max) {
          props.onChange(props.integer ? Math.round(parsed) : parsed);
        }
      }}
    />
  );
}
