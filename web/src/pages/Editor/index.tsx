/**
 * Editor: WYSIWYG-Objekteditor mit Tabs.
 * Das Bild rendert immer der Server; jede Bearbeitung ist eine Operation an `/editor/op` bzw.
 * `/editor/new-object`, das Ergebnis-Dokument landet im Undo-Stapel des Tabs und wird neu gerendert.
 *
 * Je Tab gehalten: Undo-Stapel, Dokumentname, Titel (`useEditorTabs`), dazu Auswahl, Zoom und
 * Panel-Reiter (Map nach Tab-ID). Jeder Tab wird als Entwurf gesichert (`useDraftSync`); eigene
 * Entwürfe kommen beim Öffnen still zurück, verwaiste bietet `RecoveryDialog` an.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import {
  Button,
  Caption1,
  DrawerBody,
  DrawerHeader,
  DrawerHeaderTitle,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  OverlayDrawer,
  Spinner,
  Tab,
  TabList,
  makeStyles,
  mergeClasses,
  tokens,
} from '@fluentui/react-components';
import { Dismiss20Regular, DocumentOnePage24Regular, PanelRight20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { qk, useAppInfo, useFonts } from '../../api/core';
import { adoptDraft, deleteDraft, getDraft, listDrafts } from '../../api/drafts';
import { exportLabel, useLabelRender } from '../../api/labels';
import {
  DEFAULT_PRINT_OPTIONS,
  type DocumentSource,
  type Draft,
  type DraftInfo,
  type EditOp,
  type EditResult,
  type EditorPreset,
  type Guide,
  type LabelDocumentJson,
  type PrintOptions,
} from '../../api/types';
import { registerUnsaved } from '../../api/unsaved';
import { useRegisterCommands } from '../../commands/CommandProvider';
import { useShortcut } from '../../commands/shortcuts';
import { EmptyState } from '../../components/EmptyState';
import { useErrorText } from '../../components/ErrorMessage';
import { LoadingState } from '../../components/LoadingState';
import { useNotify } from '../../components/NotifyProvider';
import { PageHeader } from '../../components/PageHeader';
import { PrintOptionsBar } from '../../components/PrintOptionsBar';
import { TapePreview } from '../../components/TapePreview';
import { usePrint } from '../../components/usePrint';
import { readFileAsB64 } from '../../platform';
import { EditorCanvas, type SnapQuery } from './EditorCanvas';
import {
  EMPTY_DOC,
  applyOp,
  fetchPending,
  fromHistory,
  fromTemplate,
  loadDocument,
  newObject,
  saveDocument,
  snap,
  uploadImage,
} from './editorApi';
import { arrowDelta, cssPxPerDot, resizeBox, zoomScale, type Box, type Handle, type Point, type Zoom } from './geometry';
import { HistoryPanel } from './HistoryPanel';
import { IconPickerDialog } from './IconPickerDialog';
import { LabelSettings } from './LabelSettings';
import { LayersPanel, type ReorderOp } from './LayersPanel';
import { OpenDialog, SaveAsDialog } from './OpenDialog';
import { Palette } from './Palette';
import { objectTitle, presetForKey, useKindName } from './presets';
import { PropertiesPanel, type AlignMode, type PropertiesActions } from './PropertiesPanel';
import { SaveAsTemplateDialog } from './SaveAsTemplateDialog';
import { CloseTabDialog } from './tabs/CloseTabDialog';
import { EditorTabs } from './tabs/EditorTabs';
import { RecoveryDialog } from './tabs/RecoveryDialog';
import { putLeftoverBack, settleDraftWrites, takeLeftoverDrafts, useDraftSync } from './tabs/useDraftSync';
import { isTabDirty, useEditorTabs, type TabMeta, type TabSeed } from './tabs/useEditorTabs';
import { EditorToolbar } from './Toolbar';
import { canRedo, canUndo, current, jump, labels, push, redo, undo, type UndoState } from './undoStack';
import { useElementWidth, useMediaQuery } from './useMediaQuery';

const RENDER_DEBOUNCE_MS = 120;
const NUDGE_MERGE_MS = 500;
const GUIDE_FLASH_MS = 900;
/** Merker je Fenster: verwaiste Entwürfe wurden schon angeboten (sessionStorage überlebt Neuladen). */
const RECOVERY_OFFERED_KEY = 'p12.editor.recoveryOffered';

type PanelTab = 'props' | 'layers' | 'history';
type ImageTarget = { mode: 'new'; at?: Point } | { mode: 'replace'; id: string };

interface EditOpts {
  mergeKey?: string;
  windowMs?: number;
  /** Tab, in dem die Bearbeitung entstand (Standard: der aktive). */
  tabId?: string;
}

interface TabView {
  selection: string[];
  zoom: Zoom;
  panel: PanelTab;
}

const DEFAULT_VIEW: TabView = { selection: [], zoom: 'fit', panel: 'props' };

