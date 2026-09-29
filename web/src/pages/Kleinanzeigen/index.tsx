/** Seite „Kleinanzeigen": Artikel-Tracking mit Etikett und Reservierung. */
import { useEffect, useState } from 'react';
import {
  Badge,
  Button,
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogSurface,
  DialogTitle,
  Field,
  Input,
  Tab,
  TabList,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Add20Regular } from '@fluentui/react-icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { printLabel, useLabelRender } from '../../api/labels';
import { DEFAULT_PRINT_OPTIONS, type LabelSource, type PrintOptions } from '../../api/types';
import { EmptyState } from '../../components/EmptyState';
import { ErrorMessage, useErrorText } from '../../components/ErrorMessage';
import { LoadingState } from '../../components/LoadingState';
import { useNotify } from '../../components/NotifyProvider';
import { PageHeader } from '../../components/PageHeader';
import { moduleTexts } from '../../modules';
import { Section } from '../../components/Section';
import { PrintOptionsBar } from '../../components/PrintOptionsBar';
import { TapePreview } from '../../components/TapePreview';
import { usePrintFlow } from '../../components/usePrint';
import { WarningList } from '../../components/WarningList';
import { useLayoutStyles } from '../../theme/layout';
import { ArtikelDialog } from './ArtikelDialog';
import { fetchArtikel, fetchArtikelLabel, setArtikelStatus } from './api';
import type { ArtikelJson, KaStatus } from './types';
import { useDialogFocusReturn } from '../../components/useDialogFocusReturn';

type StatusFilter = 'alle' | KaStatus;

function todayPlusDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

const useStyles = makeStyles({
  cards: { listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS },
  card: {
    display: 'flex',
    flexDirection: 'column',
    rowGap: tokens.spacingVerticalXS,
    padding: tokens.spacingHorizontalM,
    borderRadius: tokens.borderRadiusMedium,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: tokens.colorNeutralBackground2,
    minWidth: 0,
  },
  cardHead: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', columnGap: tokens.spacingHorizontalS, flexWrap: 'wrap' },
  cardTitle: { fontWeight: tokens.fontWeightSemibold, overflowWrap: 'anywhere', minWidth: 0 },
  cardMeta: { color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200, overflowWrap: 'anywhere' },
  actions: { display: 'flex', columnGap: tokens.spacingHorizontalS, rowGap: tokens.spacingVerticalXXS, flexWrap: 'wrap' },
  dialogContent: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM, minWidth: '260px' },
});

// ---------- Reservieren ----------

