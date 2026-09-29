/** Reiter „Notizen“ der Vault-Seite: Notizen wählen, Werte zeigen, Label drucken, Tabellen als Serie. */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Select,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { DocumentText20Regular, Print20Regular, TableSimple20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../api/client';
import { useLabelRender } from '../../api/labels';
import type { OutcomeJson, TemplateSummary } from '../../api/types';
import { EmptyState } from '../../components/EmptyState';
import { ErrorMessage } from '../../components/ErrorMessage';
import { LoadingState } from '../../components/LoadingState';
import { useNotify } from '../../components/NotifyProvider';
import { Section } from '../../components/Section';
import { TapePreview } from '../../components/TapePreview';
import { usePrint } from '../../components/usePrint';
import { useLayoutStyles } from '../../theme/layout';
import { postPrinted, postVaultTable, useTemplates, useVaultNote, useVaultNotes, useVaultSettings } from './api';
import type { PrintedJson, VaultNoteJson } from './types';

const MAX_TABLE_ROWS = 12;

const useStyles = makeStyles({
  layout: {
    display: 'grid',
    gridTemplateColumns: 'minmax(220px, 300px) minmax(0, 1fr)',
    columnGap: tokens.spacingHorizontalXL,
    rowGap: tokens.spacingVerticalL,
    '@media (max-width: 760px)': { gridTemplateColumns: 'minmax(0, 1fr)' },
  },
  column: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalL, minWidth: 0 },
  list: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalXXS,
    maxHeight: '480px',
    overflowY: 'auto',
  },
  noteButton: { justifyContent: 'flex-start', textAlign: 'left', minWidth: 0 },
  scroll: { overflowX: 'auto', maxWidth: '100%' },
  mono: { fontFamily: tokens.fontFamilyMonospace, wordBreak: 'break-all' },
});

function inputFields(template: TemplateSummary | undefined) {
  return (template?.input_fields ?? []).filter((f) => f.type === 'input');
}

/** Vorbelegung „Feld ← Notizschlüssel“: gleicher Name, sonst leer. */
function defaultMapping(template: TemplateSummary | undefined, note: VaultNoteJson | undefined): Record<string, string> {
  const mapping: Record<string, string> = {};
  for (const field of inputFields(template)) {
    mapping[field.id] = note && field.id in note.values ? field.id : '';
  }
  return mapping;
}

function mappedValues(template: TemplateSummary | undefined, note: VaultNoteJson | undefined, mapping: Record<string, string>) {
  const values: Record<string, string> = {};
  if (!note) return values;
  for (const field of inputFields(template)) {
    const key = mapping[field.id];
    if (key && note.values[key] !== undefined) values[field.id] = note.values[key];
  }
  return values;
}

function isPrinted(outcome: OutcomeJson | null): outcome is OutcomeJson {
  return Boolean(outcome && (outcome.status === 'ok' || outcome.status === 'wartet') && outcome.history_id !== null); // i18n-ignore (Server-Wert)
}