const useStyles = makeStyles({
  root: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM, minWidth: 0 },
  docName: {
    display: 'flex',
    alignItems: 'center',
    columnGap: tokens.spacingHorizontalS,
    color: tokens.colorNeutralForeground2,
    fontSize: tokens.fontSizeBase400,
  },
  dot: { width: '8px', height: '8px', borderRadius: '50%', backgroundColor: tokens.colorPaletteDarkOrangeBackground3, flexShrink: 0 },
  body: { display: 'grid', gridTemplateColumns: 'auto minmax(0, 1fr) 340px', columnGap: tokens.spacingHorizontalM, alignItems: 'start' },
  bodyNarrow: { gridTemplateColumns: 'auto minmax(0, 1fr)' },
  bodyTiny: { gridTemplateColumns: 'minmax(0, 1fr)', rowGap: tokens.spacingVerticalM },
  stage: {
    position: 'relative',
    minHeight: '220px',
    minWidth: 0,
    display: 'flex',
    flexDirection: 'column',
    justifyContent: 'center',
    rowGap: tokens.spacingVerticalL,
    padding: `${tokens.spacingVerticalXXL} ${tokens.spacingHorizontalXL}`,
    borderRadius: tokens.borderRadiusXLarge,
    backgroundColor: tokens.colorNeutralBackground3,
    backgroundImage: `radial-gradient(${tokens.colorNeutralStroke3} 1px, transparent 1px)`,
    backgroundSize: '16px 16px',
    overflow: 'auto',
  },
  stageBusy: { position: 'absolute', top: tokens.spacingVerticalS, right: tokens.spacingHorizontalS },
  panels: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalM,
    padding: tokens.spacingHorizontalL,
    backgroundColor: tokens.colorNeutralBackground1,
    borderRadius: tokens.borderRadiusXLarge,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    boxShadow: tokens.shadow4,
    maxHeight: 'calc(100vh - 220px)',
    minHeight: '320px',
    overflowY: 'auto',
    '@media (forced-colors: active)': { border: `${tokens.strokeWidthThin} solid CanvasText` },
  },
  bottom: {
    display: 'grid',
    gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1fr)',
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalM,
    padding: tokens.spacingHorizontalL,
    backgroundColor: tokens.colorNeutralBackground1,
    borderRadius: tokens.borderRadiusXLarge,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    boxShadow: tokens.shadow4,
  },
  bottomNarrow: { gridTemplateColumns: 'minmax(0, 1fr)' },
  issues: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS },
  issuesTitle: { margin: 0, fontSize: tokens.fontSizeBase300, fontWeight: tokens.fontWeightSemibold },
  issue: {
    justifyContent: 'flex-start',
    textAlign: 'left',
    height: 'auto',
    padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`,
    fontWeight: tokens.fontWeightRegular,
  },
  issueError: { borderLeft: `${tokens.strokeWidthThicker} solid ${tokens.colorPaletteRedBorder2}` },
  issueWarn: { borderLeft: `${tokens.strokeWidthThicker} solid ${tokens.colorPaletteDarkOrangeBorder2}` },
  muted: { color: tokens.colorNeutralForeground3 },
  hiddenInput: { position: 'absolute', width: '1px', height: '1px', opacity: 0, overflow: 'hidden' },
});

function downloadJson(doc: LabelDocumentJson, name: string): void {
  const blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${name}.p12doc.json`;
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function recoveryOffered(): boolean {
  try {
    return sessionStorage.getItem(RECOVERY_OFFERED_KEY) === '1';
  } catch {
    return false;
  }
}

function markRecoveryOffered(): void {
  try {
    sessionStorage.setItem(RECOVERY_OFFERED_KEY, '1');
  } catch {
    // ohne Speicher: beim nächsten Öffnen erneut anbieten
  }
}

/**
 * Gibt den Fokus nach dem Schließen eines Dialogs an das zuletzt fokussierte Element außerhalb von
 * Dialogen zurück (die Dialoge des Editors werden beim Schließen entfernt, nicht nur verborgen).
 */
function useDialogFocusReturn(open: boolean): void {
  const last = useRef<HTMLElement | null>(null);
  const wasOpen = useRef(open);
  useEffect(() => {
    const onFocus = (e: FocusEvent) => {
      const el = e.target;
      if (el instanceof HTMLElement && !el.closest('[role="dialog"], [role="alertdialog"], [role="menu"]')) last.current = el;
    };
    document.addEventListener('focusin', onFocus);
    return () => document.removeEventListener('focusin', onFocus);
  }, []);
  useEffect(() => {
    const closed = wasOpen.current && !open;
    wasOpen.current = open;
    if (!closed) return undefined;
    const timer = setTimeout(() => {
      const el = last.current;
      const lost = !document.activeElement || document.activeElement === document.body;
      if (el && el.isConnected && lost) el.focus();
    }, 0);
    return () => clearTimeout(timer);
  }, [open]);
}

export default function EditorPage(): JSX.Element {
  const styles = useStyles();
  const { t, i18n } = useTranslation('editor');
  const errorText = useErrorText();
  const kindName = useKindName();
  const app = useAppInfo().data;
  const fonts = useFonts().data?.fonts ?? [];
  const notify = useNotify();
  const queryClient = useQueryClient();
  const location = useLocation();
  const navigate = useNavigate();
  const print = usePrint();
  const wide = !useMediaQuery('(max-width: 1023px)');
  const tiny = useMediaQuery('(max-width: 639px)');

  const showError = useCallback(
    (err: unknown) => {
      const e = errorText(err);
      notify({ intent: 'error', title: e.title, body: e.message || undefined, hint: e.hint || undefined });
    },
    [errorText, notify],
  );

  // --- Tabs und Ansicht je Tab ------------------------------------------------------
  const untitled = useCallback((n: number) => (n <= 1 ? t('untitled') : t('untitledN', { n })), [t]);
  const onLimit = useCallback(() => notify({ intent: 'warning', title: t('notify.tabLimit'), body: t('notify.tabLimitBody') }), [notify, t]);
  const tabsApi = useEditorTabs({ untitled, onLimit });
  const {
    get: getTabs,
    tab: getTab,
    updateUndo,
    markSaved: markTabSaved,
    newTab,
    closeTab,
    activate,
    next: nextTab,
    prev: prevTab,
    openDocument,
    replaceActiveIfEmpty,
    findByDocName,
    restore: restoreTabs,
  } = tabsApi;
  const tabsState = tabsApi.state;
  const activeTab = tabsState.tabs.find((x) => x.id === tabsState.activeId) ?? tabsState.tabs[0]!;
  const activeId = activeTab.id;
  const undoState = activeTab.undo;
  const doc = current(undoState);
  const docName = activeTab.docName;
  const unsaved = isTabDirty(activeTab);

  const [views, setViews] = useState<Record<string, TabView>>({});
  const viewsRef = useRef(views);
  const view = views[activeId] ?? DEFAULT_VIEW;
  const { selection, zoom, panel } = view;
  const updateView = useCallback((id: string, patch: Partial<TabView>) => {
    const next = { ...viewsRef.current, [id]: { ...(viewsRef.current[id] ?? DEFAULT_VIEW), ...patch } };
    viewsRef.current = next;
    setViews(next);
  }, []);
  const dropView = useCallback((id: string) => {
    if (!(id in viewsRef.current)) return;
    const next = { ...viewsRef.current };
    delete next[id];
    viewsRef.current = next;
    setViews(next);
  }, []);
  /** Auswahl des aktiven Tabs (immer aktuell, auch zwischen zwei Renderläufen). */
  const sel = useCallback(() => viewsRef.current[getTabs().activeId]?.selection ?? [], [getTabs]);
  const setSelection = useCallback((ids: string[]) => updateView(getTabs().activeId, { selection: ids }), [getTabs, updateView]);
  const setZoom = useCallback((z: Zoom) => updateView(getTabs().activeId, { zoom: z }), [getTabs, updateView]);
  const setPanel = useCallback((p: PanelTab) => updateView(getTabs().activeId, { panel: p }), [getTabs, updateView]);
  const activeUndo = useCallback(() => {
    const s = getTabs();
    return (s.tabs.find((x) => x.id === s.activeId) ?? s.tabs[0]!).undo;
  }, [getTabs]);
  const commitUndo = useCallback((next: UndoState) => updateUndo(getTabs().activeId, next), [getTabs, updateUndo]);

  const [ready, setReady] = useState(false);
  const [guides, setGuides] = useState<Guide[]>([]);
  const [grid, setGrid] = useState(false);
  const [snapOn, setSnapOn] = useState(true);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [printOptions, setPrintOptions] = useState<PrintOptions>(DEFAULT_PRINT_OPTIONS);
  const [openOpen, setOpenOpen] = useState(false);
  const [saveAsFor, setSaveAsFor] = useState<{ id: string; closeAfter: boolean } | null>(null);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [iconTarget, setIconTarget] = useState<string | null>(null);
  const [recovery, setRecovery] = useState<DraftInfo[] | null>(null);
  const [closing, setClosing] = useState<string | null>(null);
  const imageInput = useRef<HTMLInputElement>(null);
  const imageTarget = useRef<ImageTarget>({ mode: 'new' });
  const [stageEl, setStageEl] = useState<HTMLDivElement | null>(null);
  const stageWidth = useElementWidth(stageEl);
  const opQueue = useRef<Promise<unknown>>(Promise.resolve());
  const guideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handledSearch = useRef<string | null>(null);
  const locationRef = useRef(location);
  locationRef.current = location;

  const dotsPerMm = app?.profile.dots_per_mm ?? 8;
  const base = cssPxPerDot(app?.screen_px_per_mm, dotsPerMm);
  const dialogOpen = openOpen || saveAsFor !== null || templateOpen || iconTarget !== null || recovery !== null || closing !== null;
  useDialogFocusReturn(dialogOpen);

  // --- Autosave und Ungespeichert-Register --------------------------------------------
  const sync = useDraftSync(tabsState.tabs, { enabled: ready });
  const discardDraft = sync.discard;
  useEffect(() => registerUnsaved('editor', () => getTabs().tabs.filter(isTabDirty).length), [getTabs]);

  const flashGuides = useCallback((g: Guide[]) => {
    if (guideTimer.current) clearTimeout(guideTimer.current);
    setGuides(g);
    if (g.length) guideTimer.current = setTimeout(() => setGuides([]), GUIDE_FLASH_MS);
  }, []);
  useEffect(
    () => () => {
      if (guideTimer.current) clearTimeout(guideTimer.current);
    },
    [],
  );

  /**
   * Führt Bearbeitungen nacheinander aus; jede arbeitet auf dem jeweils aktuellen Dokument ihres Tabs.
   * `tabId` bindet die Bearbeitung an den Tab, in dem sie entstand (Panels: eine entprellte Eingabe
   * kann erst nach einem Tabwechsel ankommen), sonst gilt der aktive Tab.
   */
  const runEdit = useCallback(
    (task: (d: LabelDocumentJson) => Promise<EditResult>, opts?: EditOpts): Promise<EditResult | null> => {
      const tabId = opts?.tabId ?? getTabs().activeId;
      const next = opQueue.current.then(async () => {
        const before = getTab(tabId);
        if (!before) return null;
        try {
          const res = await task(current(before.undo));
          const after = getTab(tabId);
          if (!after) return null;
          updateUndo(tabId, push(after.undo, res.document, res.step_label, { mergeKey: opts?.mergeKey, windowMs: opts?.windowMs }));
          updateView(tabId, { selection: res.selected });
          if (getTabs().activeId === tabId) flashGuides(res.guides ?? []);
          return res;
        } catch (err) {
          showError(err);
          return null;
        }
      });
      opQueue.current = next;
      return next;
    },
    [flashGuides, getTab, getTabs, showError, updateUndo, updateView],
  );

  const op = useCallback(
    (name: EditOp, ids: string[], params: Record<string, unknown> = {}, opts?: EditOpts) =>
      runEdit((d) => applyOp(d, name, ids, params), opts),
    [runEdit],
  );

  const movableSelection = useCallback(
    () => sel().filter((id) => current(activeUndo()).objects.find((o) => o.id === id)?.locked !== true),
    [activeUndo, sel],
  );

  // --- Öffnen in Tabs ----------------------------------------------------------------
  const openInTab = useCallback(
    (next: LabelDocumentJson, meta: TabMeta) => {
      const id = meta.docName ? openDocument(next, meta) : replaceActiveIfEmpty(next, meta);
      if (id) updateView(id, { selection: [] });
      return id;
    },
    [openDocument, replaceActiveIfEmpty, updateView],
  );

  const seedFromDraft = useCallback(
    (d: Draft): TabSeed => ({ id: d.id, title: d.title, docName: d.doc_name, document: d.document, dirty: d.dirty, label: t('steps.restored') }),
    [t],
  );

  const offerRecovery = useCallback(async () => {
    try {
      const list = await listDrafts();
      if (list.orphaned.length) setRecovery(list.orphaned);
    } catch (err) {
      showError(err);
    }
  }, [showError]);

  /** Verarbeitet `?dokument=`, `?verlauf=`, `?vorlage=`, `?import=` und `?wiederherstellen=1` einmal je Aufruf. */
  const processQuery = useCallback(
    async (search: string, initial: boolean) => {
      if (handledSearch.current === search) return;
      handledSearch.current = search;
      const q = new URLSearchParams(search);
      const dokument = q.get('dokument');
      const verlauf = q.get('verlauf');
      const vorlage = q.get('vorlage');
      const importId = q.get('import');
      const wiederherstellen = q.get('wiederherstellen');
      if (!dokument && !verlauf && !vorlage && !importId && !wiederherstellen) return;
      let importTab: string | null = null;
      try {
        if (dokument) {
          const existing = findByDocName(dokument);
          if (existing) activate(existing.id);
          else {
            const r = await loadDocument(dokument);
            openInTab(r.document, { docName: r.name, label: t('steps.opened', { name: r.name }) });
          }
        } else if (verlauf) {
          const r = await fromHistory(verlauf);
          openInTab(r.document, { label: t('steps.fromHistory') });
        } else if (vorlage) {
          const r = await fromTemplate(vorlage);
          openInTab(r.document, { label: t('steps.fromTemplate', { name: vorlage }) });
        } else if (importId) {
          importTab = openInTab(EMPTY_DOC, { label: t('steps.new') });
        }
      } catch (err) {
        showError(err);
      }
      if (wiederherstellen && !initial) await offerRecovery();
      // Query entfernen: Neuladen öffnet nichts doppelt (die Tabs kommen über die Entwürfe zurück)
      navigate({ search: '' }, { replace: true });
      if (importId && importTab) {
        try {
          const pending = await fetchPending(importId);
          if (pending.type !== 'image') {
            notify({ intent: 'warning', title: t('notify.importNoImage'), body: t('notify.importNoImageBody') });
            return;
          }
          const up = await uploadImage(pending.data_b64, pending.name);
          if (getTabs().activeId === importTab) await runEdit((d) => newObject(d, 'image', { png: up.png }));
        } catch (err) {
          showError(err);
        }
      }
    },
    [activate, findByDocName, getTabs, navigate, notify, offerRecovery, openInTab, runEdit, showError, t],
  );

  // --- Erstes Öffnen: eigene Entwürfe still zurück, verwaiste anbieten, dann die Query ------
  useEffect(() => {
    let alive = true;
    void (async () => {
      // Sicherungen eines eben verlassenen Editors erst ankommen lassen; was trotzdem nicht ankam, ist
      // neuer als der Entwurf auf dem Server und ersetzt ihn (Tab wird dann neu gesichert).
      await settleDraftWrites();
      const leftovers = takeLeftoverDrafts();
      const giveBack = () => {
        for (const [id, body] of leftovers) putLeftoverBack(id, body);
      };
      let own: DraftInfo[] = [];
      let orphaned: DraftInfo[] = [];
      try {
        const list = await listDrafts();
        own = list.own ?? [];
        orphaned = list.orphaned ?? [];
      } catch {
        // ältere Druckdienste ohne Entwürfe: einfach leer beginnen
      }
      if (!alive) return giveBack();
      const seeds: TabSeed[] = [];
      for (const info of own) {
        if (leftovers.has(info.id)) continue;
        try {
          seeds.push(seedFromDraft(await getDraft(info.id)));
        } catch {
          // einzelner Entwurf nicht lesbar: überspringen
        }
        if (!alive) return giveBack();
      }
      const ownOrder = new Map(own.map((info) => [info.id, info.order]));
      const leftoverSeeds = [...leftovers.entries()].map(
        ([id, body]): TabSeed => ({
          id,
          title: body.title,
          docName: body.doc_name,
          document: body.document,
          dirty: body.dirty,
          label: t('steps.restored'),
          unsynced: true,
        }),
      );
      // Reihenfolge wie beim Verlassen (Tab-Position aus der Übergabe bzw. dem Entwurf)
      const position = (seed: TabSeed): number => leftovers.get(seed.id)?.order ?? ownOrder.get(seed.id) ?? 0;
      seeds.push(...leftoverSeeds);
      seeds.sort((x, y) => position(x) - position(y));
      if (seeds.length) restoreTabs(seeds);
      const search = locationRef.current.search;
      const wanted = new URLSearchParams(search).get('wiederherstellen') !== null;
      // Nur ein tatsächlich gezeigtes Angebot zählt: Entwürfe eines eben beendeten Fensters gelten
      // erst nach 90 s ohne Lebenszeichen als verwaist und sollen beim nächsten Öffnen noch kommen.
      if (orphaned.length && (wanted || !recoveryOffered())) {
        setRecovery(orphaned);
        markRecoveryOffered();
      }
      await processQuery(search, true);
      if (alive) setReady(true);
    })();
    return () => {
      alive = false;
    };
    // nur beim ersten Öffnen
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (ready) void processQuery(location.search, false);
  }, [location.search, processQuery, ready]);

  // --- Rendern ----------------------------------------------------------------------
  const source = useMemo<DocumentSource | null>(
    () => (ready ? (docName ? { kind: 'document', document: doc, title: docName } : { kind: 'document', document: doc }) : null),
    [ready, doc, docName],
  );
  const render = useLabelRender(source, undefined, { debounceMs: RENDER_DEBOUNCE_MS });
  const overlay = render.data?.editor ?? null;
  const printBlock = !render.data ? t('printBlock.preview') : !render.data.ok ? t('printBlock.errors') : null;
  const printBlockRef = useRef(printBlock);
  printBlockRef.current = printBlock;
  const widthDots = overlay?.width ?? Math.round(40 * dotsPerMm);
  const heightDots = overlay?.height ?? app?.profile.head_dots ?? 96;
  const scale = zoomScale(zoom, base, widthDots, Math.max(0, stageWidth - 48));

  // Auswahl bereinigen, wenn Objekte verschwinden (Undo, Löschen)
  useEffect(() => {
    const ids = new Set(doc.objects.map((o) => o.id));
    const current_ = sel();
    if (current_.some((id) => !ids.has(id))) setSelection(current_.filter((id) => ids.has(id)));
  }, [doc, sel, setSelection]);

  // --- Aktionen -------------------------------------------------------------------
  const addObject = useCallback(
    async (preset: EditorPreset, at?: Point) => {
      if (preset === 'image') {
        imageTarget.current = { mode: 'new', at };
        imageInput.current?.click();
        return;
      }
      const res = await runEdit((d) => newObject(d, preset, at ? { at } : undefined));
      if (res && preset === 'icon' && res.selected[0]) setIconTarget(res.selected[0]);
    },
    [runEdit],
  );

  const insertImage = useCallback(
    async (file: File, target: ImageTarget) => {
      try {
        const data = await readFileAsB64(file);
        const up = await uploadImage(data, file.name);
        if (target.mode === 'replace') {
          await op('update', [target.id], { changes: { png: up.png } });
        } else {
          await runEdit((d) => newObject(d, 'image', target.at ? { png: up.png, at: target.at } : { png: up.png }));
        }
      } catch (err) {
        showError(err);
      }
    },
    [op, runEdit, showError],
  );

  const doUndo = useCallback(() => commitUndo(undo(activeUndo())), [activeUndo, commitUndo]);
  const doRedo = useCallback(() => commitUndo(redo(activeUndo())), [activeUndo, commitUndo]);
  const remove = useCallback(() => {
    if (sel().length) void op('remove', sel());
  }, [op, sel]);
  const duplicate = useCallback(() => {
    if (sel().length) void op('duplicate', sel());
  }, [op, sel]);
  const rotate = useCallback(
    (degrees: 90 | -90) => {
      if (sel().length) void op('rotate', sel(), { degrees });
    },
    [op, sel],
  );
  const flip = useCallback(() => {
    if (sel().length) void op('flip', sel());
  }, [op, sel]);
  const nudge = useCallback(
    (dx: number, dy: number) => {
      const ids = movableSelection();
      if (!ids.length) return;
      void op('move', ids, { dx, dy, snap: false }, { mergeKey: `nudge:${ids.join(',')}`, windowMs: NUDGE_MERGE_MS });
    },
    [movableSelection, op],
  );

  const addTab = useCallback(() => {
    const id = newTab();
    if (id) updateView(id, DEFAULT_VIEW);
  }, [newTab, updateView]);

  const openByName = useCallback(
    async (name: string) => {
      try {
        const existing = findByDocName(name);
        if (existing) activate(existing.id);
        else {
          const r = await loadDocument(name);
          openInTab(r.document, { docName: r.name, label: t('steps.opened', { name: r.name }) });
        }
        setOpenOpen(false);
      } catch (err) {
        showError(err);
      }
    },
    [activate, findByDocName, openInTab, showError, t],
  );

  /** Speichert den Tab `tabId` unter `name`; true bei Erfolg. */
  const saveAs = useCallback(
    async (name: string, tabId: string = getTabs().activeId): Promise<boolean> => {
      const tab = getTab(tabId);
      if (!tab) return false;
      const entry = tab.undo.entries[tab.undo.index] ?? tab.undo.entries[0]!;
      try {
        await saveDocument(name, entry.doc);
        markTabSaved(tabId, name, entry.id);
        void queryClient.invalidateQueries({ queryKey: qk.documents });
        notify({ intent: 'success', title: t('notify.saved', { name }) });
        return true;
      } catch (err) {
        showError(err);
        return false;
      }
    },
    [getTab, getTabs, markTabSaved, notify, queryClient, showError, t],
  );

  const save = useCallback(() => {
    const tab = getTab(getTabs().activeId);
    if (!tab) return;
    if (tab.docName) void saveAs(tab.docName, tab.id);
    else setSaveAsFor({ id: tab.id, closeAfter: false });
  }, [getTab, getTabs, saveAs]);

  const closeNow = useCallback(
    (id: string) => {
      void discardDraft(id);
      closeTab(id);
      dropView(id);
    },
    [closeTab, discardDraft, dropView],
  );

  const requestClose = useCallback(
    (id: string) => {
      const tab = getTab(id);
      if (!tab) return;
      if (isTabDirty(tab)) setClosing(id);
      else closeNow(id);
    },
    [closeNow, getTab],
  );

  const closeOthers = useCallback(
    (keep: string) => {
      activate(keep);
      for (const tab of getTabs().tabs) {
        if (tab.id !== keep && !isTabDirty(tab)) closeNow(tab.id);
      }
    },
    [activate, closeNow, getTabs],
  );

  const closingTab = closing ? getTab(closing) : undefined;
  const saveAndClose = useCallback(async () => {
    const tab = closing ? getTab(closing) : undefined;
    setClosing(null);
    if (!tab) return;
    if (tab.docName) {
      if (await saveAs(tab.docName, tab.id)) closeNow(tab.id);
    } else {
      setSaveAsFor({ id: tab.id, closeAfter: true });
    }
  }, [closeNow, closing, getTab, saveAs]);

  const doPrint = useCallback(() => {
    if (printBlockRef.current || !source) return;
    void print.run(source, printOptions);
  }, [print, printOptions, source]);

  const snapQuery = useCallback(
    (q: SnapQuery, signal: AbortSignal) =>
      snap(
        { document: current(activeUndo()), ids: q.ids, dx: q.dx, dy: q.dy, mode: q.mode, handle: q.handle, grid: grid ? dotsPerMm : undefined },
        signal,
      ),
    [activeUndo, dotsPerMm, grid],
  );

  const onMoveEnd = useCallback((ids: string[], dx: number, dy: number) => void op('move', ids, { dx, dy, snap: snapOn }), [op, snapOn]);

  const onResizeEnd = useCallback(
    async (id: string, handle: Handle, box: Box, dx: number, dy: number) => {
      let fx = dx;
      let fy = dy;
      if (snapOn) {
        try {
          const r = await snapQuery({ ids: [id], dx, dy, mode: 'resize', handle }, new AbortController().signal);
          fx = r.dx;
          fy = r.dy;
        } catch {
          // ohne Einrasten weiter
        }
      }
      const [x, y, w, h] = resizeBox(box, handle, fx, fy);
      void op('set_box', [id], { x, y, w, h });
    },
    [op, snapOn, snapQuery],
  );

  const selectAll = useCallback(() => {
    setSelection(current(activeUndo()).objects.filter((o) => o.visible !== false).map((o) => o.id));
  }, [activeUndo, setSelection]);

  const onCanvasKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    const delta = arrowDelta(e.key, e.shiftKey);
    if (delta) {
      e.preventDefault();
      nudge(delta[0], delta[1]);
      return;
    }
    if (e.key.length === 1 && !e.shiftKey) {
      const preset = presetForKey(e.key);
      if (preset) {
        e.preventDefault();
        void addObject(preset);
      }
    }
  };

  const restoreDrafts = useCallback(
    async (ids: string[]) => {
      setRecovery(null);
      const seeds: TabSeed[] = [];
      for (const id of ids) {
        try {
          await adoptDraft(id);
          seeds.push(seedFromDraft(await getDraft(id)));
        } catch (err) {
          const e = errorText(err);
          notify({ intent: 'error', title: t('recovery.failed'), body: e.message || e.title, hint: e.hint || undefined });
        }
      }
      if (seeds.length) restoreTabs(seeds, { activate: true });
    },
    [errorText, notify, restoreTabs, seedFromDraft, t],
  );

  const discardDrafts = useCallback(
    async (ids: string[]) => {
      setRecovery(null);
      for (const id of ids) {
        try {
          await deleteDraft(id);
        } catch (err) {
          showError(err);
        }
      }
    },
    [showError],
  );

  // --- Kürzel und Kommandos ------------------------------------------------------
  const sc = { enabled: !dialogOpen };
  useShortcut('Ctrl+Z', doUndo, sc);
  useShortcut('Ctrl+Y', doRedo, sc);
  useShortcut('Ctrl+Shift+Z', doRedo, sc);
  useShortcut('Delete', remove, sc);
  useShortcut('Ctrl+D', duplicate, sc);
  useShortcut('Ctrl+R', () => rotate(90), sc);
  useShortcut('Ctrl+Shift+R', () => rotate(-90), sc);
  useShortcut('Ctrl+M', flip, sc);
  useShortcut('Ctrl+A', selectAll, sc);
  useShortcut('Ctrl+S', save, { enabled: !dialogOpen, allowInInputs: true });
  useShortcut('Escape', () => setSelection([]), sc);
  const tabKeys = { enabled: !dialogOpen, allowInInputs: true };
  useShortcut('Ctrl+Alt+T', addTab, tabKeys);
  useShortcut('Ctrl+Alt+W', () => requestClose(getTabs().activeId), tabKeys);
  useShortcut('Ctrl+PageDown', nextTab, tabKeys);
  useShortcut('Ctrl+PageUp', prevTab, tabKeys);

  useRegisterCommands(
    [
      {
        id: 'druck.aktuell',
        title: t('commands.print'),
        group: t('commands.groupPrint'),
        shortcut: t('keys.print'),
        keywords: ['editor', 'drucken', 'print'],
        run: doPrint,
        enabled: () => printBlockRef.current === null,
      },
      {
        id: 'editor.duplizieren',
        title: t('commands.duplicate'),
        group: t('commands.groupEditor'),
        shortcut: t('keys.duplicate'),
        keywords: ['kopieren', 'kopie', 'duplicate', 'copy'],
        run: duplicate,
        enabled: () => sel().length > 0,
      },
      {
        id: 'editor.als-vorlage',
        title: t('commands.saveTemplate'),
        group: t('commands.groupEditor'),
        keywords: ['vorlage', 'template'],
        run: () => setTemplateOpen(true),
      },
      { id: 'editor.neu', title: t('commands.new'), group: t('commands.groupEditor'), keywords: ['leer', 'neu', 'new'], run: addTab },
      {
        id: 'editor.tab-neu',
        title: t('commands.newTab'),
        group: t('commands.groupEditor'),
        shortcut: t('keys.newTab'),
        keywords: ['tab'],
        run: addTab,
      },
      {
        id: 'editor.tab-schliessen',
        title: t('commands.closeTab'),
        group: t('commands.groupEditor'),
        shortcut: t('keys.closeTab'),
        keywords: ['tab'],
        run: () => requestClose(getTabs().activeId),
      },
      {
        id: 'editor.tab-weiter',
        title: t('commands.nextTab'),
        group: t('commands.groupEditor'),
        shortcut: t('keys.nextTab'),
        keywords: ['tab'],
        run: nextTab,
        enabled: () => getTabs().tabs.length > 1,
      },
      {
        id: 'editor.tab-zurueck',
        title: t('commands.prevTab'),
        group: t('commands.groupEditor'),
        shortcut: t('keys.prevTab'),
        keywords: ['tab'],
        run: prevTab,
        enabled: () => getTabs().tabs.length > 1,
      },
    ],
    [i18n.language],
  );

  // --- Panels -------------------------------------------------------------------
  // Panels gehören zum aktiven Tab: ihre Bearbeitungen sind an ihn gebunden und sie werden je Tab neu
  // aufgebaut (`key`), damit eine noch entprellte Eingabe beim Tabwechsel in ihrem Tab ankommt.
  const editTab = activeId;
  const tabSel = () => viewsRef.current[editTab]?.selection ?? [];
  const actions: PropertiesActions = {
    update: (ids, changes, field) => void op('update', ids, { changes }, { mergeKey: `update:${ids.join(',')}:${field}`, tabId: editTab }),
    setBox: (id, box, field) => void op('set_box', [id], box, { mergeKey: `update:${id}:${field}`, tabId: editTab }),
    align: (mode: AlignMode, reference) => void op('align', tabSel(), { mode, reference }, { tabId: editTab }),
    distribute: (axis) => void op('distribute', tabSel(), { axis }, { tabId: editTab }),
    rotate,
    flip,
    duplicate,
    remove,
    pickIcon: (id) => setIconTarget(id),
    replaceImage: (id) => {
      imageTarget.current = { mode: 'replace', id };
      imageInput.current?.click();
    },
  };

  const labelSettings = (
    <LabelSettings
      doc={doc}
      contentMm={render.data?.preview?.content_mm ?? null}
      onSetLength={(mode, lengthMm) =>
        void op('set_length', [], { mode, length_mm: mode === 'auto' ? null : lengthMm }, { mergeKey: 'label:length', tabId: editTab })
      }
      onMargin={(mm) =>
        void runEdit(async (d) => ({ document: { ...d, margin_mm: mm }, selected: tabSel(), step_label: t('steps.margin'), guides: [] }), {
          mergeKey: 'label:margin',
          tabId: editTab,
        })
      }
      onTransform={(change) => void op('label_transform', [], change, { tabId: editTab })}
    />
  );

  const panelBody = (
    <>
      <TabList selectedValue={panel} onTabSelect={(_e, d) => setPanel(d.value as PanelTab)} aria-label={t('panels.label')}>
        <Tab value="props">{t('panels.props')}</Tab>
        <Tab value="layers">{t('panels.layers')}</Tab>
        <Tab value="history">{t('panels.history')}</Tab>
      </TabList>
      {panel === 'props' ? (
        <PropertiesPanel key={editTab} doc={doc} selection={selection} overlay={overlay} fonts={fonts} dotsPerMm={dotsPerMm} actions={actions} empty={labelSettings} />
      ) : null}
      {panel === 'layers' ? (
        <LayersPanel
          key={editTab}
          doc={doc}
          selection={selection}
          onSelect={setSelection}
          onUpdate={(id, changes, field) => void op('update', [id], { changes }, { mergeKey: `update:${id}:${field}`, tabId: editTab })}
          onReorder={(o: ReorderOp) => void op('reorder', tabSel(), { op: o }, { tabId: editTab })}
        />
      ) : null}
      {panel === 'history' ? (
        <HistoryPanel labels={labels(undoState)} index={undoState.index} onJump={(i) => commitUndo(jump(activeUndo(), i))} />
      ) : null}
    </>
  );

  const issues = (render.data?.issues ?? []).filter((i) => i.object_id);
  const objectName = (id: string) => {
    const o = doc.objects.find((x) => x.id === id);
    return o ? objectTitle(o, kindName) : id;
  };
  const autosaveError = sync.error ? errorText(sync.error) : null;

  return (
    <div className={styles.root}>
      <PageHeader
        title={t('title')}
        subtitle={
          <span className={styles.docName}>
            {activeTab.title}
            {unsaved ? <span className={styles.dot} role="img" aria-label={t('header.unsaved')} title={t('header.unsaved')} /> : null}
          </span>
        }
        actions={
          !wide ? (
            <Button icon={<PanelRight20Regular />} onClick={() => setDrawerOpen(true)}>
              {t('header.panels')}
            </Button>
          ) : undefined
        }
      />

      <EditorTabs
        tabs={tabsState.tabs}
        activeId={activeId}
        onSelect={activate}
        onClose={requestClose}
        onCloseOthers={closeOthers}
        onNew={addTab}
      />

      <EditorToolbar
        onNew={addTab}
        onOpen={() => setOpenOpen(true)}
        onSave={save}
        onSaveAs={() => setSaveAsFor({ id: activeId, closeAfter: false })}
        onSaveTemplate={() => setTemplateOpen(true)}
        onUndo={doUndo}
        onRedo={doRedo}
        canUndo={canUndo(undoState)}
        canRedo={canRedo(undoState)}
        zoom={zoom}
        onZoom={setZoom}
        grid={grid}
        onGrid={setGrid}
        snap={snapOn}
        onSnap={setSnapOn}
        onPrint={doPrint}
        printDisabledReason={printBlock}
        printBusy={print.busy}
        printOptions={<PrintOptionsBar value={printOptions} onChange={setPrintOptions} />}
        onExport={(format) => {
          if (source) exportLabel(source, printOptions, format).catch(showError);
        }}
        onDownloadDoc={() => downloadJson(doc, docName ?? 'label')}
        compact={!wide}
      />

      {autosaveError ? (
        <MessageBar intent="warning" layout="multiline" politeness="polite">
          <MessageBarBody>
            <MessageBarTitle>{t('autosave.failed', { message: autosaveError.message || autosaveError.title })}</MessageBarTitle>
            {t('autosave.failedHint')}
          </MessageBarBody>
        </MessageBar>
      ) : null}

      {tiny ? (
        <MessageBar intent="info">
          <MessageBarBody>{t('header.narrow')}</MessageBarBody>
        </MessageBar>
      ) : null}

      <div className={mergeClasses(styles.body, !wide && styles.bodyNarrow, tiny && styles.bodyTiny)}>
        <Palette onPick={(p) => void addObject(p)} horizontal={tiny} />
        <div className={styles.stage} ref={setStageEl}>
          {!ready ? (
            <LoadingState variant="section" label={t('stage.loading')} />
          ) : (
            <>
              <EditorCanvas
                doc={doc}
                overlay={overlay}
                selection={selection}
                scale={scale}
                dotsPerMm={dotsPerMm}
                grid={grid}
                snap={snapOn}
                background={app?.tape.background ?? '#ffffff' /* Bandfarbe aus Daten, i18n-ignore */}
                placeholderSize={[widthDots, heightDots]}
                guides={guides}
                onSelect={setSelection}
                onMoveEnd={onMoveEnd}
                onResizeEnd={(id, handle, box, dx, dy) => void onResizeEnd(id, handle, box, dx, dy)}
                snapQuery={snapQuery}
                onKeyDown={onCanvasKey}
                onDropPreset={(preset, at) => void addObject(preset, at)}
                onDropFiles={(files, at) => {
                  for (const f of files) void insertImage(f, { mode: 'new', at });
                }}
              />
              {doc.objects.length === 0 ? (
                <EmptyState icon={<DocumentOnePage24Regular />} title={t('stage.emptyTitle')} body={t('stage.emptyBody')} />
              ) : null}
            </>
          )}
          {render.loading ? <Spinner className={styles.stageBusy} size="extra-tiny" aria-label={t('stage.updating')} /> : null}
        </div>
        {wide ? <aside className={styles.panels}>{panelBody}</aside> : null}
      </div>

      <section className={mergeClasses(styles.bottom, !wide && styles.bottomNarrow)} aria-label={t('bottom.label')}>
        <TapePreview render={render.data} loading={render.loading} title={docName ?? undefined} />
        <div className={styles.issues}>
          <h2 className={styles.issuesTitle}>{t('bottom.issues')}</h2>
          {issues.length === 0 ? <Caption1 className={styles.muted}>{t('bottom.none')}</Caption1> : null}
          {issues.map((issue, i) => (
            <Button
              key={`${issue.object_id}-${i}`}
              appearance="secondary"
              className={mergeClasses(styles.issue, issue.level === 'error' ? styles.issueError : styles.issueWarn)}
              onClick={() => {
                if (!issue.object_id) return;
                setSelection([issue.object_id]);
                setPanel('props');
                if (!wide) setDrawerOpen(true);
              }}
            >
              {t(issue.level === 'error' ? 'bottom.error' : 'bottom.warning', { message: issue.message, object: objectName(issue.object_id ?? '') })}
            </Button>
          ))}
        </div>
      </section>

      {!wide ? (
        <OverlayDrawer position="end" size="medium" open={drawerOpen} onOpenChange={(_e, d) => setDrawerOpen(d.open)}>
          <DrawerHeader>
            <DrawerHeaderTitle
              action={<Button appearance="subtle" aria-label={t('common:actions.close')} icon={<Dismiss20Regular />} onClick={() => setDrawerOpen(false)} />}
            >
              {t('panels.drawer')}
            </DrawerHeaderTitle>
          </DrawerHeader>
          <DrawerBody>{panelBody}</DrawerBody>
        </OverlayDrawer>
      ) : null}

      <input
        ref={imageInput}
        className={styles.hiddenInput}
        type="file"
        accept="image/png,image/jpeg,image/bmp,image/gif,image/webp,image/svg+xml"
        aria-label={t('imageFile')}
        tabIndex={-1}
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = '';
          const target = imageTarget.current;
          imageTarget.current = { mode: 'new' };
          if (file) void insertImage(file, target);
        }}
      />
      {openOpen ? (
        <OpenDialog
          open
          onClose={() => setOpenOpen(false)}
          onOpen={(name) => void openByName(name)}
          onUpload={(uploaded, name) => {
            openInTab(uploaded, { title: name, label: t('steps.uploaded', { name }) });
            setOpenOpen(false);
          }}
        />
      ) : null}
      {saveAsFor ? (
        <SaveAsDialog
          open
          initial={getTab(saveAsFor.id)?.docName ?? ''}
          onClose={() => setSaveAsFor(null)}
          onSave={async (name) => {
            const target = saveAsFor;
            const ok = await saveAs(name, target.id);
            if (ok) {
              setSaveAsFor(null);
              if (target.closeAfter) closeNow(target.id);
            }
            return ok;
          }}
        />
      ) : null}
      {templateOpen ? <SaveAsTemplateDialog open document={doc} initialName={docName ?? ''} onClose={() => setTemplateOpen(false)} /> : null}
      {iconTarget !== null ? (
        <IconPickerDialog
          open
          onClose={() => setIconTarget(null)}
          onPick={(ref) => {
            const id = iconTarget;
            setIconTarget(null);
            void op('update', [id], { changes: { icon: ref } });
          }}
        />
      ) : null}
      {recovery ? (
        <RecoveryDialog drafts={recovery} onRestore={(ids) => void restoreDrafts(ids)} onDiscard={(ids) => void discardDrafts(ids)} onLater={() => setRecovery(null)} />
      ) : null}
      {closingTab ? (
        <CloseTabDialog
          title={closingTab.title}
          onSave={() => void saveAndClose()}
          onDiscard={() => {
            setClosing(null);
            closeNow(closingTab.id);
          }}
          onCancel={() => setClosing(null)}
        />
      ) : null}
    </div>
  );
}
