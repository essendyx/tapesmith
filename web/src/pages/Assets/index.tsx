/** Seite „Assets": Register mit zentralem Nummernkreis und Kurz-Links. */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Badge,
  Button,
  Checkbox,
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
import { Add16Regular, ArrowDownload16Regular, BookRegular, Copy16Regular, Print16Regular, TagQuestionMark16Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../api/client';
import { EmptyState } from '../../components/EmptyState';
import { ErrorMessage } from '../../components/ErrorMessage';
import { LoadingState } from '../../components/LoadingState';
import { PageHeader } from '../../components/PageHeader';
import { moduleTexts } from '../../modules';
import { Section } from '../../components/Section';
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
  toolbar: { display: 'flex', columnGap: tokens.spacingHorizontalM, rowGap: tokens.spacingVerticalS, flexWrap: 'wrap', marginBottom: tokens.spacingVerticalL, alignItems: 'flex-end' },
  search: { minWidth: '220px', flexGrow: 1, maxWidth: '360px' },
  actions: { display: 'flex', columnGap: tokens.spacingHorizontalS, flexWrap: 'wrap' },
  tableWrap: { overflowX: 'auto', width: '100%' },
  table: { width: '100%', borderCollapse: 'collapse' },
  th: { textAlign: 'left', padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`, borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`, color: tokens.colorNeutralForeground3, fontWeight: tokens.fontWeightRegular, fontSize: tokens.fontSizeBase200, whiteSpace: 'nowrap' },
  td: { padding: `${tokens.spacingVerticalS} ${tokens.spacingHorizontalM}`, borderBottom: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`, verticalAlign: 'middle' },
  rowActions: { display: 'flex', columnGap: tokens.spacingHorizontalXS, flexWrap: 'wrap' },
  info: { display: 'flex', columnGap: tokens.spacingHorizontalM, rowGap: tokens.spacingVerticalXS, flexWrap: 'wrap', alignItems: 'center', marginBottom: tokens.spacingVerticalM, color: tokens.colorNeutralForeground2 },
  warning: { marginBottom: tokens.spacingVerticalM },
});

export default function AssetsPage(): JSX.Element {
  const styles = useStyles();
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

  const allSelected = assets.length > 0 && assets.every((a) => selected.has(a.id));

  const rows = useMemo(() => assets, [assets]);

  return (
    <>
      <PageHeader
        title={moduleTexts('assets').name}
        subtitle={moduleTexts('assets').description}
        actions={
          <>
            <Button appearance="primary" icon={<Add16Regular />} onClick={() => setDialogMode('create')}>
              {t('actions.new')}
            </Button>
            <Button icon={<TagQuestionMark16Regular />} onClick={() => setDialogMode('import')}>
              {t('actions.import')}
            </Button>
            <Button icon={<ArrowDownload16Regular />} onClick={() => void onExport()}>
              {t('actions.export')}
            </Button>
          </>
        }
      />

      <div className={styles.info}>{range ? <span>{t('nextNumber', { next: range.next })}</span> : null}</div>

      {!shortlinkOk ? (
        <MessageBar intent="warning" className={styles.warning}>
          <MessageBarBody>
            <MessageBarTitle>{t('shortlinkWarning.title')}</MessageBarTitle>
            {t('shortlinkWarning.body')}
          </MessageBarBody>
        </MessageBar>
      ) : null}

      {loadError ? (
        <div className={styles.warning}>
          <ErrorMessage error={loadError} title={t('loadErrorFallback')} onRetry={load} />
        </div>
      ) : null}

      <Section
        actions={
          <Button
            appearance="secondary"
            icon={<Print16Regular />}
            disabled={selected.size === 0}
            onClick={() => void onPrintSeries()}
          >
            {t('actions.printSeries', { count: selected.size })}
          </Button>
        }
      >
        <div className={styles.toolbar}>
          <Input
            ref={searchRef}
            className={styles.search}
            aria-label={t('toolbar.searchAria')}
            placeholder={t('toolbar.searchPlaceholder')}
            value={searchInput}
            onChange={(_e, d) => onSearchChange(d.value)}
          />
          <Field label={t('toolbar.statusLabel')}>
            <Dropdown
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
        </div>

        {!loaded ? (
          <LoadingState variant="list" label={t('loading')} />
        ) : rows.length === 0 ? (
          <EmptyState title={t('empty.title')} body={t('empty.body')} />
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table} aria-label={t('table.ariaLabel')}>
              <thead>
                <tr>
                  <th className={styles.th}>
                    <Checkbox
                      checked={allSelected}
                      aria-label={t('table.selectAllAria')}
                      onChange={(_e, d) => setSelected(d.checked ? new Set(rows.map((a) => a.id)) : new Set())}
                    />
                  </th>
                  <th className={styles.th}>{t('table.columns.id')}</th>
                  <th className={styles.th}>{t('table.columns.bezeichnung')}</th>
                  <th className={styles.th}>{t('table.columns.kategorie')}</th>
                  <th className={styles.th}>{t('table.columns.standort')}</th>
                  <th className={styles.th}>{t('table.columns.sn')}</th>
                  <th className={styles.th}>{t('table.columns.host')}</th>
                  <th className={styles.th}>{t('table.columns.status')}</th>
                  <th className={styles.th}>{t('table.columns.ziel')}</th>
                  <th className={styles.th}>{t('table.columns.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((asset) => (
                  <tr key={asset.id}>
                    <td className={styles.td}>
                      <Checkbox
                        checked={selected.has(asset.id)}
                        aria-label={t('table.selectRowAria', { id: asset.id })}
                        onChange={(_e, d) => toggleSelected(asset.id, Boolean(d.checked))}
                      />
                    </td>
                    <td className={styles.td}>{asset.id}</td>
                    <td className={styles.td}>{asset.bezeichnung}</td>
                    <td className={styles.td}>{asset.kategorie}</td>
                    <td className={styles.td}>{asset.standort}</td>
                    <td className={styles.td}>{asset.seriennummer}</td>
                    <td className={styles.td}>{asset.host}</td>
                    <td className={styles.td}>
                      <Badge appearance="tint" color={STATUS_COLOR[asset.status] ?? 'informative'}>
                        {STATUS_LABEL[asset.status] ?? asset.status}
                      </Badge>
                    </td>
                    <td className={styles.td}>{asset.ziel ?? ''}</td>
                    <td className={styles.td}>
                      <div className={styles.rowActions}>
                        <Button size="small" onClick={() => { setDialogAsset(asset); setDialogMode('edit'); }}>
                          {t('rowActions.edit')}
                        </Button>
                        <Button size="small" icon={<Print16Regular />} onClick={() => void onPrintLabel(asset)}>
                          {t('rowActions.printLabel')}
                        </Button>
                        <Button size="small" icon={<Copy16Regular />} onClick={() => void onCopyShortlink(asset)}>
                          {t('rowActions.copyShortlink')}
                        </Button>
                        <Button size="small" icon={<BookRegular />} onClick={() => void onCreateVaultNote(asset)}>
                          {t('rowActions.createVaultNote')}
                        </Button>
                        <Button
                          size="small"
                          disabled={asset.status === 'verworfen'}
                          onClick={() => { setVoidTarget(asset); setVoidReason(''); }}
                        >
                          {t('rowActions.void')}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

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
