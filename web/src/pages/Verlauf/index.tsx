/**
 * Seite „Verlauf": alle Drucke mit Miniatur, Suche, Nachdruck, Export, „PNG kopieren",
 * „Als Vorlage speichern" und „Im Editor öffnen". Sensible Einträge zeigen kein Bild; fehlende
 * sensible Felder werden vor dem Nachdruck neu abgefragt (nur für diese eine Anfrage). Ab 480 px
 * Breite steht die Liste als Fluent DataGrid, darunter als Karten.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Badge,
  Body1,
  Button,
  Caption1,
  DataGrid,
  DataGridBody,
  DataGridCell,
  DataGridHeader,
  DataGridHeaderCell,
  DataGridRow,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  Menu,
  MenuItem,
  MenuList,
  MenuPopover,
  MenuTrigger,
  OverlayDrawer,
  DrawerBody,
  DrawerHeader,
  DrawerHeaderTitle,
  Switch,
  Tooltip,
  createTableColumn,
  makeStyles,
  mergeClasses,
  tokens,
  type BadgeProps,
  type TableColumnDefinition,
} from '@fluentui/react-components';
import {
  ArrowClockwise20Regular,
  CheckmarkCircle20Regular,
  DismissCircle20Regular,
  LockClosed24Regular,
  MoreHorizontal20Regular,
  Search20Regular,
  Warning20Regular,
} from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { apiGet, apiPost, authUrl } from '../../api/client';
import { qk } from '../../api/core';
import { exportLabel } from '../../api/labels';
import type { HistoryEntryJson, LabelDocumentJson } from '../../api/types';
import { EmptyState } from '../../components/EmptyState';
import { PageHeader } from '../../components/PageHeader';
import { useNotify } from '../../components/NotifyProvider';
import { usePrint } from '../../components/usePrint';
import { copyPngToClipboard } from '../../platform';
import { useRegisterCommands } from '../../commands/CommandProvider';
import { formatMm } from '../../i18n/format';
import { absoluteTime, relativeTime } from './time';

const SEARCH_DEBOUNCE_MS = 250;
/** Unterhalb dieser Breite zeigt die Liste Karten statt des DataGrid (responsiv bis 360 px;
 * die Grenze liegt bei 1023 px, damit bei 200 % Zoom keine Aktionen abgeschnitten werden). */
const NARROW_QUERY = '(max-width: 1023px)';

type Translate = (key: string, options?: Record<string, unknown>) => string;

// Schlüssel sind Server-Enumwerte, keine Anzeige-Texte. // i18n-ignore (Server-Wert)
const STATUS_COLOR: Record<string, NonNullable<BadgeProps['color']>> = {
  ok: 'success',
  wartet: 'warning',
  abgebrochen: 'warning',
  unvollständig: 'danger', // i18n-ignore (Server-Wert)
  fehler: 'danger', // i18n-ignore (Server-Wert)
};
const STATUS_ICON: Record<string, JSX.Element> = {
  ok: <CheckmarkCircle20Regular />,
  wartet: <Warning20Regular />,
  abgebrochen: <Warning20Regular />, // i18n-ignore (Server-Wert, siehe nächste Zeile)
  unvollständig: <DismissCircle20Regular />, // i18n-ignore (Server-Wert)
  fehler: <DismissCircle20Regular />, // i18n-ignore (Server-Wert)
};
/** Quelle bleibt als technisches Kürzel unübersetzt (identisch in beiden Sprachen). */
const SOURCE_TEXT: Record<string, string> = { gui: 'GUI', cli: 'CLI', hotkey: 'Hotkey', api: 'API' };
const HIDDEN_VALUE_KEYS = new Set(['qr_spec']);

function sourceLabel(source: string): string {
  return SOURCE_TEXT[source] ?? source;
}

/** Server-Statuswert (deutscher Enum-Wert) übersetzt anzeigen; unbekannte Werte bleiben, wie sie sind. */
function statusLabel(t: Translate, status: string): string {
  return t(`status.${status}`, { defaultValue: status });
}

function lengthText(t: Translate, entry: HistoryEntryJson): string {
  let text = formatMm(entry.length_mm, 0);
  if (entry.copies > 1) text += t('length.copies', { count: entry.copies });
  if (entry.chained) text += t('length.chain');
  return text;
}

