/** Serie/Import: Tabelle/Datei, Liste oder Serie, Zuordnung, Vorschau, Druck als Kette. */
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Button,
  Checkbox,
  Combobox,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  Option,
  Spinner,
  Tab,
  TabList,
  Textarea,
  makeStyles,
  mergeClasses,
  tokens,
} from '@fluentui/react-components';
import { ArrowClockwise20Regular, Clipboard20Regular, DocumentArrowUp20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import type { BatchPlanJson, BatchRequest, BatchSourceInput, FieldJson } from '../../api/types';
import { DEFAULT_PRINT_OPTIONS } from '../../api/types';
import { pngSrc } from '../../api/client';
import { PrintOptionsBar } from '../../components/PrintOptionsBar';
import { WarningList } from '../../components/WarningList';
import { usePrintFlow } from '../../components/usePrint';
import { readClipboardText, readFileAsB64 } from '../../platform';
import { batchContactSheet, fetchBatchPlan, fetchBatchTable, printBatch } from './batchApi';
import { useMediaQuery } from '../../components/useMediaQuery';

type FileTab = 'datei' | 'liste' | 'serie';
type HasHeaderMode = 'auto' | 'ja' | 'nein';

/** Ab dieser Breite füllt der Dialog den ganzen Bildschirm (auf schmalen Bildschirmen Vollbild). */
const FULLSCREEN_QUERY = '(max-width: 599px)';

const useStyles = makeStyles({
  // Datei-Eingabe nur für die Auswahl, sichtbar ist der übersetzte Knopf.
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
  surface: { maxWidth: '960px', width: '95vw' },
  body: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM, minHeight: '60vh' },
  toolbar: { display: 'flex', columnGap: tokens.spacingHorizontalS, alignItems: 'center', flexWrap: 'wrap' },
  columns: { display: 'flex', columnGap: tokens.spacingHorizontalL, flexWrap: 'wrap' },
  col: { flex: '1 1 320px', minWidth: 0, display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS },
  tableWrap: { maxHeight: '260px', overflow: 'auto', border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`, borderRadius: tokens.borderRadiusMedium },
  table: { borderCollapse: 'collapse', width: '100%', fontSize: tokens.fontSizeBase200 },
  th: { textAlign: 'left', padding: tokens.spacingHorizontalXS, position: 'sticky', top: 0, backgroundColor: tokens.colorNeutralBackground2, borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}` },
  td: { padding: tokens.spacingHorizontalXS, borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke3}` },
  rowExcluded: { opacity: 0.5 },
  mapping: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXS },
  mappingRow: { display: 'flex', columnGap: tokens.spacingHorizontalS, alignItems: 'center' },
  fieldLabel: { minWidth: '140px', flexShrink: 0, fontSize: tokens.fontSizeBase200 },
  mappingHeading: { margin: `0 0 ${tokens.spacingVerticalXS}`, fontSize: tokens.fontSizeBase200, fontWeight: tokens.fontWeightSemibold },
  mappingTable: { borderCollapse: 'collapse', width: '100%' },
  mappingTh: {
    textAlign: 'left',
    verticalAlign: 'middle',
    padding: `${tokens.spacingVerticalXXS} ${tokens.spacingHorizontalS} ${tokens.spacingVerticalXXS} 0`,
    fontWeight: tokens.fontWeightRegular,
    fontSize: tokens.fontSizeBase200,
    whiteSpace: 'nowrap',
  },
  mappingTd: { padding: `${tokens.spacingVerticalXXS} 0`, width: '100%' },
  mappingFields: { display: 'flex', columnGap: tokens.spacingHorizontalS, alignItems: 'center' },
  previews: { display: 'flex', columnGap: tokens.spacingHorizontalS, overflowX: 'auto', padding: tokens.spacingVerticalXS },
  previewImg: { height: '60px', border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`, borderRadius: tokens.borderRadiusSmall },
  summary: { fontWeight: tokens.fontWeightSemibold },
});

function noHeader(mode: HasHeaderMode): boolean | null {
  if (mode === 'ja') return true;
  if (mode === 'nein') return false;
  return null;
}

