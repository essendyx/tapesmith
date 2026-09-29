/** Auswahl der Schriftgröße: automatisch (einheitlich), automatisch je Feld (nur Raster) oder feste Texthöhe in mm. */
import { Dropdown, Option, makeStyles } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';

/** Kanonische Werte wie im Backend (`render/textsize.py`). */
export const TEXT_SIZE_AUTO = 'auto';
export const TEXT_SIZE_AUTO_FIELD = 'auto-feld';
export const TEXT_SIZE_FIXED_MM: readonly string[] = ['2', '2.5', '3', '3.5', '4', '4.5', '5', '6', '7', '8', '9'];

const useStyles = makeStyles({
  root: { width: '100%', minWidth: 0 },
});

export function useTextSizeLabel(perField: boolean): (value: string) => string {
  const { t, i18n } = useTranslation('components');
  const format = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 });
  return (value: string) => {
    if (value === TEXT_SIZE_AUTO || value === '') return perField ? t('textSize.autoUniform') : t('textSize.auto');
    if (value === TEXT_SIZE_AUTO_FIELD) return t('textSize.autoField');
    const n = Number(value.replace(',', '.'));
    return Number.isFinite(n) ? t('textSize.mm', { value: format.format(n) }) : value;
  };
}

export function TextSizeSelect(props: {
  id?: string;
  value: string;
  choices?: readonly string[];
  onChange: (value: string) => void;
  'aria-labelledby'?: string;
}): JSX.Element {
  const styles = useStyles();
  const choices = props.choices ?? [TEXT_SIZE_AUTO, ...TEXT_SIZE_FIXED_MM];
  const perField = choices.includes(TEXT_SIZE_AUTO_FIELD);
  const label = useTextSizeLabel(perField);
  const value = props.value || TEXT_SIZE_AUTO;
  return (
    <Dropdown
      id={props.id}
      className={styles.root}
      aria-labelledby={props['aria-labelledby']}
      value={label(value)}
      selectedOptions={[value]}
      onOptionSelect={(_e, d) => d.optionValue && props.onChange(d.optionValue)}
    >
      {choices.map((c) => (
        <Option key={c} value={c}>
          {label(c)}
        </Option>
      ))}
    </Dropdown>
  );
}
