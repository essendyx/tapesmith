/** Druckoptionen: Kopien, Kette, Schnittmarken, Schneidpause. */
import { useId } from 'react';
import {
  Dropdown,
  Field,
  Option,
  SpinButton,
  Switch,
  makeStyles,
  tokens,
  type SpinButtonOnChangeData,
} from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import type { PrintOptions } from '../api/types';

/** Auswahl der Schneidpause: `null` = Standard, -1 = keine, 0 = bis „Weiter“, sonst Sekunden. */
const CUT_PAUSE_VALUES: (number | null)[] = [null, -1, 0, 5, 10, 30];

function cutPauseLabel(v: number | null, t: (key: string, opts?: Record<string, unknown>) => string): string {
  if (v === null) return t('printOptions.cutPauseDefault');
  if (v < 0) return t('printOptions.cutPauseNone');
  if (v === 0) return t('printOptions.cutPauseManual');
  return t('printOptions.cutPauseSeconds', { seconds: v });
}

function cutPauseKey(v: number | null): string {
  return v === null ? 'standard' : String(v);
}

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'flex-end',
    columnGap: tokens.spacingHorizontalXL,
    rowGap: tokens.spacingVerticalM,
  },
  copies: { width: '96px' },
  switchField: { paddingBottom: tokens.spacingVerticalXXS },
  dropdown: { minWidth: '150px' },
});

export function PrintOptionsBar(props: {
  value: PrintOptions;
  onChange: (v: PrintOptions) => void;
  showCutPause?: boolean;
  /** Kopien-Feld zeigen (Default ja); Serie/Import druckt je Zeile ein Label und blendet es aus. */
  showCopies?: boolean;
  maxCopies?: number;
}): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('components');
  const tt = (key: string, opts?: Record<string, unknown>) => String(t(key, opts));
  const { value, onChange } = props;
  const max = props.maxCopies ?? 50;
  const idBase = useId();
  const showCutPause = props.showCutPause ?? true;
  const showCopies = props.showCopies ?? true;

  const set = (patch: Partial<PrintOptions>) => onChange({ ...value, ...patch });

  const onCopies = (_e: unknown, data: SpinButtonOnChangeData) => {
    const raw = data.value ?? (data.displayValue !== undefined ? parseInt(data.displayValue, 10) : NaN);
    if (raw === null || Number.isNaN(raw)) return;
    set({ copies: Math.min(max, Math.max(1, Math.round(raw))) });
  };

  const selectedValue = CUT_PAUSE_VALUES.includes(value.cut_pause_s) ? value.cut_pause_s : null;

  return (
    <div className={styles.root} role="group" aria-label={t('printOptions.label')}>
      {showCopies ? (
        <Field label={t('printOptions.copies')}>
          <SpinButton className={styles.copies} min={1} max={max} value={value.copies} onChange={onCopies} />
        </Field>
      ) : null}
      <Field className={styles.switchField}>
        <Switch
          label={t('printOptions.chain')}
          checked={value.chain}
          onChange={(_e, d) => set({ chain: d.checked })}
        />
      </Field>
      {value.chain ? (
        <Field className={styles.switchField}>
          <Switch label={t('printOptions.cutMarks')} checked={value.cut_marks} onChange={(_e, d) => set({ cut_marks: d.checked })} />
        </Field>
      ) : null}
      {showCutPause ? (
        <Field label={t('printOptions.cutPause')} id={`${idBase}-cut`}>
          <Dropdown
            className={styles.dropdown}
            value={cutPauseLabel(selectedValue, tt)}
            selectedOptions={[cutPauseKey(selectedValue)]}
            onOptionSelect={(_e, data) => {
              const choice = CUT_PAUSE_VALUES.find((v) => cutPauseKey(v) === data.optionValue);
              if (choice !== undefined) set({ cut_pause_s: choice });
            }}
          >
            {CUT_PAUSE_VALUES.map((v) => (
              <Option key={cutPauseKey(v)} value={cutPauseKey(v)}>
                {cutPauseLabel(v, tt)}
              </Option>
            ))}
          </Dropdown>
        </Field>
      ) : null}
    </div>
  );
}
