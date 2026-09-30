/** Seite Proxmox: VMs und LXCs eines Hosts laden, auswählen und als Serie drucken. */
import { useEffect, useState } from 'react';
import {
  Badge,
  Button,
  Dropdown,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Option,
  Switch,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { ArrowDownload20Regular, Print20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { ApiError } from '../../api/client';
import { DataList, type ListColumn } from '../../components/DataList';
import { EmptyState } from '../../components/EmptyState';
import { LoadingState } from '../../components/LoadingState';
import { PageHeader } from '../../components/PageHeader';
import { ModuleSettingsButton } from '../../modules/ModuleSettingsButton';
import { moduleTexts } from '../../modules';
import { Section } from '../../components/Section';
import { WarningList } from '../../components/WarningList';
import { useLayoutStyles } from '../../theme/layout';
import { fetchGuests, fetchPveHosts, prepareTable } from './api';
import type { GuestJson, GuestKind, GuestsJson, GuestsRequest, PveHostJson } from './types';

const useStyles = makeStyles({
  filters: {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'flex-end',
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalS,
  },
  narrowField: { flex: '1 1 160px', minWidth: '140px', maxWidth: '240px' },
  nameCell: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXXS, minWidth: 0 },
  passthrough: {
    fontFamily: tokens.fontFamilyMonospace,
    fontSize: tokens.fontSizeBase100,
    color: tokens.colorNeutralForeground3,
    overflowWrap: 'anywhere',
  },
  note: { color: tokens.colorNeutralForeground3 },
  mono: { fontFamily: tokens.fontFamilyMonospace, fontSize: tokens.fontSizeBase200, overflowWrap: 'anywhere' },
});

type KindFilter = 'alle' | GuestKind;

interface ErrorInfo {
  title: string;
  hint?: string;
}

function toError(err: unknown): ErrorInfo {
  if (err instanceof ApiError) return { title: err.message, hint: err.hint || undefined };
  return { title: err instanceof Error ? err.message : String(err) };
}

function ipText(guest: GuestJson, unknownText: string): string {
  return guest.ips.length > 0 ? guest.ips.join(', ') : guest.ip_note || unknownText;
}

export default function ProxmoxPage(): JSX.Element {
  const styles = useStyles();
  const layout = useLayoutStyles();
  const { t } = useTranslation('proxmox');
  const navigate = useNavigate();
  const [hosts, setHosts] = useState<PveHostJson[]>([]);
  const [hostsLoaded, setHostsLoaded] = useState(false);
  const [host, setHost] = useState<string | null>(null);
  const [onlyRunning, setOnlyRunning] = useState(false);
  const [kind, setKind] = useState<KindFilter>('alle');
  const [ids, setIds] = useState('');
  const [name, setName] = useState('');
  const [links, setLinks] = useState(true);
  const [loading, setLoading] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [result, setResult] = useState<GuestsJson | null>(null);
  const [selected, setSelected] = useState<Record<number, boolean>>({});
  const [error, setError] = useState<ErrorInfo | null>(null);
  const [tableWarnings, setTableWarnings] = useState<string[]>([]);

  const KIND_LABELS: Record<KindFilter, string> = {
    alle: t('filters.kindAll'),
    qemu: t('filters.kindQemu'),
    lxc: t('filters.kindLxc'),
  };

  function tokenHint(err: ErrorInfo, host: PveHostJson | undefined): string | undefined {
    if (!err.title.includes('Token fehlt')) return err.hint; // i18n-ignore (Server-Wert)
    const extra = t('tokenMissing.extraTokenScript');
    const where = host ? ` ${t('tokenMissing.reference', { describe: host.token_describe })}` : '';
    return [err.hint, extra + where].filter(Boolean).join(' ');
  }

  useEffect(() => {
    const controller = new AbortController();
    fetchPveHosts(controller.signal)
      .then((r) => {
        setHosts(r.hosts);
        setHostsLoaded(true);
        if (r.hosts.length > 0) setHost((h) => h ?? r.hosts[0]!.name);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(toError(err));
        setHostsLoaded(true);
      });
    return () => controller.abort();
  }, []);

  const currentHost = hosts.find((h) => h.name === host);

  const load = async () => {
    if (!host) return;
    const req: GuestsRequest = { host };
    if (onlyRunning) req.status = 'running';
    if (kind !== 'alle') req.kind = kind;
    if (ids.trim()) req.ids = ids.trim();
    if (name.trim()) req.name = name.trim();
    setLoading(true);
    setError(null);
    setTableWarnings([]);
    try {
      const r = await fetchGuests(req);
      setResult(r);
      setSelected({});
    } catch (err) {
      setResult(null);
      setError(toError(err));
    } finally {
      setLoading(false);
    }
  };

  const vmids = (result?.guests ?? []).filter((g) => selected[g.vmid]).map((g) => g.vmid);

  const printSeries = async () => {
    if (!host || vmids.length === 0) return;
    setPreparing(true);
    setError(null);
    try {
      const r = await prepareTable({ host, vmids, links });
      setTableWarnings(r.warnings);
      navigate(`/vorlagen?vorlage=${encodeURIComponent(r.template)}&import=${encodeURIComponent(r.pending_id)}`);
    } catch (err) {
      setError(toError(err));
    } finally {
      setPreparing(false);
    }
  };

  const columns: ListColumn<GuestJson>[] = [
    { id: 'vmid', header: t('guests.vmid'), kind: 'number', cell: (g) => g.vmid },
    { id: 'type', header: t('guests.type'), cell: (g) => (g.kind === 'qemu' ? t('guests.typeVm') : t('guests.typeLxc')) },
    {
      id: 'name',
      header: t('guests.name'),
      kind: 'title',
      cell: (g) => (
        <div className={styles.nameCell}>
          <span>{g.name}</span>
          {g.passthrough.length > 0 ? (
            <span className={styles.passthrough}>
              {t('guests.passthrough')}: {g.passthrough.join('; ')}
            </span>
          ) : null}
        </div>
      ),
    },
    {
      id: 'status',
      header: t('guests.status'),
      kind: 'status',
      cell: (g) => (
        <Badge appearance="tint" color={g.status === 'running' ? 'success' : 'informative'}>
          {g.status === 'running' // i18n-ignore (Server-Wert)
            ? t('guests.statusRunning')
            : g.status === 'stopped' // i18n-ignore (Server-Wert)
              ? t('guests.statusStopped')
              : g.status}
        </Badge>
      ),
    },
    {
      id: 'ip',
      header: t('guests.ip'),
      cell: (g) => <span className={g.ips.length > 0 ? styles.mono : styles.note}>{ipText(g, t('guests.ipUnknown'))}</span>,
    },
  ];

  return (
    <div className={layout.stack}>
      <PageHeader title={moduleTexts('proxmox').name} subtitle={moduleTexts('proxmox').description} />

      {error ? (
        <MessageBar intent="error" layout="multiline">
          <MessageBarBody>
            <MessageBarTitle>{error.title}</MessageBarTitle>
            {tokenHint(error, currentHost)}
          </MessageBarBody>
        </MessageBar>
      ) : null}

      {hostsLoaded && hosts.length === 0 && !error ? (
        <EmptyState title={t('noHosts.title')} body={t('noHosts.body')} action={<ModuleSettingsButton module="proxmox" />} />
      ) : null}

      {!hostsLoaded ? <LoadingState variant="section" /> : null}

      {hosts.length > 0 ? (
        <Section title={t('filters.title')} description={t('filters.description')}>
          <div className={styles.filters}>
            <Field label={t('filters.host')} className={styles.narrowField}>
              <Dropdown
                aria-label={t('filters.host')}
                value={host ?? ''}
                selectedOptions={host ? [host] : []}
                onOptionSelect={(_e, d) => {
                  setHost(d.optionValue ?? null);
                  setResult(null);
                  setSelected({});
                }}
              >
                {hosts.map((h) => (
                  <Option key={h.name} value={h.name} text={h.name}>
                    {h.name} ({h.url})
                  </Option>
                ))}
              </Dropdown>
            </Field>
            <Field label={t('filters.kind')} className={styles.narrowField}>
              <Dropdown
                aria-label={t('filters.kind')}
                value={KIND_LABELS[kind]}
                selectedOptions={[kind]}
                onOptionSelect={(_e, d) => setKind((d.optionValue as KindFilter | undefined) ?? 'alle')}
              >
                {(Object.keys(KIND_LABELS) as KindFilter[]).map((k) => (
                  <Option key={k} value={k} text={KIND_LABELS[k]}>
                    {KIND_LABELS[k]}
                  </Option>
                ))}
              </Dropdown>
            </Field>
            <Field label={t('filters.ids')} className={styles.narrowField}>
              <Input
                aria-label={t('filters.ids')}
                placeholder={t('filters.idsHint')}
                value={ids}
                onChange={(_e, d) => setIds(d.value)}
              />
            </Field>
            <Field label={t('filters.name')} className={styles.narrowField}>
              <Input aria-label={t('filters.name')} value={name} onChange={(_e, d) => setName(d.value)} />
            </Field>
            <Switch label={t('filters.onlyRunning')} checked={onlyRunning} onChange={(_e, d) => setOnlyRunning(d.checked)} />
            <Button appearance="primary" icon={<ArrowDownload20Regular />} disabled={!host || loading} onClick={() => void load()}>
              {t('filters.load')}
            </Button>
          </div>
          {currentHost && !currentHost.token_set ? (
            <MessageBar intent="warning" layout="multiline">
              <MessageBarBody>
                <MessageBarTitle>{t('tokenMissing.title')}</MessageBarTitle>
                {currentHost.token_describe}. {t('tokenMissing.extra')}
              </MessageBarBody>
            </MessageBar>
          ) : null}
        </Section>
      ) : null}

      {loading ? <LoadingState variant="list" rows={4} /> : null}

      {result ? (
        <Section
          title={t('guests.title', { host: result.host })}
          description={result.nodes.map((n) => `${n.node}: ${n.status}${n.ip ? `, ${n.ip}` : ''}`).join(' · ')}
        >
          <WarningList warnings={[...result.warnings, ...tableWarnings]} />
          <DataList
            items={result.guests}
            columns={columns}
            getKey={(g) => g.vmid}
            label={t('guests.ariaLabel')}
            empty={<Text className={styles.note}>{t('guests.none')}</Text>}
            selection={{
              isSelected: (g) => Boolean(selected[g.vmid]),
              onChange: (g, on) => setSelected((m) => ({ ...m, [g.vmid]: on })),
              onChangeAll: (on) => setSelected(Object.fromEntries(result.guests.map((g) => [g.vmid, on]))),
              itemLabel: (g) => t('guests.select', { vmid: g.vmid, name: g.name }),
              allLabel: t('guests.selectAll'),
            }}
          />
          <div className={layout.rowWrap}>
            <Switch
              label={t('actions.qrWithLink')}
              checked={links}
              onChange={(_e, d) => setLinks(d.checked)}
            />
            <Button
              appearance="primary"
              icon={<Print20Regular />}
              disabled={vmids.length === 0 || preparing}
              onClick={() => void printSeries()}
            >
              {t('actions.printSeries')}
            </Button>
            <Text className={styles.note}>{t('actions.selectedCount', { count: vmids.length })}</Text>
          </div>
        </Section>
      ) : null}
    </div>
  );
}