function secretLabel(t: Translate, fieldId: string): string {
  if (fieldId === 'password') return t('secret.wifiPassword');
  return t('secret.generic', { id: fieldId });
}

/** Wie in shell/AppShell.tsx: sicherer matchMedia-Zugriff (kann in Vorschauen/älteren Browsern fehlen). */
function useNarrow(query: string): boolean {
  const get = (): boolean => {
    try {
      return typeof window.matchMedia === 'function' && window.matchMedia(query).matches;
    } catch {
      return false;
    }
  };
  const [matches, setMatches] = useState(get);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const mql = window.matchMedia(query);
    const onChange = (): void => setMatches(mql.matches);
    onChange();
    mql.addEventListener?.('change', onChange);
    return () => mql.removeEventListener?.('change', onChange);
  }, [query]);
  return matches;
}

const useStyles = makeStyles({
  toolbar: { display: 'flex', columnGap: tokens.spacingHorizontalM, marginBottom: tokens.spacingVerticalL, flexWrap: 'wrap' },
  search: { flexGrow: 1, minWidth: '220px', maxWidth: '420px' },
  list: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  card: {
    display: 'flex',
    columnGap: tokens.spacingHorizontalL,
    padding: tokens.spacingVerticalM,
    borderRadius: tokens.borderRadiusXLarge,
    backgroundColor: tokens.colorNeutralBackground1,
    boxShadow: tokens.shadow4,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    '@media (max-width: 480px)': { flexDirection: 'column' },
  },
  thumbWrap: {
    flexShrink: 0,
    width: '96px',
    height: '64px',
    borderRadius: tokens.borderRadiusLarge,
    display: 'grid',
    placeItems: 'center',
    backgroundColor: tokens.colorNeutralBackground3,
    overflow: 'hidden',
    color: tokens.colorNeutralForeground3,
  },
  thumbWrapSmall: { width: '56px', height: '40px' },
  thumb: { maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' },
  body: { flexGrow: 1, minWidth: 0, display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXS },
  head: { display: 'flex', alignItems: 'baseline', columnGap: tokens.spacingHorizontalS, flexWrap: 'wrap' },
  titleBtn: {
    padding: 0,
    minWidth: 0,
    fontWeight: tokens.fontWeightSemibold,
    fontSize: tokens.fontSizeBase400,
    textAlign: 'left',
  },
  meta: {
    display: 'flex',
    columnGap: tokens.spacingHorizontalS,
    alignItems: 'center',
    flexWrap: 'wrap',
    color: tokens.colorNeutralForeground3,
  },
  actions: { display: 'flex', columnGap: tokens.spacingHorizontalXS, flexWrap: 'wrap' },
  grid: { marginBottom: tokens.spacingVerticalL },
  drawerRow: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXXS, marginBottom: tokens.spacingVerticalM },
  drawerThumb: {
    maxWidth: '100%',
    borderRadius: tokens.borderRadiusLarge,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    marginBottom: tokens.spacingVerticalM,
  },
});

interface HistoryResponse {
  entries: HistoryEntryJson[];
}

interface SaveTemplateState {
  entry: HistoryEntryJson;
  name: string;
  description: string;
  category: string;
  busy: boolean;
}

interface ReprintDialogState {
  entry: HistoryEntryJson;
  /** Rohtext des Kopien-Felds (erlaubt kurzzeitig leer/ungueltig während der Eingabe). */
  copiesText: string;
  chain: boolean;
  values: Record<string, string>;
  busy: boolean;
}

/** Kopien aus dem Rohtext des Dialogfelds; ungueltig/leer faellt auf 1 zurueck. */
function parseCopies(text: string): number {
  const n = Number.parseInt(text, 10);
  return Number.isFinite(n) && n > 0 ? n : 1;
}

