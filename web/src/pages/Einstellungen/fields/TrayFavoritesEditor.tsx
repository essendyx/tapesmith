/** JSON-Editor für `tray.favorites`: Tabelle Titel, Vorlage, feste Werte als „feld=wert“-Liste. */
import { Body1, Button, Input, makeStyles, Select, tokens } from '@fluentui/react-components';
import { Add20Regular, Delete20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import type { TemplateSummary } from '../../../api/types';
import { TableScroll } from '../../../components/TableScroll';

export interface TrayFavoriteRow {
  title: string;
  template: string;
  values: Record<string, string>;
}

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', alignItems: 'flex-start', rowGap: tokens.spacingVerticalS, width: '100%' },
  table: { width: '100%', minWidth: '520px', borderCollapse: 'collapse', tableLayout: 'fixed' },
  th: {
    textAlign: 'left',
    fontWeight: tokens.fontWeightRegular,
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
    paddingBottom: tokens.spacingVerticalXS,
    paddingRight: tokens.spacingHorizontalS,
  },
  td: { paddingRight: tokens.spacingHorizontalS, paddingBottom: tokens.spacingVerticalS, verticalAlign: 'middle' },
  tdLast: { paddingRight: 0, paddingBottom: tokens.spacingVerticalS, verticalAlign: 'middle', textAlign: 'right' },
  input: { width: '100%', minWidth: 0 },
  colTitle: { width: '28%' },
  colTemplate: { width: '28%' },
  colAction: { width: '40px' },
  empty: { color: tokens.colorNeutralForeground3 },
});

function isFavoriteArray(value: unknown): value is TrayFavoriteRow[] {
  return Array.isArray(value);
}

function valuesToText(values: Record<string, string> | undefined): string {
  return Object.entries(values ?? {})
    .map(([k, v]) => `${k}=${v}`)
    .join(', ');
}

function textToValues(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of text.split(',')) {
    const piece = part.trim();
    if (!piece) continue;
    const eq = piece.indexOf('=');
    if (eq < 0) continue;
    out[piece.slice(0, eq).trim()] = piece.slice(eq + 1).trim();
  }
  return out;
}

function emptyRow(): TrayFavoriteRow {
  return { title: '', template: '', values: {} };
}

export function TrayFavoritesEditor(props: {
  fieldId: string;
  value: unknown;
  templates: TemplateSummary[];
  onChange: (rows: TrayFavoriteRow[]) => void;
}): JSX.Element {
  const { t } = useTranslation('einstellungen');
  const styles = useStyles();
  const rows = isFavoriteArray(props.value) ? props.value : [];

  const update = (index: number, patch: Partial<TrayFavoriteRow>) => {
    props.onChange(rows.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  };
  const remove = (index: number) => props.onChange(rows.filter((_, i) => i !== index));
  const add = () => props.onChange([...rows, emptyRow()]);

  return (
    <div className={styles.root} id={props.fieldId}>
      {rows.length > 0 ? (
        <TableScroll label={t('trayFavorites.tableAria')}>
        <table className={styles.table}>
          <colgroup>
            <col className={styles.colTitle} />
            <col className={styles.colTemplate} />
            <col />
            <col className={styles.colAction} />
          </colgroup>
          <thead>
            <tr>
              <th className={styles.th}>{t('trayFavorites.title')}</th>
              <th className={styles.th}>{t('trayFavorites.template')}</th>
              <th className={styles.th}>{t('trayFavorites.values')}</th>
              <th className={styles.th} />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                <td className={styles.td}>
                  <Input className={styles.input} value={row.title} aria-label={t('trayFavorites.title')} onChange={(_e, d) => update(i, { title: d.value })} />
                </td>
                <td className={styles.td}>
                  {props.templates.length > 0 ? (
                    <Select
                      className={styles.input}
                      aria-label={t('trayFavorites.template')}
                      value={row.template}
                      onChange={(_e, d) => update(i, { template: d.value })}
                    >
                      <option value="">{t('trayFavorites.none')}</option>
                      {props.templates.map((tpl) => (
                        <option key={tpl.name} value={tpl.name}>
                          {tpl.name}
                        </option>
                      ))}
                    </Select>
                  ) : (
                    <Input className={styles.input} value={row.template} aria-label={t('trayFavorites.template')} onChange={(_e, d) => update(i, { template: d.value })} />
                  )}
                </td>
                <td className={styles.td}>
                  <Input
                    className={styles.input}
                    value={valuesToText(row.values)}
                    aria-label={t('trayFavorites.values')}
                    placeholder={t('trayFavorites.valuesPlaceholder')}
                    onChange={(_e, d) => update(i, { values: textToValues(d.value) })}
                  />
                </td>
                <td className={styles.tdLast}>
                  <Button
                    appearance="subtle"
                    icon={<Delete20Regular />}
                    aria-label={t('field.removeRow', { row: i + 1 })}
                    onClick={() => remove(i)}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </TableScroll>
      ) : (
        <Body1 className={styles.empty}>{t('trayFavorites.empty')}</Body1>
      )}
      <Button appearance="secondary" icon={<Add20Regular />} onClick={add}>
        {t('field.addRow')}
      </Button>
    </div>
  );
}
