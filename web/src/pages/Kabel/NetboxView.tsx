/** Reiter „NetBox-Import": CSV wählen, Spalten zuordnen, Vorschau, als Serie öffnen. */
import { useRef, useState } from 'react';
import {
  Button,
  Checkbox,
  Field,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { DocumentArrowUp20Regular, Open20Regular } from '@fluentui/react-icons';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { EmptyState } from '../../components/EmptyState';
import { ErrorMessage } from '../../components/ErrorMessage';
import { LoadingState } from '../../components/LoadingState';
import { readFileAsB64 } from '../../platform';
import { openNetboxSeries, previewNetbox } from './api';
import type { ColumnMapping, ColumnMappingValue, NetboxPreviewJson } from './types';
import { MAPPING_FIELDS } from './types';

const useStyles = makeStyles({
  col: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  toolbar: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalM, flexWrap: 'wrap' },
  // Datei-Eingabe nur für die Auswahl, sichtbar ist der übersetzte Knopf (der native Knopf spräche
  // die Sprache des Browsers statt der Oberfläche).
  visuallyHidden: {
    position: 'absolute',
    width: '1px',
    height: '1px',
    padding: 0,
    margin: '-1px',
    overflow: 'hidden',
    clip: 'rect(0, 0, 0, 0)',
    whiteSpace: 'nowrap',
    border: 0,
  },
  switches: { display: 'flex', columnGap: tokens.spacingHorizontalL, flexWrap: 'wrap' },
  mappingGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalS,
  },
  tableWrap: { overflowX: 'auto', maxWidth: '100%' },
  dup: { backgroundColor: tokens.colorPaletteRedBackground1 },
});