function NoteDetail(props: { note: VaultNoteJson }): JSX.Element {
  const { note } = props;
  const styles = useStyles();
  const layout = useLayoutStyles();
  const { t } = useTranslation('vault');
  const navigate = useNavigate();
  const notify = useNotify();
  const templates = useTemplates();
  const settings = useVaultSettings();
  const list = useMemo(() => templates.data?.templates ?? [], [templates.data]);
  const [templateName, setTemplateName] = useState('');
  const template = list.find((t) => t.name === templateName);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [vermerk, setVermerk] = useState(false);
  const vermerkTouched = useRef(false);
  const [printed, setPrinted] = useState<PrintedJson | null>(null);
  const [busyTable, setBusyTable] = useState<number | null>(null);
  const printFlow = usePrint();

  useEffect(() => {
    setMapping(defaultMapping(template, note));
  }, [template, note]);

  useEffect(() => {
    setPrinted(null);
  }, [note.path]);

  useEffect(() => {
    const preset = settings.data?.settings.obsidian.append_after_print;
    if (preset !== undefined && !vermerkTouched.current) setVermerk(preset);
  }, [settings.data]);

  const values = useMemo(() => mappedValues(template, note, mapping), [template, note, mapping]);
  const source = template ? ({ kind: 'template' as const, template: template.name, values }) : null;
  const render = useLabelRender(source);
  const keys = Object.keys(note.values);

  const onPrint = async () => {
    if (!source) return;
    setPrinted(null);
    const outcome = await printFlow.run(source);
    if (!isPrinted(outcome) || !vermerk) return;
    try {
      const result = await postPrinted({ path: note.path, history_id: outcome.history_id, force: vermerk });
      setPrinted(result);
    } catch (err) {
      const api = err instanceof ApiError ? err : null;
      notify({ intent: 'error', title: api ? api.message : t('print.appendFailedTitle'), hint: api?.hint || undefined });
    }
  };

  const onTakeOver = () => {
    if (!template) return;
    const params = new URLSearchParams({ vorlage: template.name, werte: JSON.stringify(values) });
    navigate(`/vorlagen?${params.toString()}`);
  };

  const onSeries = async (index: number) => {
    setBusyTable(index);
    try {
      const result = await postVaultTable({ path: note.path, table: index, columns: null, template: templateName || null });
      const params = new URLSearchParams();
      if (templateName) params.set('vorlage', templateName);
      params.set('import', result.pending_id);
      navigate(`/vorlagen?${params.toString()}`);
    } catch (err) {
      const api = err instanceof ApiError ? err : null;
      notify({ intent: 'error', title: api ? api.message : t('print.seriesFailedTitle'), hint: api?.hint || undefined });
    } finally {
      setBusyTable(null);
    }
  };

  return (
    <div className={styles.column}>
      <Section title={note.title} description={note.path}>
        {keys.length === 0 ? (
          <EmptyState title={t('detail.empty.title')} body={t('detail.empty.body')} />
        ) : (
          <div className={styles.scroll}>
            <Table size="small" aria-label={t('detail.valuesAriaLabel')}>
              <TableHeader>
                <TableRow>
                  <TableHeaderCell>{t('detail.key')}</TableHeaderCell>
                  <TableHeaderCell>{t('detail.value')}</TableHeaderCell>
                </TableRow>
              </TableHeader>
              <TableBody>
                {keys.map((key) => (
                  <TableRow key={key}>
                    <TableCell className={styles.mono}>{key}</TableCell>
                    <TableCell>{note.values[key]}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Section>

      <Section title={t('print.sectionTitle')} description={t('print.description')}>
        {templates.error ? <ErrorMessage error={templates.error} title={t('print.templatesFailedTitle')} /> : null}
        <div className={layout.rowWrap}>
          <Field label={t('print.template')}>
            <Select value={templateName} onChange={(_e, d) => setTemplateName(d.value)}>
              <option value="">{t('print.pleaseChoose')}</option>
              {list.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.name}
                </option>
              ))}
            </Select>
          </Field>
          <Switch
            label={t('print.appendNote')}
            checked={vermerk}
            onChange={(_e, d) => {
              vermerkTouched.current = true;
              setVermerk(d.checked);
            }}
          />
        </div>
        {template ? (
          <>
            <div className={styles.scroll}>
              <Table size="small" aria-label={t('print.mappingAriaLabel')}>
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell>{t('print.field')}</TableHeaderCell>
                    <TableHeaderCell>{t('print.mappingFrom')}</TableHeaderCell>
                    <TableHeaderCell>{t('print.value')}</TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {inputFields(template).map((field) => (
                    <TableRow key={field.id}>
                      <TableCell>{field.label}</TableCell>
                      <TableCell>
                        <Select
                          aria-label={t('print.mappingSelectAriaLabel', { field: field.label })}
                          value={mapping[field.id] ?? ''}
                          onChange={(_e, d) => setMapping((prev) => ({ ...prev, [field.id]: d.value }))}
                        >
                          <option value="">{t('print.empty')}</option>
                          {keys.map((key) => (
                            <option key={key} value={key}>
                              {key}
                            </option>
                          ))}
                        </Select>
                      </TableCell>
                      <TableCell>{values[field.id] ?? ''}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <TapePreview render={render.data} loading={render.loading} compact />
            <div className={layout.rowWrap}>
              <Button appearance="primary" icon={<Print20Regular />} disabled={printFlow.busy} onClick={() => void onPrint()}>
                {t('print.print')}
              </Button>
              <Button icon={<DocumentText20Regular />} onClick={onTakeOver}>
                {t('print.takeOver')}
              </Button>
            </div>
          </>
        ) : null}
        {printed ? (
          printed.appended ? (
            <MessageBar intent="success">
              <MessageBarBody>
                <MessageBarTitle>{t('print.appendedTitle')}</MessageBarTitle>
                <span className={styles.mono}>{printed.line}</span>
              </MessageBarBody>
            </MessageBar>
          ) : (
            <MessageBar intent="info">
              <MessageBarBody>{t('print.notAppended', { reason: printed.reason || t('print.noReason') })}</MessageBarBody>
            </MessageBar>
          )
        ) : null}
      </Section>

      {note.tables.map((table, index) => (
        <Section
          key={`${table.heading ?? ''}-${index}`}
          title={table.heading ? t('tables.titleWithHeading', { index: index + 1, heading: table.heading }) : t('tables.title', { index: index + 1 })}
          actions={
            <Button icon={<TableSimple20Regular />} disabled={busyTable !== null} onClick={() => void onSeries(index)}>
              {t('tables.asSeries')}
            </Button>
          }
        >
          <div className={styles.scroll}>
            <Table size="small" aria-label={t('tables.ariaLabel', { index: index + 1 })}>
              <TableHeader>
                <TableRow>
                  {table.headers.map((h, i) => (
                    <TableHeaderCell key={`${h}-${i}`}>{h}</TableHeaderCell>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {table.rows.slice(0, MAX_TABLE_ROWS).map((row, r) => (
                  <TableRow key={r}>
                    {row.map((cell, c) => (
                      <TableCell key={c}>{cell}</TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {table.rows.length > MAX_TABLE_ROWS ? <span>{t('tables.moreRows', { count: table.rows.length - MAX_TABLE_ROWS })}</span> : null}
        </Section>
      ))}
    </div>
  );
}

export function NotesView(): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('vault');
  const [folder, setFolder] = useState('');
  const [filter, setFilter] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const notes = useVaultNotes(folder);
  const note = useVaultNote(selected);
  const [knownFolders, setKnownFolders] = useState<string[]>([]);

  useEffect(() => {
    const all = notes.data?.folders;
    if (all?.length && !folder) setKnownFolders(all);
  }, [notes.data, folder]);

  const visible = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const list = notes.data?.notes ?? [];
    return needle ? list.filter((n) => n.toLowerCase().includes(needle)) : list;
  }, [notes.data, filter]);

  return (
    <div className={styles.layout}>
      <div className={styles.column}>
        <Section title={t('notes.sectionTitle')}>
          <Field label={t('notes.folder')}>
            <Select value={folder} onChange={(_e, d) => setFolder(d.value)}>
              <option value="">{t('notes.allFolders')}</option>
              {knownFolders.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('notes.search')}>
            <Input value={filter} onChange={(_e, d) => setFilter(d.value)} placeholder={t('notes.searchPlaceholder')} />
          </Field>
          {notes.isLoading ? <LoadingState variant="inline" /> : null}
          {notes.error ? <ErrorMessage error={notes.error} title={t('notes.notReachableTitle')} /> : null}
          {notes.data && visible.length === 0 ? <EmptyState title={t('notes.empty')} /> : null}
          <div className={styles.list} role="group" aria-label={t('notes.ariaLabel')}>
            {visible.map((path) => (
              <Button
                key={path}
                className={styles.noteButton}
                appearance={path === selected ? 'primary' : 'subtle'}
                onClick={() => setSelected(path)}
              >
                {path}
              </Button>
            ))}
          </div>
        </Section>
      </div>
      <div className={styles.column}>
        {!selected ? <EmptyState title={t('notes.noSelection.title')} body={t('notes.noSelection.body')} /> : null}
        {selected && note.isLoading ? <LoadingState variant="inline" /> : null}
        {selected && note.error ? <ErrorMessage error={note.error} title={t('detail.notLoadedTitle')} /> : null}
        {note.data && selected ? <NoteDetail note={note.data} /> : null}
      </div>
    </div>
  );
}
