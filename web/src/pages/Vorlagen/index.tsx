/**
 * Vorlagen: links die Vorlagenliste (Titel und Kurzbeschreibung je Kategorie), rechts oben die große
 * Vorschau mit den Druckknöpfen, darunter „Inhalt“ (die Felder der Vorlage) und die einklappbaren
 * „Druckoptionen“. Leere Pflichtfelder blockieren die Vorschau nicht: sie zeigt dann Beispielinhalt
 * (deutlich markiert); gedruckt wird erst, wenn alle Pflichtfelder ausgefüllt sind.
 */
import { useEffect, useId, useMemo, useRef, useState, type ReactElement } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Badge,
  Button,
  Combobox,
  Field,
  Menu,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  MessageBar,
  MessageBarBody,
  Option,
  SearchBox,
  Tooltip,
  makeStyles,
  mergeClasses,
  tokens,
} from '@fluentui/react-components';
import {
  ArrowExport20Regular,
  Briefcase20Regular,
  ChevronDown20Regular,
  ChevronUp20Regular,
  Delete20Regular,
  DocumentArrowUp20Regular,
  Edit20Regular,
  Grid20Regular,
  HardDrive20Regular,
  Home20Regular,
  Info16Regular,
  Lightbulb20Regular,
  PlugConnected20Regular,
  Print20Regular,
  Server20Regular,
  Tag20Regular,
  TableMultiple20Regular,
} from '@fluentui/react-icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../api/client';
import { useLabelRender } from '../../api/labels';
import type { FieldJson, TemplateDetail, TemplateSummary } from '../../api/types';
import { useConfirm } from '../../components/ConfirmProvider';
import { useNotify } from '../../components/NotifyProvider';
import { LoadingState } from '../../components/LoadingState';
import { NavList } from '../../components/NavList';
import { PageHeader } from '../../components/PageHeader';
import { PlausiHint, usePlausi } from '../../components/PlausiHint';
import { PrintOptionsBar } from '../../components/PrintOptionsBar';
import { RowActions } from '../../components/RowActions';
import { Section } from '../../components/Section';
import { TapePreview } from '../../components/TapePreview';
import { TextSizeSelect } from '../../components/TextSizeSelect';
import { WarningList } from '../../components/WarningList';
import { usePrint } from '../../components/usePrint';
import { useRegisterCommands } from '../../commands/CommandProvider';
import { readFileAsB64 } from '../../platform';
import { deleteTemplate, exportAssignment, fetchTemplateDetail, fetchTemplates, parseTemplateFile } from './api';
import { BatchDialog } from './BatchDialog';
import { TemplateForm } from './TemplateForm';
import { categoryKind, placeholderValue, shortDescription, templateFieldId, templateTitle, type CategoryKind } from './templateText';
import { useMediaQuery } from '../../components/useMediaQuery';

/** Darunter einspaltig: Vorlagenwahl als Combobox, dann Vorschau, Inhalt und Druckoptionen untereinander. */
// Liste plus Arbeitsbereich (Vorschau, darunter Inhalt und Optionen nebeneinander) brauchen rund
// 1000 px Inhaltsbreite; bei 200 % Zoom überlagerten sich sonst die Spalten.
const NARROW_QUERY = '(max-width: 1279px)';