function ReserveDialog(props: {
  open: boolean;
  artikel: ArtikelJson | null;
  onClose: () => void;
  onDone: () => void;
}): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('kleinanzeigen');
  const { t: tc } = useTranslation('common');
  const notify = useNotify();
  useDialogFocusReturn(props.open);
  const [name, setName] = useState('');
  const [bis, setBis] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (props.open) {
      setName('');
      setBis(todayPlusDays(3));
      setError(null);
    }
  }, [props.open]);

  async function submit(): Promise<void> {
    if (!props.artikel || !name.trim() || !bis) return;
    setSaving(true);
    setError(null);
    try {
      await setArtikelStatus(props.artikel.id, { status: 'reserviert', name: name.trim(), datum: bis });
      notify({ intent: 'success', title: t('notify.reserved', { id: props.artikel.id }) });
      props.onDone();
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={props.open} onOpenChange={(_e, d) => !d.open && props.onClose()}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{t('dialogs.reserve.title')}</DialogTitle>
          <DialogContent className={styles.dialogContent}>
            {error ? <ErrorMessage error={error} /> : null}
            <Field label={t('dialogs.reserve.name')} required>
              <Input value={name} onChange={(_e, d) => setName(d.value)} />
            </Field>
            <Field label={t('dialogs.reserve.until')} required>
              <Input type="date" value={bis} onChange={(_e, d) => setBis(d.value)} />
            </Field>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!name.trim() || !bis || saving} onClick={() => void submit()}>
              {t('dialogs.reserve.submit')}
            </Button>
            <Button appearance="secondary" onClick={props.onClose}>
              {tc('actions.cancel')}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ---------- Verkauft ----------

function SellDialog(props: {
  open: boolean;
  artikel: ArtikelJson | null;
  onClose: () => void;
  onDone: () => void;
}): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('kleinanzeigen');
  const { t: tc } = useTranslation('common');
  const notify = useNotify();
  useDialogFocusReturn(props.open);
  const [name, setName] = useState('');
  const [am, setAm] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (props.open) {
      setName('');
      setAm(todayPlusDays(0));
      setError(null);
    }
  }, [props.open]);

  async function submit(): Promise<void> {
    if (!props.artikel || !name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await setArtikelStatus(props.artikel.id, { status: 'verkauft', name: name.trim(), datum: am || undefined });
      notify({ intent: 'success', title: t('notify.sold', { id: props.artikel.id }) });
      props.onDone();
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={props.open} onOpenChange={(_e, d) => !d.open && props.onClose()}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{t('dialogs.sell.title')}</DialogTitle>
          <DialogContent className={styles.dialogContent}>
            {error ? <ErrorMessage error={error} /> : null}
            <Field label={t('dialogs.sell.buyer')} required>
              <Input value={name} onChange={(_e, d) => setName(d.value)} />
            </Field>
            <Field label={t('dialogs.sell.date')}>
              <Input type="date" value={am} onChange={(_e, d) => setAm(d.value)} />
            </Field>
          </DialogContent>
          <DialogActions>
            <Button appearance="primary" disabled={!name.trim() || saving} onClick={() => void submit()}>
              {t('dialogs.sell.submit')}
            </Button>
            <Button appearance="secondary" onClick={props.onClose}>
              {tc('actions.cancel')}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ---------- Etikett-Vorschau ----------

function LabelPreviewDialog(props: { open: boolean; artikel: ArtikelJson | null; onClose: () => void }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('kleinanzeigen');
  const { t: tc } = useTranslation('common');
  const { open, artikel } = props;
  useDialogFocusReturn(open);
  const [options, setOptions] = useState<PrintOptions>(DEFAULT_PRINT_OPTIONS);
  const [source, setSource] = useState<LabelSource | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [loadError, setLoadError] = useState<unknown>(null);
  const printFlow = usePrintFlow<LabelSource>((req, opts) => printLabel(req, opts));

  useEffect(() => {
    if (!open || !artikel) {
      setSource(null);
      setWarnings([]);
      return;
    }
    setLoadError(null);
    let active = true;
    fetchArtikelLabel(artikel.id, 'artikel').then(
      (data) => {
        if (!active) return;
        setSource({ kind: 'template', template: data.template, values: data.values });
        setWarnings(data.warnings);
      },
      (err: unknown) => {
        if (active) setLoadError(err);
      },
    );
    return () => {
      active = false;
    };
  }, [open, artikel]);

  const render = useLabelRender(source);

  return (
    <Dialog open={open} onOpenChange={(_e, d) => !d.open && props.onClose()}>
      <DialogSurface>
        <DialogBody>
          <DialogTitle>{t('dialogs.label.titleWithId', { id: artikel?.id })}</DialogTitle>
          <DialogContent className={styles.dialogContent}>
            {loadError ? <ErrorMessage error={loadError} /> : null}
            <WarningList warnings={warnings} />
            <TapePreview render={render.data} loading={render.loading} compact />
            <PrintOptionsBar value={options} onChange={setOptions} />
          </DialogContent>
          <DialogActions>
            <Button
              appearance="primary"
              disabled={!source || printFlow.busy}
              onClick={() => {
                if (source) void printFlow.run(source, options);
              }}
            >
              {tc('actions.print')}
            </Button>
            <Button appearance="secondary" onClick={props.onClose}>
              {tc('actions.close')}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
}

// ---------- Hauptseite ----------

export default function KleinanzeigenPage(): JSX.Element {
  const styles = useStyles();
  const layout = useLayoutStyles();
  const { t } = useTranslation('kleinanzeigen');
  const notify = useNotify();
  const errorText = useErrorText();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<StatusFilter>('alle');
  const [dialogMode, setDialogMode] = useState<'neu' | 'bearbeiten' | null>(null);
  const [dialogArtikel, setDialogArtikel] = useState<ArtikelJson | null>(null);
  const [reserveTarget, setReserveTarget] = useState<ArtikelJson | null>(null);
  const [sellTarget, setSellTarget] = useState<ArtikelJson | null>(null);
  const [labelTarget, setLabelTarget] = useState<ArtikelJson | null>(null);

  const listQuery = useQuery({
    queryKey: ['kleinanzeigen', tab],
    queryFn: ({ signal }) => fetchArtikel(tab === 'alle' ? {} : { status: tab }, signal),
  });

  function reload(): void {
    void queryClient.invalidateQueries({ queryKey: ['kleinanzeigen'] });
  }

  async function quickPrintReserved(art: ArtikelJson): Promise<void> {
    try {
      const label = await fetchArtikelLabel(art.id, 'reserviert');
      const outcome = await printLabel({ kind: 'template', template: label.template, values: label.values }, DEFAULT_PRINT_OPTIONS);
      if (outcome.status === 'ok' || outcome.status === 'wartet') {
        notify({ intent: 'success', title: t('notify.printed', { id: art.id }) });
      } else {
        notify({ intent: 'warning', title: t('notify.notPrinted', { id: art.id }), body: outcome.reasons.join('\n') || undefined });
      }
    } catch (err) {
      const e = errorText(err);
      notify({ intent: 'error', title: e.title, body: e.message || undefined, hint: e.hint || undefined });
    }
  }

  async function releaseArtikel(art: ArtikelJson): Promise<void> {
    try {
      await setArtikelStatus(art.id, { status: 'verfügbar' }); // i18n-ignore (Server-Wert)
      reload();
    } catch (err) {
      const e = errorText(err);
      notify({ intent: 'error', title: e.title, body: e.message || undefined, hint: e.hint || undefined });
    }
  }

  const items = listQuery.data?.items ?? [];

  const statusLabel = (status: KaStatus): string =>
    status === 'reserviert' // i18n-ignore (Server-Wert)
      ? t('status.reserved')
      : status === 'verkauft' // i18n-ignore (Server-Wert)
        ? t('status.sold')
        : t('status.available');

  return (
    <div className={layout.stack}>
      <PageHeader
        title={moduleTexts('kleinanzeigen').name}
        subtitle={moduleTexts('kleinanzeigen').description}
        actions={
          <Button appearance="primary" icon={<Add20Regular />} onClick={() => setDialogMode('neu')}>
            {t('actions.newArticle')}
          </Button>
        }
      />

      <Section flush>
        <TabList selectedValue={tab} onTabSelect={(_e, data) => setTab(data.value as StatusFilter)}>
          <Tab value="alle">{t('tabs.all')}</Tab>
          <Tab value="verfügbar">{t('tabs.available')}</Tab> {/* i18n-ignore (Server-Wert) */}
          <Tab value="reserviert">{t('tabs.reserved')}</Tab>
          <Tab value="verkauft">{t('tabs.sold')}</Tab>
        </TabList>
      </Section>

      {listQuery.isLoading ? <LoadingState variant="list" rows={3} /> : null}
      {listQuery.error ? <ErrorMessage error={listQuery.error} onRetry={() => void listQuery.refetch()} /> : null}
      {!listQuery.isLoading && !listQuery.error && items.length === 0 ? (
        <EmptyState title={t('empty.title')} body={t('empty.body')} />
      ) : null}

      {items.length ? (
        <ul className={styles.cards} aria-label={t('list.ariaLabel')}>
          {items.map((art) => (
            <li key={art.id} className={styles.card}>
              <div className={styles.cardHead}>
                <span className={styles.cardTitle}>
                  {art.id} · {art.titel}
                </span>
                <Badge
                  appearance="tint"
                  color={art.status === 'reserviert' ? 'warning' : art.status === 'verkauft' ? 'success' : 'informative'} // i18n-ignore (Server-Wert)
                >
                  {statusLabel(art.status)}
                </Badge>
              </div>
              <span className={styles.cardMeta}>
                {art.preis ? `${art.preis}` : ''}
                {art.preis && art.ort ? ' · ' : ''}
                {art.ort}
              </span>
              {art.status !== 'verfügbar' ? ( // i18n-ignore (Server-Wert)
                <span className={styles.cardMeta}>
                  {art.status === 'reserviert' // i18n-ignore (Server-Wert)
                    ? t('list.reservedUntil', { name: art.name, date: art.datum })
                    : t('list.soldOn', { name: art.name, date: art.datum })}
                </span>
              ) : null}
              {art.anzeige ? (
                <a href={art.anzeige} target="_blank" rel="noreferrer">
                  {t('list.openAd')}
                </a>
              ) : null}
              <div className={styles.actions}>
                <Button size="small" onClick={() => setLabelTarget(art)}>
                  {t('actions.label')}
                </Button>
                {art.status !== 'verkauft' ? ( // i18n-ignore (Server-Wert)
                  <Button size="small" onClick={() => setReserveTarget(art)}>
                    {t('actions.reserve')}
                  </Button>
                ) : null}
                {art.status === 'reserviert' ? ( // i18n-ignore (Server-Wert)
                  <Button size="small" onClick={() => void quickPrintReserved(art)}>
                    {t('actions.printReservedLabel')}
                  </Button>
                ) : null}
                {art.status === 'reserviert' ? ( // i18n-ignore (Server-Wert)
                  <Button size="small" onClick={() => void releaseArtikel(art)}>
                    {t('actions.release')}
                  </Button>
                ) : null}
                {art.status !== 'verkauft' ? ( // i18n-ignore (Server-Wert)
                  <Button size="small" onClick={() => setSellTarget(art)}>
                    {t('actions.markSold')}
                  </Button>
                ) : null}
                <Button
                  size="small"
                  onClick={() => {
                    setDialogArtikel(art);
                    setDialogMode('bearbeiten');
                  }}
                >
                  {t('actions.edit')}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      ) : null}

      <ArtikelDialog
        open={dialogMode !== null}
        artikel={dialogMode === 'bearbeiten' ? dialogArtikel : null}
        onClose={() => {
          setDialogMode(null);
          setDialogArtikel(null);
        }}
        onSaved={(art, created) => {
          setDialogMode(null);
          setDialogArtikel(null);
          reload();
          notify({ intent: 'success', title: created ? t('notify.created', { id: art.id }) : t('notify.saved', { id: art.id }) });
          if (created) setLabelTarget(art);
        }}
      />
      <ReserveDialog
        open={reserveTarget !== null}
        artikel={reserveTarget}
        onClose={() => setReserveTarget(null)}
        onDone={() => {
          setReserveTarget(null);
          reload();
        }}
      />
      <SellDialog
        open={sellTarget !== null}
        artikel={sellTarget}
        onClose={() => setSellTarget(null)}
        onDone={() => {
          setSellTarget(null);
          reload();
        }}
      />
      <LabelPreviewDialog open={labelTarget !== null} artikel={labelTarget} onClose={() => setLabelTarget(null)} />
    </div>
  );
}