export default function VerlaufPage(): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('verlauf');
  const navigate = useNavigate();
  const notify = useNotify();
  const queryClient = useQueryClient();
  const print = usePrint();
  const searchRef = useRef<HTMLInputElement>(null);
  const narrow = useNarrow(NARROW_QUERY);

  const [inputValue, setInputValue] = useState('');
  const [query, setQuery] = useState('');
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [detailId, setDetailId] = useState<number | null>(null);
  const [reprintDialog, setReprintDialog] = useState<ReprintDialogState | null>(null);
  const [templateDialog, setTemplateDialog] = useState<SaveTemplateState | null>(null);

  const historyQuery = useQuery({
    queryKey: [...qk.history, query],
    queryFn: ({ signal }) => apiGet<HistoryResponse>(`/api/v1/history?query=${encodeURIComponent(query)}&limit=50`, signal),
  });
  const entries = useMemo(() => historyQuery.data?.entries ?? [], [historyQuery.data]);

  useEffect(
    () => () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    },
    [],
  );

  const onSearchChange = (value: string): void => {
    setInputValue(value);
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => setQuery(value), SEARCH_DEBOUNCE_MS);
  };

  useRegisterCommands(
    [
      {
        id: 'verlauf.suchen',
        title: t('commands.search'),
        group: 'navigation',
        keywords: ['verlauf', 'suche', 'history'],
        run: () => searchRef.current?.focus(),
      },
    ],
    [t],
  );

  const doReprint = (entry: HistoryEntryJson, copies: number, chain: boolean, values: Record<string, string>): void => {
    const hasValues = Object.keys(values).length > 0;
    const source = hasValues ? ({ kind: 'history', id: entry.id, values } as const) : ({ kind: 'history', id: entry.id } as const);
    void print.run(source, { copies, chain });
  };

  const onReprintClick = (entry: HistoryEntryJson): void => {
    setReprintDialog({ entry, copiesText: String(entry.copies || 1), chain: entry.chained, values: {}, busy: false });
  };

  const onConfirmReprint = (): void => {
    if (!reprintDialog) return;
    doReprint(reprintDialog.entry, parseCopies(reprintDialog.copiesText), reprintDialog.chain, reprintDialog.values);
    setReprintDialog(null);
  };

  const onOpenInEditor = (entry: HistoryEntryJson): void => {
    navigate(`/editor?verlauf=${entry.id}`);
  };

  const onCopyPng = async (entry: HistoryEntryJson): Promise<void> => {
    try {
      const res = await fetch(authUrl(`/api/v1/history/${entry.id}/export`, { format: 'png' }));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const buf = await res.arrayBuffer();
      let binary = '';
      for (const byte of new Uint8Array(buf)) binary += String.fromCharCode(byte);
      const ok = await copyPngToClipboard(btoa(binary));
      notify(ok ? { intent: 'success', title: t('notify.pngCopied') } : { intent: 'error', title: t('notify.copyFailed') });
    } catch (err) {
      notify({ intent: 'error', title: t('notify.copyError'), body: err instanceof Error ? err.message : String(err) });
    }
  };

  const onExport = async (entry: HistoryEntryJson, format: 'png' | 'pdf' | 'pbm'): Promise<void> => {
    try {
      await exportLabel({ kind: 'history', id: entry.id }, {}, format);
    } catch (err) {
      notify({ intent: 'error', title: t('notify.exportFailed'), body: err instanceof Error ? err.message : String(err) });
    }
  };

  const onArchive = async (entry: HistoryEntryJson): Promise<void> => {
    try {
      const res = await apiPost<{ notes: string[] }>(`/api/v1/history/${entry.id}/archive`, {});
      notify({ intent: 'success', title: t('notify.archived'), body: res.notes.join('\n') || undefined });
    } catch (err) {
      notify({ intent: 'error', title: t('notify.archiveFailed'), body: err instanceof Error ? err.message : String(err) });
    }
  };

  const onSaveTemplate = async (): Promise<void> => {
    if (!templateDialog) return;
    setTemplateDialog({ ...templateDialog, busy: true });
    try {
      const from = await apiPost<{ document: LabelDocumentJson }>(`/api/v1/documents/from-history/${templateDialog.entry.id}`, {});
      await apiPost('/api/v1/templates', {
        name: templateDialog.name,
        description: templateDialog.description,
        category: templateDialog.category,
        tags: [],
        document: from.document,
        overwrite: false,
      });
      void queryClient.invalidateQueries({ queryKey: qk.templates });
      void queryClient.invalidateQueries({ queryKey: qk.gallery });
      notify({ intent: 'success', title: t('notify.templateSaved', { name: templateDialog.name }) });
      setTemplateDialog(null);
    } catch (err) {
      notify({ intent: 'error', title: t('notify.templateSaveFailed'), body: err instanceof Error ? err.message : String(err) });
      setTemplateDialog((prev) => (prev ? { ...prev, busy: false } : prev));
    }
  };

  const detailEntry = useMemo(() => entries.find((e) => e.id === detailId) ?? null, [entries, detailId]);

  const renderThumb = (entry: HistoryEntryJson, small = false): JSX.Element => {
    const showImage = entry.has_head && !entry.sensitive;
    return (
      <div className={small ? mergeClasses(styles.thumbWrap, styles.thumbWrapSmall) : styles.thumbWrap}>
        {entry.sensitive ? (
          <LockClosed24Regular aria-label={t('sensitiveNoImage')} />
        ) : showImage ? (
          <img className={styles.thumb} alt={t('thumbAlt')} src={authUrl(`/api/v1/history/${entry.id}/thumb.png`)} />
        ) : (
          <Caption1>{t('noImage')}</Caption1>
        )}
      </div>
    );
  };

  const renderStatusBadge = (entry: HistoryEntryJson): JSX.Element => (
    <Badge color={STATUS_COLOR[entry.status] ?? 'informative'} appearance="tint" icon={STATUS_ICON[entry.status]}>
      {statusLabel(t, entry.status)}
    </Badge>
  );

  const renderReprintButton = (entry: HistoryEntryJson): JSX.Element => {
    const visible = entry.copies > 1 ? t('actions.reprintAmount', { count: entry.copies }) : t('actions.reprint');
    const ariaLabel = t('actions.for', { action: visible, title: entry.title });
    return entry.reprintable ? (
      <Button appearance="primary" icon={<ArrowClockwise20Regular />} aria-label={ariaLabel} onClick={() => onReprintClick(entry)}>
        {visible}
      </Button>
    ) : (
      <Tooltip content={t('actions.reprintDisabledHint')} relationship="description" withArrow>
        <Button appearance="primary" icon={<ArrowClockwise20Regular />} aria-label={ariaLabel} disabled>
          {visible}
        </Button>
      </Tooltip>
    );
  };

  const renderActions = (entry: HistoryEntryJson): JSX.Element => (
    <div className={styles.actions}>
      {renderReprintButton(entry)}
      <Button
        appearance="secondary"
        aria-label={t('actions.for', { action: t('actions.editInEditor'), title: entry.title })}
        onClick={() => onOpenInEditor(entry)}
      >
        {t('actions.editInEditor')}
      </Button>
      <Button
        appearance="secondary"
        aria-label={t('actions.for', { action: t('actions.saveAsTemplate'), title: entry.title })}
        onClick={() => setTemplateDialog({ entry, name: '', description: '', category: '', busy: false })}
      >
        {t('actions.saveAsTemplate')}
      </Button>
      <Button
        appearance="secondary"
        disabled={!entry.has_head}
        aria-label={t('actions.for', { action: t('actions.copyPng'), title: entry.title })}
        onClick={() => void onCopyPng(entry)}
      >
        {t('actions.copyPng')}
      </Button>
      <Menu>
        <MenuTrigger disableButtonEnhancement>
          <Button
            appearance="secondary"
            disabled={!entry.has_head}
            icon={<MoreHorizontal20Regular />}
            aria-label={t('actions.for', { action: t('actions.export'), title: entry.title })}
          >
            {t('actions.export')}
          </Button>
        </MenuTrigger>
        <MenuPopover>
          <MenuList>
            <MenuItem onClick={() => void onExport(entry, 'png')}>PNG</MenuItem>
            <MenuItem onClick={() => void onExport(entry, 'pdf')}>PDF</MenuItem>
            <MenuItem onClick={() => void onExport(entry, 'pbm')}>PBM</MenuItem>
          </MenuList>
        </MenuPopover>
      </Menu>
      <Button
        appearance="secondary"
        aria-label={t('actions.for', { action: t('actions.archive'), title: entry.title })}
        onClick={() => void onArchive(entry)}
      >
        {t('actions.archive')}
      </Button>
    </div>
  );

  const columns: TableColumnDefinition<HistoryEntryJson>[] = useMemo(
    () => [
      createTableColumn<HistoryEntryJson>({
        columnId: 'thumb',
        renderHeaderCell: () => t('columns.thumb'),
        renderCell: (entry) => renderThumb(entry, true),
      }),
      createTableColumn<HistoryEntryJson>({
        columnId: 'title',
        renderHeaderCell: () => t('columns.title'),
        renderCell: (entry) => (
          <Button appearance="transparent" className={styles.titleBtn} onClick={() => setDetailId(entry.id)}>
            {entry.title}
          </Button>
        ),
      }),
      createTableColumn<HistoryEntryJson>({
        columnId: 'time',
        renderHeaderCell: () => t('columns.time'),
        renderCell: (entry) => (
          <Tooltip content={absoluteTime(entry.created)} relationship="label">
            <Caption1>{relativeTime(entry.created)}</Caption1>
          </Tooltip>
        ),
      }),
      createTableColumn<HistoryEntryJson>({
        columnId: 'source',
        renderHeaderCell: () => t('columns.source'),
        renderCell: (entry) => <Badge appearance="outline">{sourceLabel(entry.source)}</Badge>,
      }),
      createTableColumn<HistoryEntryJson>({
        columnId: 'length',
        renderHeaderCell: () => t('columns.length'),
        renderCell: (entry) => lengthText(t, entry),
      }),
      createTableColumn<HistoryEntryJson>({
        columnId: 'status',
        renderHeaderCell: () => t('columns.status'),
        renderCell: (entry) => renderStatusBadge(entry),
      }),
      createTableColumn<HistoryEntryJson>({
        columnId: 'actions',
        renderHeaderCell: () => t('columns.actions'),
        renderCell: (entry) => renderActions(entry),
      }),
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [styles, t],
  );

  return (
    <>
      <PageHeader title={t('title')} />
      <div className={styles.toolbar}>
        <Input
          ref={searchRef}
          className={styles.search}
          aria-label={t('search.label')}
          contentBefore={<Search20Regular />}
          placeholder={t('search.placeholder')}
          value={inputValue}
          onChange={(_e, d) => onSearchChange(d.value)}
        />
      </div>

      {entries.length === 0 ? (
        <EmptyState
          title={query.trim() ? t('empty.titleQuery', { query: query.trim() }) : t('empty.titleNone')}
          body={query.trim() ? t('empty.bodyQuery') : t('empty.bodyNone')}
        />
      ) : narrow ? (
        <div className={styles.list}>
          {entries.map((entry) => (
            <article key={entry.id} className={styles.card}>
              {renderThumb(entry)}
              <div className={styles.body}>
                <div className={styles.head}>
                  <Button appearance="transparent" className={styles.titleBtn} onClick={() => setDetailId(entry.id)}>
                    {entry.title}
                  </Button>
                  {renderStatusBadge(entry)}
                </div>
                <div className={styles.meta}>
                  <Tooltip content={absoluteTime(entry.created)} relationship="label">
                    <Caption1>{relativeTime(entry.created)}</Caption1>
                  </Tooltip>
                  <Badge appearance="outline">{sourceLabel(entry.source)}</Badge>
                  <Body1>{lengthText(t, entry)}</Body1>
                </div>
                {renderActions(entry)}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <DataGrid
          className={styles.grid}
          items={entries}
          columns={columns}
          getRowId={(entry) => String(entry.id)}
          aria-label={t('grid.label')}
        >
          <DataGridHeader>
            <DataGridRow>{({ renderHeaderCell }) => <DataGridHeaderCell>{renderHeaderCell()}</DataGridHeaderCell>}</DataGridRow>
          </DataGridHeader>
          <DataGridBody<HistoryEntryJson>>
            {({ item, rowId }) => (
              <DataGridRow<HistoryEntryJson> key={rowId}>
                {({ renderCell }) => <DataGridCell>{renderCell(item)}</DataGridCell>}
              </DataGridRow>
            )}
          </DataGridBody>
        </DataGrid>
      )}

      <OverlayDrawer open={detailEntry !== null} position="end" onOpenChange={(_e, d) => !d.open && setDetailId(null)}>
        {detailEntry ? (
          <>
            <DrawerHeader>
              <DrawerHeaderTitle
                action={
                  <Button appearance="subtle" onClick={() => setDetailId(null)}>
                    {t('drawer.close')}
                  </Button>
                }
              >
                {detailEntry.title}
              </DrawerHeaderTitle>
            </DrawerHeader>
            <DrawerBody>
              {detailEntry.has_head && !detailEntry.sensitive ? (
                <img
                  className={styles.drawerThumb}
                  alt={t('drawer.previewAlt')}
                  src={authUrl(`/api/v1/history/${detailEntry.id}/thumb.png`)}
                />
              ) : null}
              <div className={styles.drawerRow}>
                <Caption1>{t('drawer.time')}</Caption1>
                <Body1>{absoluteTime(detailEntry.created)}</Body1>
              </div>
              <div className={styles.drawerRow}>
                <Caption1>{t('drawer.sourceLength')}</Caption1>
                <Body1>
                  {sourceLabel(detailEntry.source)} · {lengthText(t, detailEntry)}
                </Body1>
              </div>
              {Object.entries(detailEntry.values)
                .filter(([k]) => !HIDDEN_VALUE_KEYS.has(k))
                .map(([k, v]) => (
                  <div key={k} className={styles.drawerRow}>
                    <Caption1>{k}</Caption1>
                    <Body1>{v}</Body1>
                  </div>
                ))}
              {detailEntry.missing_secrets.map((k) => (
                <div key={k} className={styles.drawerRow}>
                  <Caption1>{k}</Caption1>
                  <Body1>{t('drawer.missingSecret')}</Body1>
                </div>
              ))}
              {detailEntry.error ? (
                <div className={styles.drawerRow}>
                  <Caption1>{t('drawer.error')}</Caption1>
                  <Body1>{detailEntry.error}</Body1>
                </div>
              ) : null}
            </DrawerBody>
          </>
        ) : null}
      </OverlayDrawer>

      <Dialog open={reprintDialog !== null} onOpenChange={(_e, d) => !d.open && setReprintDialog(null)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{t('reprintDialog.title')}</DialogTitle>
            <DialogContent>
              <Field label={t('reprintDialog.copies')}>
                <Input
                  type="number"
                  min={1}
                  value={reprintDialog?.copiesText ?? '1'}
                  onChange={(_e, d) => setReprintDialog((prev) => (prev ? { ...prev, copiesText: d.value } : prev))}
                />
              </Field>
              <Switch
                label={t('reprintDialog.chain')}
                checked={reprintDialog?.chain ?? false}
                onChange={(_e, d) => setReprintDialog((prev) => (prev ? { ...prev, chain: d.checked } : prev))}
              />
              {reprintDialog?.entry.missing_secrets.map((fieldId) => (
                <Field key={fieldId} label={secretLabel(t, fieldId)}>
                  <Input
                    type="password"
                    value={reprintDialog.values[fieldId] ?? ''}
                    onChange={(_e, d) =>
                      setReprintDialog((prev) => (prev ? { ...prev, values: { ...prev.values, [fieldId]: d.value } } : prev))
                    }
                  />
                </Field>
              ))}
            </DialogContent>
            <DialogActions>
              <Button appearance="primary" onClick={onConfirmReprint}>
                {t('common:actions.print')}
              </Button>
              <Button appearance="secondary" onClick={() => setReprintDialog(null)}>
                {t('common:actions.cancel')}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>

      <Dialog open={templateDialog !== null} onOpenChange={(_e, d) => !d.open && setTemplateDialog(null)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{t('templateDialog.title')}</DialogTitle>
            <DialogContent>
              <Field label={t('templateDialog.name')}>
                <Input
                  value={templateDialog?.name ?? ''}
                  onChange={(_e, d) => setTemplateDialog((prev) => (prev ? { ...prev, name: d.value } : prev))}
                />
              </Field>
              <Field label={t('templateDialog.description')}>
                <Input
                  value={templateDialog?.description ?? ''}
                  onChange={(_e, d) => setTemplateDialog((prev) => (prev ? { ...prev, description: d.value } : prev))}
                />
              </Field>
              <Field label={t('templateDialog.category')}>
                <Input
                  value={templateDialog?.category ?? ''}
                  onChange={(_e, d) => setTemplateDialog((prev) => (prev ? { ...prev, category: d.value } : prev))}
                />
              </Field>
            </DialogContent>
            <DialogActions>
              <Button
                appearance="primary"
                disabled={!templateDialog?.name.trim() || templateDialog.busy}
                onClick={() => void onSaveTemplate()}
              >
                {t('common:actions.save')}
              </Button>
              <Button appearance="secondary" onClick={() => setTemplateDialog(null)}>
                {t('common:actions.cancel')}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}
