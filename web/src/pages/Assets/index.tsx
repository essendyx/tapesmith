/**
 * Seite „Assets": Register mit zentralem Nummernkreis und Kurz-Links. Liste nach dem gemeinsamen
 * Muster (`DataList` mit Auswahl): je Zeile ein sichtbarer Hauptknopf („Label drucken“), Bearbeiten,
 * Kurz-Link, Vault-Notiz und Verwerfen im „Mehr“-Menü; Suche, Statusfilter und „Als Serie drucken“
 * in der Werkzeugleiste über der Liste.
 */
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Badge,
  Button,
  Caption1,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Dropdown,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Option,
  Spinner,
  makeStyles,
  tokens,
  type BadgeProps,
} from '@fluentui/react-components';
import {
  Add20Regular,
  ArrowDownload20Regular,
  Book20Regular,
  Copy20Regular,
  Delete20Regular,
  Edit20Regular,
  Print20Regular,
  Search20Regular,
  TagQuestionMark20Regular,
} from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../api/client';
import { DataList, type ListColumn } from '../../components/DataList';
import { EmptyState } from '../../components/EmptyState';
import { ListToolbar, useToolbarSearchStyles } from '../../components/ListToolbar';
import { PageHeader } from '../../components/PageHeader';
import { moduleTexts } from '../../modules';
import { RowActions } from '../../components/RowActions';
import { useConfirm } from '../../components/ConfirmProvider';
import { useNotify } from '../../components/NotifyProvider';
import { usePrint } from '../../components/usePrint';
import { AssetDialog, type AssetDialogMode } from './AssetDialog';
import { createAssetVaultNote, createAssetsTable, exportAssetsCsv, fetchAssetLabel, fetchAssets, voidAsset } from './api';
import type { AssetJson, AssetRangeJson } from './types';
import { useDialogFocusReturn } from '../../components/useDialogFocusReturn';

const STATUS_COLOR: Record<string, NonNullable<BadgeProps['color']>> = {
  aktiv: 'success',
  verworfen: 'danger',
  ausgemustert: 'informative',
};
const SEARCH_DEBOUNCE_MS = 250;

const useStyles = makeStyles({
  status: { minWidth: '160px' },
  mono: { fontFamily: tokens.fontFamilyMonospace, fontSize: tokens.fontSizeBase200 },
  next: { color: tokens.colorNeutralForeground3 },
  warning: { marginBottom: tokens.spacingVerticalM },
});

