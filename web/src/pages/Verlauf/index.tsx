/**
 * Seite „Verlauf": alle Drucke mit Miniatur, Suche, Nachdruck, Export, „PNG kopieren",
 * „Als Vorlage speichern" und „Im Editor öffnen". Sensible Einträge zeigen kein Bild; fehlende
 * sensible Felder werden vor dem Nachdruck neu abgefragt (nur für diese eine Anfrage). Die Liste
 * nutzt das gemeinsame Muster `DataList` (ab 900 px Tabelle, darunter Karten) mit genau einem
 * sichtbaren Hauptknopf je Zeile („Erneut drucken“) und allen weiteren Aktionen im „Mehr“-Menü
 * (`RowActions`). Systemtitel (Kalibrierung, Testlabel, …) erscheinen in der Oberflächensprache.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Badge,
  Body1,
  Button,
  Caption1,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  OverlayDrawer,
  DrawerBody,
  DrawerHeader,
  DrawerHeaderTitle,
  Switch,
  Tooltip,
  makeStyles,
  mergeClasses,
  tokens,
  type BadgeProps,
} from '@fluentui/react-components';
import {
  Archive20Regular,
  ArrowClockwise20Regular,
  ArrowExport20Regular,
  CheckmarkCircle20Regular,
  Copy20Regular,
  DismissCircle20Regular,
  Edit20Regular,
  LockClosed24Regular,
  Save20Regular,
  Search20Regular,
  Warning20Regular,
} from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { apiGet, apiPost, authUrl } from '../../api/client';
import { qk } from '../../api/core';
import { exportLabel } from '../../api/labels';
import type { HistoryEntryJson, LabelDocumentJson } from '../../api/types';
import { DataList, LIST_NARROW_QUERY, type ListColumn } from '../../components/DataList';
import { EmptyState } from '../../components/EmptyState';
import { ListToolbar, useToolbarSearchStyles } from '../../components/ListToolbar';
import { PageHeader } from '../../components/PageHeader';
import { RowActions } from '../../components/RowActions';
import { useNotify } from '../../components/NotifyProvider';
import { useMediaQuery } from '../../components/useMediaQuery';
import { usePrint } from '../../components/usePrint';
import { copyPngToClipboard } from '../../platform';
import { useRegisterCommands } from '../../commands/CommandProvider';
import { formatMm } from '../../i18n/format';
import { displayTitle } from '../../i18n/systemTitle';
import { absoluteTime, relativeTime } from './time';

const SEARCH_DEBOUNCE_MS = 250;
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

const useStyles = makeStyles({
  /** Vorschau in lesbarer Größe: das Band ist lang und schmal, darum breit statt hoch. */
  thumbWrap: {
    flexShrink: 0,
    width: '168px',
    height: '44px',
    boxSizing: 'border-box',
    padding: tokens.spacingVerticalXXS,
    borderRadius: tokens.borderRadiusMedium,
    display: 'grid',
    placeItems: 'center',
    backgroundColor: tokens.colorNeutralBackground3,
    overflow: 'hidden',
    color: tokens.colorNeutralForeground3,
  },
  thumbWrapCard: { width: '112px', height: '40px' },
  thumb: { maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' },
  titleBtn: {
    padding: 0,
    minWidth: 0,
    minHeight: 0,
    height: 'auto',
    fontWeight: tokens.fontWeightSemibold,
    textAlign: 'left',
    justifyContent: 'flex-start',
    // höchstens zwei Zeilen, danach „…“ (voller Titel im Detailbereich)
    display: '-webkit-box',
    WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical',
    overflow: 'hidden',
    overflowWrap: 'anywhere',
  },
  muted: { color: tokens.colorNeutralForeground3 },
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
  const toolbarStyles = useToolbarSearchStyles();
  const narrow = useMediaQuery(LIST_NARROW_QUERY);

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

  const titleOf = (entry: HistoryEntryJson): string => displayTitle(entry.title, entry.kind, entry.values);

  const renderThumb = (entry: HistoryEntryJson): JSX.Element => {
    const showImage = entry.has_head && !entry.sensitive;
    return (
      <div className={narrow ? mergeClasses(styles.thumbWrap, styles.thumbWrapCard) : styles.thumbWrap}>
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
    const ariaLabel = t('actions.for', { action: visible, title: titleOf(entry) });
    return entry.reprintable ? (
      <Button icon={<ArrowClockwise20Regular />} aria-label={ariaLabel} onClick={() => onReprintClick(entry)}>
        {visible}
      </Button>
    ) : (
      <Tooltip content={t('actions.reprintDisabledHint')} relationship="description" withArrow>
        <Button icon={<ArrowClockwise20Regular />} aria-label={ariaLabel} disabledFocusable>
          {visible}
        </Button>
      </Tooltip>
    );
  };

  const renderActions = (entry: HistoryEntryJson): JSX.Element => (
    <RowActions
      title={titleOf(entry)}
      primary={renderReprintButton(entry)}
      actions={[
        { key: 'editor', label: t('actions.editInEditor'), icon: <Edit20Regular />, onClick: () => onOpenInEditor(entry) },
        {
          key: 'template',
          label: t('actions.saveAsTemplate'),
          icon: <Save20Regular />,
          onClick: () => setTemplateDialog({ entry, name: '', description: '', category: '', busy: false }),
        },
        {
          key: 'copy',
          label: t('actions.copyPng'),
          icon: <Copy20Regular />,
          disabled: !entry.has_head,
          onClick: () => void onCopyPng(entry),
        },
        {
          key: 'export',
          label: t('actions.export'),
          icon: <ArrowExport20Regular />,
          disabled: !entry.has_head,
          items: [
            { key: 'export-png', label: 'PNG', onClick: () => void onExport(entry, 'png') },
            { key: 'export-pdf', label: 'PDF', onClick: () => void onExport(entry, 'pdf') },
            { key: 'export-pbm', label: 'PBM', onClick: () => void onExport(entry, 'pbm') },
          ],
        },
        { key: 'archive', label: t('actions.archive'), icon: <Archive20Regular />, onClick: () => void onArchive(entry) },
      ]}
    />
  );

  const columns: ListColumn<HistoryEntryJson>[] = [
    { id: 'thumb', header: t('columns.thumb'), kind: 'media', cell: (entry) => renderThumb(entry) },
    {
      id: 'title',
      header: t('columns.title'),
      kind: 'title',
      cell: (entry) => (
        <Button appearance="transparent" className={styles.titleBtn} onClick={() => setDetailId(entry.id)}>
          {titleOf(entry)}
        </Button>
      ),
    },
    {
      id: 'time',
      header: t('columns.time'),
      cell: (entry) => (
        <Tooltip content={absoluteTime(entry.created)} relationship="description">
          <span>{relativeTime(entry.created)}</span>
        </Tooltip>
      ),
    },
    { id: 'source', header: t('columns.source'), cell: (entry) => <Badge appearance="outline">{sourceLabel(entry.source)}</Badge> },
    { id: 'length', header: t('columns.length'), kind: 'number', cell: (entry) => lengthText(t, entry) },
    { id: 'status', header: t('columns.status'), kind: 'status', cell: (entry) => renderStatusBadge(entry) },
    { id: 'actions', header: t('columns.actions'), kind: 'actions', cell: (entry) => renderActions(entry) },
  ];

  return (
    <>
      <PageHeader title={t('title')} />
      <ListToolbar>
        <Input
          ref={searchRef}
          className={toolbarStyles.search}
          aria-label={t('search.label')}
          contentBefore={<Search20Regular />}
          placeholder={t('search.placeholder')}
          value={inputValue}
          onChange={(_e, d) => onSearchChange(d.value)}
        />
      </ListToolbar>

      <DataList
        items={entries}
        columns={columns}
        getKey={(entry) => entry.id}
        label={t('grid.label')}
        loading={historyQuery.isLoading}
        error={historyQuery.error}
        onRetry={() => void historyQuery.refetch()}
        empty={
          <EmptyState
            title={query.trim() ? t('empty.titleQuery', { query: query.trim() }) : t('empty.titleNone')}
            body={query.trim() ? t('empty.bodyQuery') : t('empty.bodyNone')}
          />
        }
      />

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
                {titleOf(detailEntry)}
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
