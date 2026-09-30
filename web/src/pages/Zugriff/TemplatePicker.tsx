/**
 * Auswahl freigegebener Vorlagen (Familienseite, MQTT): Suchfeld, Anzahl der gewählten,
 * „Alle abwählen“ und eine Liste mit Kontrollkästchen in fester Höhe mit eigenem Scrollbereich.
 * Beim Öffnen stehen die schon gespeicherten Vorlagen oben; die Reihenfolge bleibt beim Anklicken
 * stehen, damit nichts unter dem Mauszeiger wegspringt.
 */
import { useId, useMemo, useState, type ReactNode } from 'react';
import { Body1, Button, Caption1, Checkbox, Input, makeStyles, tokens } from '@fluentui/react-components';
import { Search20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { FieldRow } from '../../components/FieldRow';
import type { AccessFamilyAvailable } from './types';

const useStyles = makeStyles({
  box: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS, minWidth: 0 },
  toolbar: {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalS,
    minWidth: 0,
  },
  search: { flex: '1 1 240px', maxWidth: '420px', minWidth: 0 },
  count: { color: tokens.colorNeutralForeground2, marginLeft: 'auto' },
  list: {
    maxHeight: '288px',
    overflowY: 'auto',
    overscrollBehavior: 'contain',
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorNeutralBackground1,
    paddingTop: tokens.spacingVerticalXS,
    paddingBottom: tokens.spacingVerticalXS,
    minWidth: 0,
  },
  item: {
    display: 'block',
    minWidth: 0,
    '& + &': { borderTop: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke3}` },
  },
  checkbox: { width: '100%', alignItems: 'flex-start' },
  label: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXXS, minWidth: 0, overflowWrap: 'anywhere' },
  name: { fontFamily: tokens.fontFamilyMonospace, fontSize: tokens.fontSizeBase200 },
  description: { color: tokens.colorNeutralForeground3 },
  empty: { color: tokens.colorNeutralForeground3, padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}` },
});

function toggle(templates: string[], name: string, checked: boolean): string[] {
  if (checked) return templates.includes(name) ? templates : [...templates, name];
  return templates.filter((t) => t !== name);
}

export function TemplatePicker(props: {
  label: string;
  help?: ReactNode;
  available: AccessFamilyAvailable[];
  value: string[];
  /** Gespeicherter Stand: diese Vorlagen stehen oben. */
  saved: string[];
  /** Text für die Anzahl, wenn nichts gewählt ist (z. B. „alle erlaubt“). */
  emptyCount?: string;
  onChange: (templates: string[]) => void;
}): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('zugriff');
  const labelId = useId();
  const [query, setQuery] = useState('');

  const ordered = useMemo(() => {
    const saved = new Set(props.saved);
    return [...props.available].sort((a, b) => Number(saved.has(b.name)) - Number(saved.has(a.name)));
  }, [props.available, props.saved]);

  const needle = query.trim().toLowerCase();
  const shown = needle
    ? ordered.filter((a) => a.name.toLowerCase().includes(needle) || a.description.toLowerCase().includes(needle))
    : ordered;
  const selected = props.value.filter((name) => props.available.some((a) => a.name === name)).length;
  const countText =
    selected === 0 && props.emptyCount
      ? props.emptyCount
      : t('picker.count', { selected, total: props.available.length });

  return (
    <FieldRow labelId={labelId} label={props.label} help={props.help} layout="stacked">
      <div className={styles.box}>
        <div className={styles.toolbar}>
          <Input
            className={styles.search}
            type="search"
            contentBefore={<Search20Regular aria-hidden="true" />}
            placeholder={t('picker.searchPlaceholder')}
            aria-label={t('picker.searchAria', { label: props.label })}
            value={query}
            onChange={(_e, d) => setQuery(d.value)}
          />
          <Body1 className={styles.count} aria-live="polite">
            {countText}
          </Body1>
          <Button
            appearance="secondary"
            disabled={selected === 0}
            aria-label={t('picker.clearAria', { label: props.label })}
            onClick={() => props.onChange([])}
          >
            {t('picker.clear')}
          </Button>
        </div>
        <div className={styles.list} role="group" aria-labelledby={labelId}>
          {shown.length === 0 ? (
            <Caption1 className={styles.empty}>{t('picker.noMatch', { query: query.trim() })}</Caption1>
          ) : (
            shown.map((a) => (
              <div className={styles.item} key={a.name}>
                <Checkbox
                  className={styles.checkbox}
                  label={
                    <span className={styles.label}>
                      <span className={styles.name}>{a.name}</span>{' '}
                      {a.description ? <Caption1 className={styles.description}>{a.description}</Caption1> : null}
                    </span>
                  }
                  checked={props.value.includes(a.name)}
                  onChange={(_e, d) => props.onChange(toggle(props.value, a.name, Boolean(d.checked)))}
                />
              </div>
            ))
          )}
        </div>
      </div>
    </FieldRow>
  );
}