export default function AssetsPage(): JSX.Element {
  const styles = useStyles();
  const toolbarStyles = useToolbarSearchStyles();
  const { t } = useTranslation('assets');
  const navigate = useNavigate();
  const notify = useNotify();
  const confirm = useConfirm();
  const print = usePrint();
  const searchRef = useRef<HTMLInputElement>(null);

  const STATUS_LABEL: Record<string, string> = {
    aktiv: t('status.aktiv'),
    verworfen: t('status.verworfen'),
    ausgemustert: t('status.ausgemustert'),
  };

  const [assets, setAssets] = useState<AssetJson[]>([]);
  const [range, setRange] = useState<AssetRangeJson | null>(null);
  const [shortlinkOk, setShortlinkOk] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<unknown>(null);

  const [statusFilter, setStatusFilter] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [query, setQuery] = useState('');
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [dialogMode, setDialogMode] = useState<AssetDialogMode | null>(null);
  const [dialogAsset, setDialogAsset] = useState<AssetJson | null>(null);
  const [voidTarget, setVoidTarget] = useState<AssetJson | null>(null);
  const [voidReason, setVoidReason] = useState('');
  const [voidBusy, setVoidBusy] = useState(false);
  useDialogFocusReturn(voidTarget !== null);

  const load = (): void => {
    fetchAssets(statusFilter, query)
      .then((res) => {
        setAssets(res.assets);
        setRange(res.range);
        setShortlinkOk(res.shortlink);
        setLoaded(true);
        setLoadError(null);
      })
      .catch((err: unknown) => {
        setLoadError(err);
      });
  };

  useEffect(load, [statusFilter, query]);

  const onSearchChange = (value: string): void => {
    setSearchInput(value);
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => setQuery(value), SEARCH_DEBOUNCE_MS);
  };

  useEffect(
    () => () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    },
    [],
  );

  const toggleSelected = (id: string, on: boolean): void => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const onCreateVaultNote = async (asset: AssetJson): Promise<void> => {
    try {
      const res = await createAssetVaultNote(asset.id);
      notify({ intent: 'success', title: t('notify.vaultCreated', { path: res.path }) });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        notify({ intent: 'info', title: t('notify.vaultExists') });
      } else {
        notify({
          intent: 'error',
          title: err instanceof ApiError ? err.message : t('notify.vaultFailed'),
          hint: err instanceof ApiError ? err.hint || undefined : undefined,
        });
      }
    }
  };

  const onPrintLabel = async (asset: AssetJson): Promise<void> => {
    try {
      const label = await fetchAssetLabel(asset.id);
      for (const w of label.warnings) notify({ intent: 'warning', title: w });
      await print.run({ kind: 'template', template: label.template, values: label.values });
    } catch (err) {
      notify({
        intent: 'error',
        title: err instanceof ApiError ? err.message : t('notify.labelFailed'),
        hint: err instanceof ApiError ? err.hint || undefined : undefined,
      });
    }
  };

  const onCopyShortlink = async (asset: AssetJson): Promise<void> => {
    try {
      const label = await fetchAssetLabel(asset.id);
      const link = label.values.link;
      if (!link) {
        notify({ intent: 'info', title: t('notify.shortlinkMissing') });
        return;
      }
      await navigator.clipboard.writeText(link);
      notify({ intent: 'success', title: t('notify.shortlinkCopied') });
    } catch (err) {
      notify({
        intent: 'error',
        title: err instanceof ApiError ? err.message : t('notify.shortlinkFailed'),
        hint: err instanceof ApiError ? err.hint || undefined : undefined,
      });
    }
  };

  const onVoidConfirm = async (): Promise<void> => {
    if (!voidTarget) return;
    const reason = voidReason.trim();
    if (!reason) return;
    const ok = await confirm({
      title: t('void.confirmTitle', { id: voidTarget.id }),
      message: t('void.confirmMessage'),
      reasons: [reason],
      confirmText: t('void.confirmButton'),
      danger: true,
    });
    if (!ok) return;
    setVoidBusy(true);
    try {
      await voidAsset(voidTarget.id, reason);
      notify({ intent: 'success', title: t('notify.voidSuccess', { id: voidTarget.id }) });
      setVoidTarget(null);
      setVoidReason('');
      load();
    } catch (err) {
      notify({ intent: 'error', title: err instanceof ApiError ? err.message : t('notify.voidFailed') });
    } finally {
      setVoidBusy(false);
    }
  };

  const onPrintSeries = async (): Promise<void> => {
    if (selected.size === 0) return;
    try {
      const res = await createAssetsTable([...selected]);
      navigate(`/vorlagen?vorlage=asset-kurz&import=${res.pending_id}`);
    } catch (err) {
      notify({ intent: 'error', title: err instanceof ApiError ? err.message : t('notify.seriesFailed') });
    }
  };

  const onExport = async (): Promise<void> => {
    try {
      await exportAssetsCsv();
    } catch (err) {
      notify({ intent: 'error', title: err instanceof ApiError ? err.message : t('notify.exportFailed') });
    }
  };


  const columns: ListColumn<AssetJson>[] = [
    { id: 'id', header: t('table.columns.id'), cell: (asset) => <span className={styles.mono}>{asset.id}</span> },
    { id: 'bezeichnung', header: t('table.columns.bezeichnung'), kind: 'title', cell: (asset) => asset.bezeichnung },
    { id: 'kategorie', header: t('table.columns.kategorie'), cell: (asset) => asset.kategorie },
    { id: 'standort', header: t('table.columns.standort'), cell: (asset) => asset.standort },
    { id: 'sn', header: t('table.columns.sn'), cell: (asset) => <span className={styles.mono}>{asset.seriennummer}</span> },
    { id: 'host', header: t('table.columns.host'), cell: (asset) => asset.host },
    {
      id: 'status',
      header: t('table.columns.status'),
      kind: 'status',
      cell: (asset) => (
        <Badge appearance="tint" color={STATUS_COLOR[asset.status] ?? 'informative'}>
          {STATUS_LABEL[asset.status] ?? asset.status}
        </Badge>
      ),
    },
    {
      id: 'actions',
      header: t('table.columns.actions'),
      kind: 'actions',
      cell: (asset) => (
        <RowActions
          title={asset.id}
          primary={
            <Button
              icon={<Print20Regular />}
              aria-label={t('rowActions.for', { action: t('rowActions.printLabel'), title: asset.id })}
              onClick={() => void onPrintLabel(asset)}
            >
              {t('rowActions.printLabel')}
            </Button>
          }
          actions={[
            {
              key: 'edit',
              label: t('rowActions.edit'),
              icon: <Edit20Regular />,
              onClick: () => {
                setDialogAsset(asset);
                setDialogMode('edit');
              },
            },
            { key: 'shortlink', label: t('rowActions.copyShortlink'), icon: <Copy20Regular />, onClick: () => void onCopyShortlink(asset) },
            { key: 'vault', label: t('rowActions.createVaultNote'), icon: <Book20Regular />, onClick: () => void onCreateVaultNote(asset) },
            {
              key: 'void',
              label: t('rowActions.void'),
              icon: <Delete20Regular />,
              danger: true,
              disabled: asset.status === 'verworfen',
              onClick: () => {
                setVoidTarget(asset);
                setVoidReason('');
              },
            },
          ]}
        />
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title={moduleTexts('assets').name}
        subtitle={moduleTexts('assets').description}
        actions={
          <>
            <Button appearance="primary" icon={<Add20Regular />} onClick={() => setDialogMode('create')}>
              {t('actions.new')}
            </Button>
            <Button icon={<TagQuestionMark20Regular />} onClick={() => setDialogMode('import')}>
              {t('actions.import')}
            </Button>
            <Button icon={<ArrowDownload20Regular />} onClick={() => void onExport()}>
              {t('actions.export')}
            </Button>
          </>
        }
      />

      {!shortlinkOk ? (
        <MessageBar intent="warning" className={styles.warning}>
          <MessageBarBody>
            <MessageBarTitle>{t('shortlinkWarning.title')}</MessageBarTitle>
            {t('shortlinkWarning.body')}
          </MessageBarBody>
        </MessageBar>
      ) : null}

      <ListToolbar
        actions={
          <>
            {range ? <Caption1 className={styles.next}>{t('nextNumber', { next: range.next })}</Caption1> : null}
            <Button icon={<Print20Regular />} disabled={selected.size === 0} onClick={() => void onPrintSeries()}>
              {t('actions.printSeries', { count: selected.size })}
            </Button>
          </>
        }
      >
        <Input
          ref={searchRef}
          className={toolbarStyles.search}
          contentBefore={<Search20Regular />}
          aria-label={t('toolbar.searchAria')}
          placeholder={t('toolbar.searchPlaceholder')}
          value={searchInput}
          onChange={(_e, d) => onSearchChange(d.value)}
        />
        <Field label={t('toolbar.statusLabel')} orientation="horizontal">
          <Dropdown
            className={styles.status}
            aria-label={t('toolbar.statusFilterAria')}
            value={statusFilter ? STATUS_LABEL[statusFilter] ?? statusFilter : t('status.all')}
            selectedOptions={[statusFilter]}
            onOptionSelect={(_e, d) => setStatusFilter(d.optionValue ?? '')}
          >
            <Option value="">{t('status.all')}</Option>
            <Option value="aktiv">{t('status.aktiv')}</Option>
            <Option value="verworfen">{t('status.verworfen')}</Option>
            <Option value="ausgemustert">{t('status.ausgemustert')}</Option>
          </Dropdown>
        </Field>
      </ListToolbar>

      <DataList
        items={assets}
        columns={columns}
        getKey={(asset) => asset.id}
        label={t('table.ariaLabel')}
        loading={!loaded && !loadError}
        error={loadError}
        errorTitle={t('loadErrorFallback')}
        onRetry={load}
        empty={<EmptyState title={t('empty.title')} body={t('empty.body')} />}
        selection={{
          isSelected: (asset) => selected.has(asset.id),
          onChange: (asset, on) => toggleSelected(asset.id, on),
          onChangeAll: (on) => setSelected(on ? new Set(assets.map((a) => a.id)) : new Set()),
          itemLabel: (asset) => t('table.selectRowAria', { id: asset.id }),
          allLabel: t('table.selectAllAria'),
        }}
      />

      <AssetDialog
        mode={dialogMode}
        asset={dialogAsset}
        onClose={() => { setDialogMode(null); setDialogAsset(null); }}
        onCreated={() => load()}
        onImported={() => load()}
        onUpdated={() => load()}
      />

      <Dialog open={voidTarget !== null} onOpenChange={(_e, d) => !d.open && setVoidTarget(null)}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{t('void.dialogTitle')}</DialogTitle>
            <DialogContent>
              <Field label={t('void.reasonLabel')} required>
                <Input value={voidReason} onChange={(_e, d) => setVoidReason(d.value)} autoFocus />
              </Field>
            </DialogContent>
            <DialogActions>
              <Button
                appearance="primary"
                disabled={voidBusy || !voidReason.trim()}
                aria-busy={voidBusy}
                onClick={() => void onVoidConfirm()}
              >
                {voidBusy ? <Spinner size="tiny" /> : t('void.continue')}
              </Button>
              <Button appearance="secondary" onClick={() => setVoidTarget(null)} disabled={voidBusy}>
                {t('common:actions.cancel')}
              </Button>
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}