const useStyles = makeStyles({
  layout: {
    display: 'grid',
    gridTemplateColumns: 'minmax(220px, 280px) minmax(0, 1fr)',
    columnGap: tokens.spacingHorizontalXL,
    alignItems: 'start',
  },
  /** Eigenständig (statt mit `layout` gemergt): Griffels mergeClasses warnt/verliert Regeln, wenn zwei bereits atomare
   *  makeStyles-Klassen mit überlappenden Eigenschaften zusammengeführt werden. Deshalb per Ternary austauschen. */
  layoutNarrow: { display: 'grid', gridTemplateColumns: '1fr', rowGap: tokens.spacingVerticalL },
  listCol: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalS,
    minWidth: 0,
    position: 'sticky',
    top: tokens.spacingVerticalL,
    maxHeight: `calc(100vh - 120px)`,
    overflowY: 'auto',
    paddingRight: tokens.spacingHorizontalXS,
  },
  listColNarrow: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS, minWidth: 0 },
  categoryTitle: {
    display: 'flex',
    alignItems: 'center',
    columnGap: tokens.spacingHorizontalS,
    margin: `${tokens.spacingVerticalL} 0 ${tokens.spacingVerticalXS}`,
    paddingLeft: tokens.spacingHorizontalS,
    fontSize: tokens.fontSizeBase200,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground3,
  },
  categoryIcon: { display: 'inline-flex', color: tokens.colorNeutralForeground3 },
  noHits: { margin: `${tokens.spacingVerticalS} 0`, color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200 },
  work: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalL, minWidth: 0 },
  /** Inhalt und Druckoptionen nebeneinander, sobald Platz ist, sonst untereinander. */
  columns: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
    columnGap: tokens.spacingHorizontalL,
    rowGap: tokens.spacingVerticalL,
    alignItems: 'start',
  },
  /** Fuß der Vorschau: Hinweis links, Knöpfe rechts; auf schmalen Breiten untereinander. */
  actionBar: {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    justifyContent: 'space-between',
    columnGap: tokens.spacingHorizontalL,
    rowGap: tokens.spacingVerticalM,
    paddingTop: tokens.spacingVerticalM,
    borderTop: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
  },
  buttons: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', columnGap: tokens.spacingHorizontalS, rowGap: tokens.spacingVerticalS, marginLeft: 'auto' },
  /** Schmal: Drucken über die volle Breite oben, darunter Serie/Import und Exportieren nebeneinander. */
  buttonsNarrow: { display: 'grid', gridTemplateColumns: '1fr 1fr', columnGap: tokens.spacingHorizontalS, rowGap: tokens.spacingVerticalS, width: '100%' },
  printNarrow: { gridColumn: '1 / -1', order: -1 },
  status: {
    display: 'flex',
    alignItems: 'center',
    columnGap: tokens.spacingHorizontalS,
    color: tokens.colorNeutralForeground2,
    fontSize: tokens.fontSizeBase300,
    minWidth: 0,
  },
  statusIcon: { display: 'inline-flex', flexShrink: 0, color: tokens.colorNeutralForeground3 },
  statusReady: { color: tokens.colorNeutralForeground3 },
  linkButton: { minWidth: 0, paddingLeft: tokens.spacingHorizontalXS, paddingRight: tokens.spacingHorizontalXS },
  optionsBody: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalL },
  optionsSummary: { color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200, fontWeight: tokens.fontWeightRegular },
  sampleButton: { alignSelf: 'flex-start', marginLeft: `calc(-1 * ${tokens.spacingHorizontalS})` },
  disclosureHeading: { margin: 0 },
  disclosure: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    columnGap: tokens.spacingHorizontalM,
    width: '100%',
    padding: 0,
    border: 'none',
    background: 'none',
    color: 'inherit',
    font: 'inherit',
    textAlign: 'left',
    cursor: 'pointer',
    borderRadius: tokens.borderRadiusMedium,
    ':focus-visible': { outline: `${tokens.strokeWidthThick} solid ${tokens.colorStrokeFocus2}`, outlineOffset: '4px' },
  },
  disclosureText: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXXS, minWidth: 0 },
  disclosureTitle: {
    fontSize: tokens.fontSizeBase400,
    lineHeight: tokens.lineHeightBase400,
    fontWeight: tokens.fontWeightSemibold,
    color: tokens.colorNeutralForeground1,
  },
  disclosureIcon: { display: 'inline-flex', flexShrink: 0, color: tokens.colorNeutralForeground2 },
  textSize: { maxWidth: '320px' },
  hints: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS },
  center: { display: 'grid', placeItems: 'center', padding: tokens.spacingVerticalXXXL },
});

/** Suche in der Vorlagenliste: Name, Titel, Stichworte und Beschreibung, ohne Groß-/Kleinschreibung. */
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

const CATEGORY_ICONS: Record<CategoryKind, ReactElement> = {
  office: <Briefcase20Regular />,
  home: <Home20Regular />,
  homelab: <Server20Regular />,
  disks: <HardDrive20Regular />,
  cables: <PlugConnected20Regular />,
  grid: <Grid20Regular />,
  other: <Tag20Regular />,
};

