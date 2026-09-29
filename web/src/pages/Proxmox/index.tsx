/** Seite Proxmox: VMs und LXCs eines Hosts laden, auswählen und als Serie drucken. */
import { useEffect, useState } from 'react';
import {
  Badge,
  Button,
  Checkbox,
  Dropdown,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Option,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { ArrowDownload20Regular, Print20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { ApiError } from '../../api/client';
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
  narrowField: { minWidth: '120px', maxWidth: '100%' },
  /** Eigener Scroll-Container: die Tabelle scrollt seitlich, nie die ganze Seite. */
  tableScroll: { overflowX: 'auto', maxWidth: '100%' },
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

  const allChecked = result !== null && result.guests.length > 0 && result.guests.every((g) => selected[g.vmid]);

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
            <Field label={t('filters.ids')} hint={t('filters.idsHint')} className={styles.narrowField}>
              <Input aria-label={t('filters.ids')} value={ids} onChange={(_e, d) => setIds(d.value)} />
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
          {result.guests.length === 0 ? (
            <Text className={styles.note}>{t('guests.none')}</Text>
          ) : (
            <div className={styles.tableScroll}>
              <Table aria-label={t('guests.ariaLabel')} size="small">
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell>
                      <Checkbox
                        aria-label={t('guests.selectAll')}
                        checked={allChecked}
                        onChange={(_e, d) =>
                          setSelected(Object.fromEntries(result.guests.map((g) => [g.vmid, Boolean(d.checked)])))
                        }
                      />
                    </TableHeaderCell>
                    <TableHeaderCell>{t('guests.vmid')}</TableHeaderCell>
                    <TableHeaderCell>{t('guests.type')}</TableHeaderCell>
                    <TableHeaderCell>{t('guests.name')}</TableHeaderCell>
                    <TableHeaderCell>{t('guests.status')}</TableHeaderCell>
                    <TableHeaderCell>{t('guests.ip')}</TableHeaderCell>
                    <TableHeaderCell>{t('guests.passthrough')}</TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {result.guests.map((g) => (
                    <TableRow key={g.vmid}>
                      <TableCell>
                        <Checkbox
                          aria-label={t('guests.select', { vmid: g.vmid, name: g.name })}
                          checked={Boolean(selected[g.vmid])}
                          onChange={(_e, d) => setSelected((m) => ({ ...m, [g.vmid]: Boolean(d.checked) }))}
                        />
                      </TableCell>
                      <TableCell>{g.vmid}</TableCell>
                      <TableCell>{g.kind === 'qemu' ? t('guests.typeVm') : t('guests.typeLxc')}</TableCell>
                      <TableCell>{g.name}</TableCell>
                      <TableCell>
                        <Badge appearance="tint" color={g.status === 'running' ? 'success' : 'informative'}>
                          {g.status === 'running' // i18n-ignore (Server-Wert)
                            ? t('guests.statusRunning')
                            : g.status === 'stopped' // i18n-ignore (Server-Wert)
                              ? t('guests.statusStopped')
                              : g.status}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <span className={g.ips.length > 0 ? styles.mono : styles.note}>{ipText(g, t('guests.ipUnknown'))}</span>
                      </TableCell>
                      <TableCell>
                        <span className={styles.mono}>{g.passthrough.join('; ')}</span>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
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