export function NetboxView(): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('kabel');
  const navigate = useNavigate();

  const [fileName, setFileName] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [csvB64, setCsvB64] = useState<string | null>(null);
  const [mapping, setMapping] = useState<ColumnMapping>({});
  const [preview, setPreview] = useState<NetboxPreviewJson | null>(null);
  const [assignIds, setAssignIds] = useState(false);
  const [saveMapping, setSaveMapping] = useState(false);
  const [registerRows, setRegisterRows] = useState(false);
  const [template, setTemplate] = useState<'kabelfahne' | 'kabelwickel'>('kabelfahne');
  const [loading, setLoading] = useState(false);
  const [opening, setOpening] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function load(csv: string, nextMapping: ColumnMapping | null): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const result = await previewNetbox(csv, nextMapping, assignIds, false);
      setPreview(result);
      setMapping(result.mapping);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }

  async function onFile(file: File): Promise<void> {
    const b64 = await readFileAsB64(file);
    setFileName(file.name);
    setCsvB64(b64);
    setPreview(null);
    await load(b64, null);
  }

  function editMapping(fieldId: string, value: ColumnMappingValue): void {
    const next = { ...mapping, [fieldId]: value };
    setMapping(next);
    if (csvB64) void load(csvB64, next);
  }

  async function reloadWithAssignIds(next: boolean): Promise<void> {
    setAssignIds(next);
    if (csvB64) {
      setLoading(true);
      setError(null);
      try {
        const result = await previewNetbox(csvB64, mapping, next, false);
        setPreview(result);
      } catch (err) {
        setError(err);
      } finally {
        setLoading(false);
      }
    }
  }

  async function openSeries(): Promise<void> {
    if (!csvB64) return;
    setOpening(true);
    setError(null);
    try {
      const result = await openNetboxSeries(csvB64, mapping, assignIds, template, registerRows);
      if (saveMapping) {
        // Die Zuordnung wird beim nächsten Vorschau-Aufruf serverseitig übernommen; hier reicht der
        // Hinweis über den Schalter, das eigentliche Speichern übernimmt die Vorschau-Route (`save_mapping`).
        await previewNetbox(csvB64, mapping, assignIds, true);
      }
      navigate(`/vorlagen?vorlage=${result.template}&import=${result.pending_id}`);
    } catch (err) {
      setError(err);
    } finally {
      setOpening(false);
    }
  }

  return (
    <div className={styles.col}>
      <div className={styles.toolbar}>
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,.txt"
          tabIndex={-1}
          className={styles.visuallyHidden}
          aria-label={t('netbox.uploadLabel')}
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = '';
            if (file) void onFile(file);
          }}
        />
        <Button icon={<DocumentArrowUp20Regular />} onClick={() => fileInputRef.current?.click()}>
          {t('netbox.chooseFile')}
        </Button>
        {fileName ? <span>{t('netbox.fileLabel', { name: fileName })}</span> : null}
        {loading ? <LoadingState variant="inline" label={t('netbox.loading')} /> : null}
      </div>

      {error ? <ErrorMessage error={error} /> : null}

      {preview ? (
        <>
          <div className={styles.mappingGrid}>
            {MAPPING_FIELDS.map((field) => {
              const value = mapping[field.id];
              const selected = value === undefined ? [] : Array.isArray(value) ? value : [value];
              const fieldLabel = t(`mappingFields.${field.id}`);
              const selectLabel = t('netbox.mappingFieldLabel', { field: fieldLabel });
              return (
                <Field key={field.id} label={selectLabel}>
                  <select
                    multiple={field.multi}
                    aria-label={selectLabel}
                    value={field.multi ? selected : (selected[0] ?? '')}
                    onChange={(e) => {
                      if (field.multi) {
                        const options = Array.from(e.target.selectedOptions).map((o) => o.value);
                        editMapping(field.id, options);
                      } else {
                        editMapping(field.id, e.target.value);
                      }
                    }}
                  >
                    {!field.multi ? <option value="">{t('netbox.mappingNone')}</option> : null}
                    {preview.headers.map((header) => (
                      <option key={header} value={header}>
                        {header}
                      </option>
                    ))}
                  </select>
                </Field>
              );
            })}
          </div>

          <div className={styles.switches}>
            <Checkbox
              label={t('netbox.assignIds')}
              checked={assignIds}
              onChange={(_e, d) => void reloadWithAssignIds(d.checked === true)}
            />
            <Checkbox label={t('netbox.saveMapping')} checked={saveMapping} onChange={(_e, d) => setSaveMapping(d.checked === true)} />
            <Checkbox label={t('common.registerCheckbox')} checked={registerRows} onChange={(_e, d) => setRegisterRows(d.checked === true)} />
          </div>

          {preview.warnings.length ? (
            <MessageBar intent="warning">
              <MessageBarBody>{preview.warnings.join(' ')}</MessageBarBody>
            </MessageBar>
          ) : null}
          {preview.duplicates.length ? (
            <MessageBar intent="warning" data-testid="netbox-duplicates">
              <MessageBarBody>
                <MessageBarTitle>{t('common.duplicatesTitle')}</MessageBarTitle>
                {preview.duplicates.join(', ')}
              </MessageBarBody>
            </MessageBar>
          ) : null}

          <div className={styles.tableWrap}>
            <Table size="small" aria-label={t('netbox.tableAriaLabel')}>
              <TableHeader>
                <TableRow>
                  <TableHeaderCell>{t('netbox.columns.id')}</TableHeaderCell>
                  <TableHeaderCell>{t('netbox.columns.source')}</TableHeaderCell>
                  <TableHeaderCell>{t('netbox.columns.target')}</TableHeaderCell>
                  <TableHeaderCell>{t('netbox.columns.type')}</TableHeaderCell>
                </TableRow>
              </TableHeader>
              <TableBody>
                {preview.rows.map((row, i) => (
                  <TableRow key={i} className={preview.duplicates.includes(row.kabel_id) ? styles.dup : undefined}>
                    <TableCell>
                      {row.kabel_id} {row.neu ? t('netbox.rowNew') : ''}
                    </TableCell>
                    <TableCell>{row.quelle}</TableCell>
                    <TableCell>{row.ziel}</TableCell>
                    <TableCell>{row.kabeltyp}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <div className={styles.toolbar}>
            <Field label={t('netbox.templateLabel')}>
              <select
                aria-label={t('netbox.templateLabel')}
                value={template}
                onChange={(e) => setTemplate(e.target.value as 'kabelfahne' | 'kabelwickel')}
              >
                <option value="kabelfahne">kabelfahne</option>
                <option value="kabelwickel">kabelwickel</option>
              </select>
            </Field>
            <Button appearance="primary" icon={<Open20Regular />} disabled={opening} aria-busy={opening} onClick={() => void openSeries()}>
              {opening ? t('common.opening') : t('common.openSeries')}
            </Button>
          </div>
        </>
      ) : !loading && !error ? (
        <EmptyState title={t('netbox.empty.title')} body={t('netbox.empty.body')} />
      ) : null}
    </div>
  );
}