export function BatchDialog(props: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Zielvorlage; `null`, solange noch keine gewählt ist (z. B. `?import=<id>` ohne `&vorlage=`). */
  templateName: string | null;
  fields: FieldJson[];
  initialImport?: string | null;
  /** Vorlagennamen für die Vorlagenwahl im Dialog. Ist die Liste gesetzt, zeigt der Dialog eine Auswahl. */
  templates?: string[];
  /** Wird bei der Vorlagenwahl im Dialog aufgerufen; die Seite lädt daraufhin die Felder der Vorlage. */
  onSelectTemplate?: (name: string) => void;
}): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('vorlagen');
  const { open, templateName, fields } = props;
  const showTemplateChoice = props.templates !== undefined;
  const fullscreen = useMediaQuery(FULLSCREEN_QUERY);

  const [tab, setTab] = useState<FileTab>('datei');
  const [text, setText] = useState('');
  const [hasHeader, setHasHeader] = useState<HasHeaderMode>('auto');
  const [linesText, setLinesText] = useState('');
  const [seriesFields, setSeriesFields] = useState<Record<string, string>>({});
  const [seriesCount, setSeriesCount] = useState('');
  const [pendingId, setPendingId] = useState<string | null>(null);
  /** Hochgeladene Datei (.csv/.xlsx); hat Vorrang vor eingefügtem Text. */
  const [fileSource, setFileSource] = useState<{ name: string; data_b64: string } | null>(null);

  const [tableHeaders, setTableHeaders] = useState<string[]>([]);
  const [tableRows, setTableRows] = useState<string[][]>([]);
  const [tableLoading, setTableLoading] = useState(false);
  const [rowFilter, setRowFilter] = useState('');
  const [deselected, setDeselected] = useState<Set<number>>(new Set());

  const [mapping, setMapping] = useState<Record<string, string>>({});
  const mappingTouched = useRef(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [fixed, setFixed] = useState<Record<string, string>>({});
  const [chain, setChain] = useState(false);
  const [cutMarks, setCutMarks] = useState(true);
  const [cutPauseS, setCutPauseS] = useState<number | null>(null);

  const [plan, setPlan] = useState<BatchPlanJson | null>(null);
  const [planLoading, setPlanLoading] = useState(false);

  const consumedImport = useRef<string | null>(null);

  const inputFields = useMemo(() => fields.filter((f) => f.type === 'input'), [fields]);

  // Reset bei jedem Öffnen mit neuer Vorlage.
  useEffect(() => {
    if (!open) return;
    setDeselected(new Set());
    mappingTouched.current = false;
  }, [open, templateName]);

  // Anfangsquelle aus der Seite (Pending-Import oder Zwischenablage), nur einmal je Wert.
  useEffect(() => {
    if (!open || !props.initialImport || consumedImport.current === props.initialImport) return;
    consumedImport.current = props.initialImport;
    setTab('datei');
    if (props.initialImport === 'zwischenablage') {
      void readClipboardText().then((clip) => {
        setFileSource(null);
        setText(clip);
      });
    } else {
      setFileSource(null);
      setPendingId(props.initialImport);
    }
  }, [open, props.initialImport]);

  const tableSource: BatchSourceInput | null = useMemo(() => {
    if (tab !== 'datei') return null;
    if (pendingId) return { type: 'pending', id: pendingId };
    if (fileSource) return { type: 'file', name: fileSource.name, data_b64: fileSource.data_b64, has_header: noHeader(hasHeader) };
    if (!text) return null;
    return { type: 'text', text, has_header: noHeader(hasHeader) };
  }, [tab, pendingId, fileSource, text, hasHeader]);

  const tableKey = tableSource ? JSON.stringify(tableSource) : null;

  // Tabellenvorschau (Kopf/Zeilen) für Tabelle/Datei.
  useEffect(() => {
    if (!open || !tableSource) {
      setTableHeaders([]);
      setTableRows([]);
      return;
    }
    let cancelled = false;
    setTableLoading(true);
    fetchBatchTable(tableSource).then(
      (res) => {
        if (cancelled) return;
        setTableHeaders(res.headers);
        setTableRows(res.rows);
        setTableLoading(false);
        setDeselected(new Set());
      },
      () => {
        if (cancelled) return;
        setTableHeaders([]);
        setTableRows([]);
        setTableLoading(false);
      },
    );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, tableKey]);

  const currentSource = (): BatchSourceInput | null => {
    if (tab === 'datei') return tableSource;
    if (tab === 'liste') return linesText ? { type: 'lines', text: linesText } : null;
    const nonEmpty = Object.fromEntries(Object.entries(seriesFields).filter(([, v]) => v.trim()));
    if (Object.keys(nonEmpty).length === 0) return null;
    const count = seriesCount.trim() ? Number(seriesCount) : null;
    return { type: 'series', fields: nonEmpty, count: Number.isFinite(count) ? count : null };
  };

  const selectedIndices = tab === 'datei' && tableRows.length > 0 ? tableRows.map((_r, i) => i).filter((i) => !deselected.has(i)) : null;

  const planRequest = useMemo<BatchRequest | null>(() => {
    const source = currentSource();
    if (!source || !templateName) return null;
    return {
      template: templateName,
      source,
      mapping: mappingTouched.current ? mapping : null,
      selected: selectedIndices,
      fixed,
      chain,
      cut_marks: cutMarks,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateName, tab, text, pendingId, fileSource, hasHeader, linesText, seriesFields, seriesCount, mapping, selectedIndices, fixed, chain, cutMarks]);

  const planKey = planRequest ? JSON.stringify(planRequest) : null;

  useEffect(() => {
    if (!open || !planRequest) {
      setPlan(null);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      setPlanLoading(true);
      fetchBatchPlan(planRequest).then(
        (res) => {
          if (cancelled) return;
          setPlan(res);
          setPlanLoading(false);
          if (!mappingTouched.current && Object.keys(res.mapping).length > 0) {
            setMapping(res.mapping);
          }
        },
        () => {
          if (cancelled) return;
          setPlanLoading(false);
        },
      );
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, planKey]);

  const printFlow = usePrintFlow<BatchRequest>(printBatch);

  const filteredRowIndices = useMemo(() => {
    if (!rowFilter.trim()) return tableRows.map((_r, i) => i);
    const needle = rowFilter.trim().toLowerCase();
    return tableRows.map((_r, i) => i).filter((i) => tableRows[i]?.some((cell) => cell.toLowerCase().includes(needle)));
  }, [tableRows, rowFilter]);

  const toggleRow = (index: number) => {
    setDeselected((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const errors = plan?.errors ?? [];
  const canPrint = plan !== null && errors.length === 0 && !printFlow.busy;

  const onPrint = () => {
    if (!planRequest) return;
    void printFlow.run(planRequest, { ...DEFAULT_PRINT_OPTIONS, chain, cut_marks: cutMarks, cut_pause_s: cutPauseS });
  };

  const onContactSheet = () => {
    if (!planRequest) return;
    void batchContactSheet(planRequest);
  };

  return (
    <Dialog open={open} onOpenChange={(_e, d) => props.onOpenChange(d.open)}>
      {/* Inline-Style statt Klasse: Fluents eigene DialogSurface-Grundstile ("__resetStyles") werden erst beim
          Rendern der Komponente selbst eingefuegt, also nach unseren makeStyles-Klassen; bei gleicher Spezifitaet
          gewinnt sonst die zuletzt eingefuegte Regel (Fluents Standardhoehe/-breite) statt unserer Vollbild-Werte. */}
      <DialogSurface className={styles.surface} style={fullscreen ? { width: '100vw', height: '100vh', maxWidth: 'none', borderRadius: 0 } : undefined}>
        <DialogBody>
          <DialogTitle>{t('batch.titlePrefix')}{templateName ?? t('batch.titleChoose')}</DialogTitle>
          <DialogContent className={styles.body}>
            {showTemplateChoice ? (
              <Field
                label={t('batch.targetTemplate')}
                validationMessage={templateName ? undefined : t('batch.targetTemplateRequired')}
                validationState={templateName ? 'none' : 'warning'}
              >
                <Combobox
                  aria-label={t('batch.targetTemplate')}
                  placeholder={t('batch.targetTemplatePlaceholder')}
                  value={templateName ?? ''}
                  selectedOptions={templateName ? [templateName] : []}
                  onOptionSelect={(_e, d) => d.optionValue && props.onSelectTemplate?.(d.optionValue)}
                >
                  {(props.templates ?? []).map((name) => (
                    <Option key={name} value={name}>
                      {name}
                    </Option>
                  ))}
                </Combobox>
              </Field>
            ) : null}
            <TabList selectedValue={tab} onTabSelect={(_e, d) => setTab(d.value as FileTab)}>
              <Tab value="datei">{t('batch.tabs.file')}</Tab>
              <Tab value="liste">{t('batch.tabs.list')}</Tab>
              <Tab value="serie">{t('batch.tabs.series')}</Tab>
            </TabList>

            {tab === 'datei' ? (
              <div className={styles.col}>
                <div className={styles.toolbar}>
                  <Button
                    icon={<Clipboard20Regular />}
                    onClick={() => {
                      void readClipboardText().then((clip) => {
                        setPendingId(null);
                        setFileSource(null);
                        setText(clip);
                      });
                    }}
                  >
                    {t('batch.fromClipboard')}
                  </Button>
                  <Field label={t('batch.header.label')}>
                    <Combobox
                      value={hasHeader === 'auto' ? t('batch.header.auto') : hasHeader === 'ja' ? t('batch.header.yes') : t('batch.header.no')}
                      selectedOptions={[hasHeader]}
                      onOptionSelect={(_e, d) => setHasHeader((d.optionValue as HasHeaderMode) ?? 'auto')}
                    >
                      <Option value="auto">{t('batch.header.auto')}</Option>
                      <Option value="ja">{t('batch.header.yes')}</Option>
                      <Option value="nein">{t('batch.header.no')}</Option>
                    </Combobox>
                  </Field>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".csv,.xlsx"
                    tabIndex={-1}
                    className={styles.visuallyHidden}
                    aria-label={t('batch.uploadFile')}
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      e.target.value = '';
                      if (!file) return;
                      // Die Tabellenvorschau und der Plan laufen danach über `tableSource` (Typ `file`).
                      void readFileAsB64(file).then((b64) => {
                        setPendingId(null);
                        setFileSource({ name: file.name, data_b64: b64 });
                      });
                    }}
                  />
                  <Button icon={<DocumentArrowUp20Regular />} onClick={() => fileInputRef.current?.click()}>
                    {t('batch.chooseFile')}
                  </Button>
                </div>
                {fileSource ? <span data-testid="batch-datei">{t('batch.fileLabel', { name: fileSource.name })}</span> : null}
                <Textarea
                  placeholder={t('batch.tablePlaceholder')}
                  value={pendingId || fileSource ? '' : text}
                  onChange={(_e, d) => {
                    setPendingId(null);
                    setFileSource(null);
                    setText(d.value);
                  }}
                  resize="vertical"
                  rows={4}
                  aria-label={t('batch.tableInsert')}
                />
              </div>
            ) : null}

            {tab === 'liste' ? (
              <Textarea
                placeholder={t('batch.listPlaceholder')}
                value={linesText}
                onChange={(_e, d) => setLinesText(d.value)}
                resize="vertical"
                rows={6}
                aria-label={t('batch.listInsert')}
              />
            ) : null}

            {tab === 'serie' ? (
              <div className={styles.mapping}>
                {inputFields.map((f) => (
                  <div key={f.id} className={styles.mappingRow}>
                    <span className={styles.fieldLabel}>{f.label}</span>
                    <Input
                      placeholder={t('batch.seriesPlaceholder')}
                      value={seriesFields[f.id] ?? ''}
                      onChange={(_e, d) => setSeriesFields((prev) => ({ ...prev, [f.id]: d.value }))}
                    />
                  </div>
                ))}
                <Field label={t('batch.seriesCount')}>
                  <Input value={seriesCount} onChange={(_e, d) => setSeriesCount(d.value)} />
                </Field>
              </div>
            ) : null}

            {tab === 'datei' ? (
              <>
                {tableLoading ? <Spinner size="tiny" label={t('batch.tableLoading')} /> : null}
                {tableHeaders.length > 0 ? (
                  <div className={styles.columns}>
                    <div className={styles.col}>
                      <Input placeholder={t('batch.rowFilterPlaceholder')} value={rowFilter} onChange={(_e, d) => setRowFilter(d.value)} />
                      <div className={styles.tableWrap}>
                        <table className={styles.table}>
                          <thead>
                            <tr>
                              <th className={styles.th}>
                                <Checkbox
                                  checked={deselected.size === 0}
                                  onChange={() => setDeselected(deselected.size === 0 ? new Set(tableRows.map((_r, i) => i)) : new Set())}
                                  aria-label={t('batch.selectAll')}
                                />
                              </th>
                              {tableHeaders.map((h) => (
                                <th className={styles.th} key={h}>
                                  {h}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {filteredRowIndices.map((i) => {
                              const row = tableRows[i] ?? [];
                              return (
                                <tr key={i} className={mergeClasses(deselected.has(i) && styles.rowExcluded)}>
                                  <td className={styles.td}>
                                    <Checkbox
                                      checked={!deselected.has(i)}
                                      onChange={() => toggleRow(i)}
                                      aria-label={t('batch.selectRow', { n: i + 1 })}
                                    />
                                  </td>
                                  {row.map((cell, j) => (
                                    <td className={styles.td} key={j}>
                                      {cell}
                                    </td>
                                  ))}
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>
                    <div className={styles.col}>
                      <h3 className={styles.mappingHeading}>{t('batch.mappingHeading')}</h3>
                      <table className={styles.mappingTable} aria-label={t('batch.mappingLabel')}>
                        <tbody>
                          {inputFields.map((f) => (
                            <tr key={f.id}>
                              <th className={styles.mappingTh} scope="row">
                                {f.label}
                              </th>
                              <td className={styles.mappingTd}>
                                <div className={styles.mappingFields}>
                                  <Combobox
                                    aria-label={t('batch.mappingField', { label: f.label })}
                                    value={mapping[f.id] ?? ''}
                                    selectedOptions={mapping[f.id] ? [mapping[f.id] as string] : []}
                                    onOptionSelect={(_e, d) => {
                                      mappingTouched.current = true;
                                      setMapping((prev) => ({ ...prev, [f.id]: d.optionValue ?? '' }));
                                    }}
                                  >
                                    {tableHeaders.map((h) => (
                                      <Option key={h} value={h}>
                                        {h}
                                      </Option>
                                    ))}
                                  </Combobox>
                                  {!mapping[f.id] ? (
                                    <Input
                                      placeholder={t('batch.fixedValuePlaceholder')}
                                      value={fixed[f.id] ?? ''}
                                      onChange={(_e, d) => setFixed((prev) => ({ ...prev, [f.id]: d.value }))}
                                    />
                                  ) : null}
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ) : null}
              </>
            ) : null}

            {planLoading ? <Spinner size="tiny" label={t('batch.planLoading')} /> : null}
            {plan ? (
              <>
                <p className={styles.summary} data-testid="batch-summary">
                  {plan.summary}
                  {t('batch.summarySuffix', { count: plan.count })}
                </p>
                <WarningList errors={plan.errors} warnings={plan.warnings} />
                {plan.previews.length > 0 ? (
                  <div className={styles.previews}>
                    {plan.previews.map((p) => (
                      <img key={p.index} className={styles.previewImg} src={pngSrc(p.design_png)} alt={p.title} />
                    ))}
                  </div>
                ) : null}
              </>
            ) : null}

            <PrintOptionsBar
              showCopies={false}
              value={{ ...DEFAULT_PRINT_OPTIONS, chain, cut_marks: cutMarks, cut_pause_s: cutPauseS }}
              onChange={(v) => {
                setChain(v.chain);
                setCutMarks(v.cut_marks);
                setCutPauseS(v.cut_pause_s);
              }}
            />
          </DialogContent>
          <DialogActions>
            <Button icon={<ArrowClockwise20Regular />} onClick={onContactSheet} disabled={!plan}>
              {t('batch.contactSheet')}
            </Button>
            <Button appearance="primary" onClick={onPrint} disabled={!canPrint}>
              {t('common:actions.print')}
            </Button>
            <Button onClick={() => props.onOpenChange(false)}>{t('common:actions.close')}</Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}
