/** Vorlagen: Formular aus den Vorlagenfeldern, Live-Vorschau, Druck, Export, Serie/Import. */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Button,
  Combobox,
  Menu,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  MessageBar,
  MessageBarBody,
  Option,
  SearchBox,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { ArrowExport20Regular } from '@fluentui/react-icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../api/client';
import { useLabelRender } from '../../api/labels';
import type { TemplateDetail, TemplateSummary } from '../../api/types';
import { useConfirm } from '../../components/ConfirmProvider';
import { useNotify } from '../../components/NotifyProvider';
import { LoadingState } from '../../components/LoadingState';
import { PageHeader } from '../../components/PageHeader';
import { PlausiHint, usePlausi } from '../../components/PlausiHint';
import { PrintOptionsBar } from '../../components/PrintOptionsBar';
import { Section } from '../../components/Section';
import { TapePreview } from '../../components/TapePreview';
import { WarningList } from '../../components/WarningList';
import { usePrint } from '../../components/usePrint';
import { useRegisterCommands } from '../../commands/CommandProvider';
import { readFileAsB64 } from '../../platform';
import { deleteTemplate, exportAssignment, fetchTemplateDetail, fetchTemplates, parseTemplateFile } from './api';
import { BatchDialog } from './BatchDialog';
import { TemplateForm } from './TemplateForm';
import { useMediaQuery } from '../../components/useMediaQuery';

/** Ab dieser Breite: Vorlagenliste wird Combobox, Vorschau ruckt unter das Formular (responsiv bis 360 px). */
// Drei Spalten (Liste, Formular, Vorschau) brauchen rund 800 px Inhaltsbreite; darunter einspaltig
// (bei 200 % Zoom überlagerten sich die Spalten).
const NARROW_QUERY = '(max-width: 1279px)';

const useStyles = makeStyles({
  layout: { display: 'grid', gridTemplateColumns: 'minmax(200px, 260px) minmax(280px, 1fr) minmax(280px, 1fr)', columnGap: tokens.spacingHorizontalL },
  /** Eigenständig (statt mit `layout` gemergt): Griffels mergeClasses warnt/verliert Regeln, wenn zwei bereits atomare
   *  makeStyles-Klassen mit überlappenden Eigenschaften zusammengeführt werden. Deshalb per Ternary austauschen. */
  layoutNarrow: { display: 'grid', gridTemplateColumns: '1fr', rowGap: tokens.spacingVerticalL },
  listCol: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS },
  categoryTitle: { margin: `${tokens.spacingVerticalM} 0 ${tokens.spacingVerticalXXS}`, fontSize: tokens.fontSizeBase200, fontWeight: tokens.fontWeightSemibold, color: tokens.colorNeutralForeground3, textTransform: 'uppercase' },
  listButton: { justifyContent: 'flex-start', textAlign: 'left' },
  listButtonActive: { backgroundColor: tokens.colorBrandBackground2 },
  /** Aktionen in Reihen, alle Knöpfe gleich hoch (stretch je Reihe), Primär „Drucken“ zuerst. */
  buttons: { display: 'flex', flexWrap: 'wrap', alignItems: 'stretch', columnGap: tokens.spacingHorizontalS, rowGap: tokens.spacingVerticalS },
  /** Nebenaktion unter dem Formular: nicht über die ganze Breite ziehen. */
  secondary: { alignSelf: 'flex-start' },
  center: { display: 'grid', placeItems: 'center', padding: tokens.spacingVerticalXXXL },
  noHits: { margin: `${tokens.spacingVerticalS} 0`, color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200 },
});

/** Suche in der Vorlagenliste: Name, Stichworte und Beschreibung, ohne Groß-/Kleinschreibung. */
function matchesTemplate(t: TemplateSummary, query: string): boolean {
  const q = query.trim().toLocaleLowerCase();
  if (!q) return true;
  const haystack = [t.name, t.title ?? '', t.description ?? '', ...t.tags].join(' ').toLocaleLowerCase();
  return haystack.includes(q);
}