function inputFields(template: TemplateDetail | null): FieldJson[] {
  if (!template) return [];
  return template.fields.length ? template.fields : template.input_fields;
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
  const formIdPrefix = useId();
  const optionsBodyId = useId();

  const [selectedName, setSelectedName] = useState<string | null>(params.get('vorlage'));
  const [values, setValues] = useState<Record<string, string>>({});
  const [touched, setTouched] = useState<Set<string>>(() => new Set());
  const [showAllErrors, setShowAllErrors] = useState(false);
  const [copies, setCopies] = useState(1);
  const [chain, setChain] = useState(false);
  const [cutMarks, setCutMarks] = useState(true);
  const [cutPauseS, setCutPauseS] = useState<number | null>(null);
  const [optionsOpen, setOptionsOpen] = useState(false);
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
        description: t('fromFile'),
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
  }, [fileDefinition, detail.data, t]);

  // Vorlage wechseln: Werte zurücksetzen, Kopien vorbelegen, Hinweise an Feldern zurücksetzen.
  const lastAppliedTemplate = useRef<string | null>(null);
  useEffect(() => {
    if (!template) return;
    if (lastAppliedTemplate.current === template.name) return;
    lastAppliedTemplate.current = template.name;
    const initial: Record<string, string> = {};
    for (const f of inputFields(template)) {
      if (f.type === 'input') initial[f.id] = f.default ?? '';
    }
    setValues(initial);
    setTouched(new Set());
    setShowAllErrors(false);
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

  const fieldsForForm = inputFields(template);
  const textSizeField = fieldsForForm.find((f) => f.type === 'input' && f.role === 'text_size') ?? null;

  /** Leere Pflichtfelder (ohne Schriftgröße): sie blockieren den Druck, nicht die Vorschau. */
  const missingFields = useMemo(
    () => fieldsForForm.filter((f) => f.type === 'input' && f.required && f.role !== 'text_size' && !(values[f.id] ?? '').trim()),
    [fieldsForForm, values],
  );
  const missingRequired = missingFields.map((f) => f.label);
  const usesPlaceholder = missingFields.length > 0;

  /** Werte für die Vorschau: leere Pflichtfelder mit Beispielwerten, damit immer ein Etikett zu sehen ist. */
  const previewValues = useMemo(() => {
    if (!template || missingFields.length === 0) return values;
    const filled = { ...values };
    for (const f of missingFields) filled[f.id] = placeholderValue(f, template.sample ?? {});
    return filled;
  }, [template, values, missingFields]);

  const makeSource = (vals: Record<string, string>) =>
    template
      ? fileDefinition
        ? ({ kind: 'template' as const, template: template.name, values: vals, definition: fileDefinition.definition })
        : ({ kind: 'template' as const, template: template.name, values: vals })
      : null;
  /** Druck und Export: nur die echten Eingaben, nie Beispielwerte. */
  const source = makeSource(values);
  const previewSource = makeSource(previewValues);

  const render = useLabelRender(previewSource, { copies, chain, cut_marks: cutMarks, cut_pause_s: cutPauseS });

  const printFlow = usePrint();
  const plausi = usePlausi(template?.name ?? null, values);

  const fieldErrors = useMemo(() => {
    const out: Record<string, string> = {};
    for (const f of missingFields) {
      if (showAllErrors || touched.has(f.id)) out[f.id] = t('form.required', { label: f.label });
    }
    return out;
  }, [missingFields, showAllErrors, touched, t]);

  /** Zum ersten leeren Pflichtfeld springen und die Hinweise an allen leeren Pflichtfeldern zeigen. */
  const revealMissing = () => {
    setShowAllErrors(true);
    const first = missingFields[0];
    if (first) document.getElementById(templateFieldId(formIdPrefix, first.id))?.focus();
  };

  const onDrucken = async (): Promise<void> => {
    if (!source) return;
    if (missingFields.length > 0) {
      revealMissing();
      return;
    }
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
    // Gekürzte Beispielwerte sind kein Hinweis wert: nur echte Eingaben melden.
    const placeholderIds = new Set(missingFields.map((f) => f.id));
    const shortened = (render.data?.shortened ?? []).filter((id) => !placeholderIds.has(id));
    if (shortened.length === 0) return [];
    return shortened.map((id) => t('shortened', { label: fieldsForForm.find((f) => f.id === id)?.label ?? id }));
  }, [render.data, fieldsForForm, missingFields, t]);

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
      message: t('deleteDialog.message', { name: templateTitle(template) }),
      confirmText: t('deleteDialog.confirm'),
      danger: true,
    });
    if (!ok) return;
    try {
      await deleteTemplate(template.name);
      notify({ intent: 'success', title: t('notify.deleted', { name: templateTitle(template) }) });
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
  const title = template ? templateTitle(template) : t('title');

  if (list.isLoading) {
    return (
      <>
        <PageHeader title={t('title')} />
        <LoadingState variant="page" label={t('list.loading')} />
      </>
    );
  }

  const cutPauseText =
    cutPauseS === null
      ? t('options.cutPauseDefault')
      : cutPauseS < 0
        ? t('options.cutPauseNone')
        : cutPauseS === 0
          ? t('options.cutPauseManual')
          : t('options.cutPauseSeconds', { seconds: cutPauseS });
  const optionsSummary = [
    t('options.copies', { count: copies }),
    chain ? t('options.chain') : null,
    cutPauseText,
  ]
    .filter(Boolean)
    .join(' · ');

  const missingText = t('missing', { fields: missingRequired.join(', ') });

  const templatePicker = narrow ? (
    <Combobox
      aria-label={t('list.select')}
      value={template ? templateTitle(template) : ''}
      selectedOptions={template ? [template.name] : []}
      onOptionSelect={(_e, d) => d.optionValue && selectTemplate(d.optionValue)}
    >
      {templates.map((tpl) => (
        <Option key={tpl.name} value={tpl.name} text={templateTitle(tpl)}>
          {templateTitle(tpl)}
        </Option>
      ))}
    </Combobox>
  ) : (
    <>
      <SearchBox
        aria-label={t('list.search')}
        placeholder={t('list.searchPlaceholder')}
        value={search}
        onChange={(_e, d) => setSearch(d.value)}
      />
      {categories.length === 0 ? <p className={styles.noHits}>{t('list.noHits')}</p> : null}
      {categories.map((cat) => (
        <div key={cat.name}>
          <h2 className={styles.categoryTitle}>
            <span className={styles.categoryIcon} aria-hidden="true">
              {CATEGORY_ICONS[categoryKind(cat.name)]}
            </span>
            {cat.name}
          </h2>
          <NavList
            items={cat.templates.map((tpl) => ({
              key: tpl.name,
              label: templateTitle(tpl),
              description: tpl.description ? shortDescription(tpl.description) : undefined,
            }))}
            selected={template?.name}
            onSelect={selectTemplate}
          />
        </div>
      ))}
    </>
  );

  return (
    <>
      <input
        type="file"
        accept=".json"
        style={{ display: 'none' }}
        id="vorlage-datei-input"
        aria-hidden="true"
        tabIndex={-1}
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = '';
          if (file) void onOpenFile(file);
        }}
      />
      <PageHeader
        title={title}
        subtitle={template?.description}
        actions={
          <>
            <Button appearance="subtle" icon={<DocumentArrowUp20Regular />} onClick={() => document.getElementById('vorlage-datei-input')?.click()}>
              {t('openFile')}
            </Button>
            {template ? (
              <RowActions
                title={title}
                actions={[
                  {
                    key: 'editor',
                    label: t('editInEditor'),
                    icon: <Edit20Regular />,
                    hidden: !canEditInEditor,
                    onClick: () => navigate(`/editor?vorlage=${encodeURIComponent(template.name)}`),
                  },
                  {
                    key: 'assignment',
                    label: t('exportAssignment'),
                    icon: <ArrowExport20Regular />,
                    hidden: !isGenerator,
                    onClick: () => void onExportAssignment(),
                  },
                  {
                    key: 'delete',
                    label: t('common:actions.delete'),
                    icon: <Delete20Regular />,
                    danger: true,
                    hidden: template.builtin,
                    onClick: () => void onDelete(),
                  },
                ]}
              />
            ) : null}
          </>
        }
      />

      <div className={narrow ? styles.layoutNarrow : styles.layout}>
        <div className={narrow ? styles.listColNarrow : styles.listCol} role="group" aria-label={t('list.label')}>
          {templatePicker}
        </div>

        <div className={styles.work}>
          <Section
            title={t('sections.preview')}
            actions={
              usesPlaceholder && render.data?.preview ? (
                <Tooltip content={t('placeholder.tooltip')} relationship="description">
                  <Badge appearance="tint" color="informative" shape="rounded" icon={<Lightbulb20Regular />}>
                    {t('placeholder.badge')}
                  </Badge>
                </Tooltip>
              ) : undefined
            }
          >
            <TapePreview render={render.data} loading={render.loading} />
            <div className={styles.hints}>
              {template?.tape_reason ? (
                <MessageBar intent="warning">
                  <MessageBarBody>
                    {template.tape_reason}
                    {t('tapeReasonSuffix')}
                  </MessageBarBody>
                </MessageBar>
              ) : null}
              <WarningList notes={shortenedNotes} />
              <PlausiHint findings={plausi.findings} />
            </div>
            {template ? (
              <div className={styles.actionBar}>
                {usesPlaceholder ? (
                  <div className={styles.status} role="status">
                    <span className={styles.statusIcon} aria-hidden="true">
                      <Info16Regular />
                    </span>
                    <span>{missingText}</span>
                    <Button appearance="transparent" size="small" className={styles.linkButton} onClick={revealMissing}>
                      {t('missingAction')}
                    </Button>
                  </div>
                ) : (
                  <span className={mergeClasses(styles.status, styles.statusReady)}>{t('ready')}</span>
                )}
                <div className={narrow ? styles.buttonsNarrow : styles.buttons}>
                  <Button icon={<TableMultiple20Regular />} onClick={() => setBatchOpen(true)}>
                    {t('batchOpen')}
                  </Button>
                  <Menu>
                    <MenuTrigger disableButtonEnhancement>
                      <Button icon={<ArrowExport20Regular />} disabledFocusable={usesPlaceholder}>
                        {t('common:actions.export')}
                      </Button>
                    </MenuTrigger>
                    <MenuPopover>
                      <MenuList>
                        <MenuItem onClick={() => void onExport('png')}>PNG</MenuItem>
                        <MenuItem onClick={() => void onExport('pdf')}>PDF</MenuItem>
                        <MenuItem onClick={() => void onExport('pbm')}>PBM</MenuItem>
                      </MenuList>
                    </MenuPopover>
                  </Menu>
                  <Tooltip
                    content={usesPlaceholder ? missingText : t('printTooltip')}
                    relationship="description"
                  >
                    <Button
                      appearance="primary"
                      icon={<Print20Regular />}
                      className={narrow ? styles.printNarrow : undefined}
                      disabledFocusable={usesPlaceholder}
                      disabled={!usesPlaceholder && printFlow.busy}
                      onClick={() => void onDrucken()}
                    >
                      {t('common:actions.print')}
                    </Button>
                  </Tooltip>
                </div>
              </div>
            ) : null}
          </Section>

          <div className={styles.columns}>
            <Section title={t('sections.content')}>
              {template ? (
                fieldsForForm.filter((f) => f.role !== 'text_size').length > 0 ? (
                  <TemplateForm
                    fields={fieldsForForm}
                    values={values}
                    computed={render.data?.values ?? null}
                    onChange={(id, value) => setValues((prev) => ({ ...prev, [id]: value }))}
                    onBlur={(id) => setTouched((prev) => (prev.has(id) ? prev : new Set(prev).add(id)))}
                    errors={fieldErrors}
                    idPrefix={formIdPrefix}
                    omitTextSize
                    samples={template.sample}
                  />
                ) : (
                  <p className={styles.optionsSummary}>{t('noFields')}</p>
                )
              ) : (
                <p>{t('noTemplateSelected')}</p>
              )}
              {template && Object.keys(template.sample ?? {}).length > 0 ? (
                <Button appearance="subtle" icon={<Lightbulb20Regular />} className={styles.sampleButton} onClick={fillSample}>
                  {t('fillSample')}
                </Button>
              ) : null}
            </Section>

            <Section>
              {/* Aufklapp-Muster: Überschrift mit einem Knopf über die ganze Breite (Titel, Zusammenfassung, Pfeil). */}
              <h2 className={styles.disclosureHeading}>
                <button
                  type="button"
                  className={styles.disclosure}
                  aria-expanded={optionsOpen}
                  aria-controls={optionsBodyId}
                  onClick={() => setOptionsOpen((o) => !o)}
                >
                  <span className={styles.disclosureText}>
                    <span className={styles.disclosureTitle}>{t('sections.options')}</span>
                    <span className={styles.optionsSummary}>{optionsSummary}</span>
                  </span>
                  <span className={styles.disclosureIcon} aria-hidden="true">
                    {optionsOpen ? <ChevronUp20Regular /> : <ChevronDown20Regular />}
                  </span>
                </button>
              </h2>
              {optionsOpen ? (
                <div id={optionsBodyId} className={styles.optionsBody}>
                  {textSizeField ? (
                    <Field label={t('components:textSize.label')} className={styles.textSize}>
                      <TextSizeSelect
                        value={values[textSizeField.id] ?? ''}
                        choices={textSizeField.choices}
                        onChange={(v) => setValues((prev) => ({ ...prev, [textSizeField.id]: v }))}
                      />
                    </Field>
                  ) : null}
                  <PrintOptionsBar
                    value={{ copies, chain, cut_marks: cutMarks, cut_pause_s: cutPauseS, confirmed: false, job_key: null, enqueue_on_offline: true }}
                    onChange={(v) => {
                      setCopies(v.copies);
                      setChain(v.chain);
                      setCutMarks(v.cut_marks);
                      setCutPauseS(v.cut_pause_s);
                    }}
                  />
                </div>
              ) : null}
            </Section>
          </div>
        </div>
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