function groupByCategory(templates: TemplateSummary[], fallbackCategory: string): { name: string; templates: TemplateSummary[] }[] {
  const map = new Map<string, TemplateSummary[]>();
  for (const t of templates) {
    const key = t.category || fallbackCategory;
    const list = map.get(key) ?? [];
    list.push(t);
    map.set(key, list);
  }
  return [...map.entries()].map(([name, list]) => ({ name, templates: list }));
}

export default function VorlagenPage(): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('vorlagen');
  const navigate = useNavigate();
  const notify = useNotify();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const narrow = useMediaQuery(NARROW_QUERY);
  const [params, setParams] = useSearchParams();

  const [selectedName, setSelectedName] = useState<string | null>(params.get('vorlage'));
  const [values, setValues] = useState<Record<string, string>>({});
  const [copies, setCopies] = useState(1);
  const [chain, setChain] = useState(false);
  const [cutMarks, setCutMarks] = useState(true);
  const [cutPauseS, setCutPauseS] = useState<number | null>(null);
  const [batchOpen, setBatchOpen] = useState(Boolean(params.get('import')));
  /** `?import=<id>` ohne `&vorlage=`: keine Vorlage automatisch wählen, sondern im Dialog wählen lassen. */
  const [importNeedsChoice] = useState(() => Boolean(params.get('import')) && !params.get('vorlage'));
  const [fileDefinition, setFileDefinition] = useState<{ name: string; definition: Record<string, unknown> } | null>(null);
  const appliedWerte = useRef<string | null>(null);
  const appliedDatei = useRef<string | null>(null);

  const list = useQuery({ queryKey: ['vorlagen-liste'], queryFn: ({ signal }) => fetchTemplates(signal) });
  const templates = useMemo(() => list.data?.templates ?? [], [list.data]);
  const [search, setSearch] = useState('');
  const categories = useMemo(
    () => groupByCategory(templates.filter((tpl) => matchesTemplate(tpl, search)), t('list.categoryFallback')),
    [templates, search, t],
  );

  useEffect(() => {
    if (selectedName || templates.length === 0 || importNeedsChoice) return;
    setSelectedName(templates[0]?.name ?? null);
  }, [templates, selectedName, importNeedsChoice]);

  const detail = useQuery({
    queryKey: ['vorlagen-detail', selectedName],
    queryFn: ({ signal }) => fetchTemplateDetail(selectedName as string, signal),
    enabled: Boolean(selectedName) && !fileDefinition,
  });

  const template: TemplateDetail | null = useMemo(() => {
    if (fileDefinition) {
      return {
        name: fileDefinition.name,
        description: 'Aus Datei geladen',
        category: 'Datei',
        tags: [],
        kind: 'document',
        builtin: false,
        favorite: false,
        target: null,
        tapes: [],
        default_copies: 1,
        input_fields: [],
        sample: {},
        fields: [],
        path: null,
        definition: fileDefinition.definition,
        tape_reason: null,
      };
    }
    return detail.data ?? null;
  }, [fileDefinition, detail.data]);

  // Vorlage wechseln: Werte zurücksetzen, Kopien vorbelegen.
  const lastAppliedTemplate = useRef<string | null>(null);
  useEffect(() => {
    if (!template) return;
    if (lastAppliedTemplate.current === template.name) return;
    lastAppliedTemplate.current = template.name;
    const initial: Record<string, string> = {};
    for (const f of template.fields.length ? template.fields : template.input_fields) {
      if (f.type === 'input') initial[f.id] = f.default ?? '';
    }
    setValues(initial);
    setCopies(template.default_copies || 1);
  }, [template]);

  // Query ?werte=<JSON> anwenden (einmal je Wert).
  useEffect(() => {
    const werteRaw = params.get('werte');
    if (!werteRaw || appliedWerte.current === werteRaw || !template) return;
    appliedWerte.current = werteRaw;
    try {
      const parsed = JSON.parse(werteRaw) as Record<string, string>;
      setValues((prev) => ({ ...prev, ...parsed }));
    } catch {
      // ungültiges JSON ignorieren
    }
  }, [params, template]);

  // ?datei=<pending-id>: Vorlage aus Datei (pending template_file).
  useEffect(() => {
    const dateiId = params.get('datei');
    if (!dateiId || appliedDatei.current === dateiId) return;
    appliedDatei.current = dateiId;
    import('../../api/client').then(({ apiGet }) =>
      apiGet<{ type: string; name: string; definition: Record<string, unknown> }>(`/api/v1/integration/pending/${encodeURIComponent(dateiId)}`).then(
        (pending) => {
          if (pending.type === 'template_file') {
            setFileDefinition({ name: pending.name, definition: pending.definition });
          }
        },
        () => notify({ intent: 'error', title: t('notify.fileNotLoaded') }),
      ),
    );
  }, [params, notify, t]);

  const source = template
    ? fileDefinition
      ? ({ kind: 'template' as const, template: template.name, values, definition: fileDefinition.definition })
      : ({ kind: 'template' as const, template: template.name, values })
    : null;

  const render = useLabelRender(source, { copies, chain, cut_marks: cutMarks, cut_pause_s: cutPauseS });

  const missingRequired = useMemo(() => {
    if (!template) return [];
    const fs = template.fields.length ? template.fields : template.input_fields;
    return fs.filter((f) => f.type === 'input' && f.required && !(values[f.id] ?? '').trim()).map((f) => f.label);
  }, [template, values]);

  const printFlow = usePrint();
  const plausi = usePlausi(template?.name ?? null, values);

  const onDrucken = async (): Promise<void> => {
    if (!source) return;
    // Nicht auf den entprellten Stand verlassen: für die aktuellen Werte sofort prüfen.
    const checked = await plausi.check();
    if (checked.worst === 'konflikt') {
      const ok = await confirm({
        title: t('confirmConflict.title'),
        message: t('confirmConflict.message'),
        reasons: checked.findings.filter((f) => f.level === 'konflikt').map((f) => f.message),
        confirmText: t('confirmConflict.confirm'),
        cancelText: t('common:actions.cancel'),
        danger: true,
      });
      if (!ok) return;
    }
    await printFlow.run(source, { copies, chain, cut_marks: cutMarks, cut_pause_s: cutPauseS });
  };

  // Gekürzte Feldwerte (max_len/Band-Länge) als eigene Hinweise, damit Nutzer die Kürzung bemerken.
  const shortenedNotes = useMemo(() => {
    const shortened = render.data?.shortened ?? [];
    if (shortened.length === 0) return [];
    const fields = template ? (template.fields.length ? template.fields : template.input_fields) : [];
    return shortened.map((id) => t('shortened', { label: fields.find((f) => f.id === id)?.label ?? id }));
  }, [render.data, template, t]);

  const selectTemplate = (name: string) => {
    setFileDefinition(null);
    setSelectedName(name);
    lastAppliedTemplate.current = null;
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set('vorlage', name);
      next.delete('werte');
      next.delete('serie');
      return next;
    });
  };

  const fillSample = () => {
    if (!template) return;
    setValues((prev) => ({ ...prev, ...template.sample }));
  };

  const onExport = async (format: 'png' | 'pdf' | 'pbm') => {
    if (!source) return;
    const { exportLabel } = await import('../../api/labels');
    try {
      await exportLabel(source, { copies, chain, cut_marks: cutMarks }, format);
    } catch (err) {
      notify({ intent: 'error', title: err instanceof ApiError ? err.message : t('notify.exportFailed') });
    }
  };

  const onDelete = async () => {
    if (!template) return;
    const ok = await confirm({
      title: t('deleteDialog.title'),
      message: t('deleteDialog.message', { name: template.name }),
      confirmText: t('deleteDialog.confirm'),
      danger: true,
    });
    if (!ok) return;
    try {
      await deleteTemplate(template.name);
      notify({ intent: 'success', title: t('notify.deleted', { name: template.name }) });
      setSelectedName(null);
      void queryClient.invalidateQueries({ queryKey: ['vorlagen-liste'] });
    } catch (err) {
      notify({ intent: 'error', title: err instanceof ApiError ? err.message : t('notify.deleteFailed') });
    }
  };

  const onOpenFile = async (file: File) => {
    try {
      const b64 = await readFileAsB64(file);
      const res = await parseTemplateFile(file.name, b64);
      setFileDefinition({ name: res.name, definition: res.definition });
    } catch (err) {
      notify({ intent: 'error', title: err instanceof ApiError ? err.message : t('notify.fileReadFailed') });
    }
  };

  const onExportAssignment = async () => {
    if (!template) return;
    try {
      await exportAssignment(template.name, values);
    } catch (err) {
      notify({ intent: 'error', title: err instanceof ApiError ? err.message : t('notify.assignmentExportFailed') });
    }
  };

  useRegisterCommands(
    [
      {
        id: 'druck.aktuell',
        title: t('common:actions.print'),
        group: 'print',
        run: () => {
          void onDrucken();
        },
        enabled: () => Boolean(source) && missingRequired.length === 0,
      },
      {
        id: 'vorlage.serie-import',
        title: t('batch.commandTitle'),
        group: 'templates',
        run: () => setBatchOpen(true),
        enabled: () => Boolean(template),
      },
    ],
    [source, copies, chain, cutMarks, cutPauseS, missingRequired.length, template, plausi.worst, t],
  );

  // ?serie=1 öffnet den Dialog automatisch.
  const appliedSerie = useRef(false);
  useEffect(() => {
    if (params.get('serie') === '1' && template && !appliedSerie.current) {
      appliedSerie.current = true;
      setBatchOpen(true);
    }
  }, [params, template]);

  const importParam = params.get('import');
  const isGenerator = template?.kind === 'generator';
  const canEditInEditor = template?.kind === 'document' || template?.kind === 'layout';
  const fieldsForForm = template ? (template.fields.length ? template.fields : template.input_fields) : [];

  if (list.isLoading) {
    return (
      <>
        <PageHeader title={t('title')} />
        <LoadingState variant="page" label={t('list.loading')} />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={t('title')}
        subtitle={template?.description}
        actions={
          <>
            <label>
              <input
                type="file"
                accept=".json"
                style={{ display: 'none' }}
                id="vorlage-datei-input"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = '';
                  if (file) void onOpenFile(file);
                }}
              />
            </label>
            <Button onClick={() => document.getElementById('vorlage-datei-input')?.click()}>{t('openFile')}</Button>
          </>
        }
      />

      <div className={narrow ? styles.layoutNarrow : styles.layout}>
        <div className={styles.listCol} role="group" aria-label={t('list.label')}>
          <Combobox
            aria-label={t('list.select')}
            value={template ? (template.title ?? template.name) : ''}
            selectedOptions={template ? [template.name] : []}
            onOptionSelect={(_e, d) => d.optionValue && selectTemplate(d.optionValue)}
          >
            {templates.map((tpl) => (
              <Option key={tpl.name} value={tpl.name} text={tpl.title ?? tpl.name}>
                {tpl.title ?? tpl.name}
              </Option>
            ))}
          </Combobox>
          {/* Auf schmalen Bildschirmen (< 640 px) genügt die Combobox zur Auswahl, Suche und Kategorie-Knöpfe entfallen. */}
          {!narrow ? (
            <SearchBox
              aria-label={t('list.search')}
              placeholder={t('list.searchPlaceholder')}
              value={search}
              onChange={(_e, d) => setSearch(d.value)}
            />
          ) : null}
          {!narrow && categories.length === 0 ? <p className={styles.noHits}>{t('list.noHits')}</p> : null}
          {!narrow
            ? categories.map((cat) => (
                <div key={cat.name}>
                  <h2 className={styles.categoryTitle}>{cat.name}</h2>
                  {cat.templates.map((tpl) => (
                    <Button
                      key={tpl.name}
                      appearance={tpl.name === template?.name ? 'primary' : 'subtle'}
                      className={styles.listButton}
                      onClick={() => selectTemplate(tpl.name)}
                    >
                      {tpl.title ?? tpl.name}
                    </Button>
                  ))}
                </div>
              ))
            : null}
        </div>

        <Section title={t('sections.form')}>
          {template ? (
            <>
              <TemplateForm
                fields={fieldsForForm}
                values={values}
                computed={render.data?.values ?? null}
                onChange={(id, value) => setValues((prev) => ({ ...prev, [id]: value }))}
              />
              <Button className={styles.secondary} onClick={fillSample}>
                {t('fillSample')}
              </Button>
              {template.tape_reason ? (
                <MessageBar intent="warning">
                  <MessageBarBody>
                    {template.tape_reason}
                    {t('tapeReasonSuffix')}
                  </MessageBarBody>
                </MessageBar>
              ) : null}
              <WarningList notes={shortenedNotes} />
              <PlausiHint findings={plausi.findings} />
              <PrintOptionsBar
                value={{ copies, chain, cut_marks: cutMarks, cut_pause_s: cutPauseS, confirmed: false, job_key: null, enqueue_on_offline: true }}
                onChange={(v) => {
                  setCopies(v.copies);
                  setChain(v.chain);
                  setCutMarks(v.cut_marks);
                  setCutPauseS(v.cut_pause_s);
                }}
              />
              <div className={styles.buttons}>
                <Button
                  appearance="primary"
                  disabled={missingRequired.length > 0 || printFlow.busy}
                  onClick={() => void onDrucken()}
                >
                  {t('common:actions.print')}
                </Button>
                <Menu>
                  <MenuTrigger disableButtonEnhancement>
                    <Button icon={<ArrowExport20Regular />}>{t('common:actions.export')}</Button>
                  </MenuTrigger>
                  <MenuPopover>
                    <MenuList>
                      <MenuItem onClick={() => void onExport('png')}>PNG</MenuItem>
                      <MenuItem onClick={() => void onExport('pdf')}>PDF</MenuItem>
                      <MenuItem onClick={() => void onExport('pbm')}>PBM</MenuItem>
                    </MenuList>
                  </MenuPopover>
                </Menu>
                {canEditInEditor ? (
                  <Button onClick={() => navigate(`/editor?vorlage=${encodeURIComponent(template.name)}`)}>{t('editInEditor')}</Button>
                ) : null}
                {isGenerator ? <Button onClick={() => void onExportAssignment()}>{t('exportAssignment')}</Button> : null}
                <Button onClick={() => setBatchOpen(true)}>{t('batchOpen')}</Button>
                {!template.builtin ? <Button onClick={() => void onDelete()}>{t('common:actions.delete')}</Button> : null}
              </div>
            </>
          ) : (
            <p>{t('noTemplateSelected')}</p>
          )}
        </Section>

        <Section title={t('sections.preview')}>
          <TapePreview render={render.data} loading={render.loading} />
        </Section>
      </div>

      {template || importNeedsChoice ? (
        <BatchDialog
          open={batchOpen}
          onOpenChange={setBatchOpen}
          templateName={template?.name ?? null}
          fields={fieldsForForm.filter((f) => f.role !== 'text_size')}
          initialImport={importParam}
          templates={importNeedsChoice ? templates.map((t) => t.name) : undefined}
          onSelectTemplate={selectTemplate}
        />
      ) : null}
    </>
  );
}
