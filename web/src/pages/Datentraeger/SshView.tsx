/** Reiter „SSH": Host wählen, Platten scannen, Serie mit Slot planen und drucken. */
import { useEffect, useRef, useState } from 'react';
import {
  Button,
  Checkbox,
  Dropdown,
  Field,
  Input,
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  Option,
  Spinner,
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
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { ApiError, pngSrc } from '../../api/client';
import { useMediaQuery } from '../../components/useMediaQuery';
import { usePrintFlow } from '../../components/usePrint';
import { WarningList } from '../../components/WarningList';
import type { BatchPlanJson, DiskJson, SshHostJson, SshSeriesRequest } from '../../api/types';
import { fetchSshHosts, planSshSeries, printSshSeries, scanSshHost } from './api';
import { errorText } from './errors';

const useStyles = makeStyles({
  hostRow: { display: 'flex', alignItems: 'flex-end', columnGap: tokens.spacingHorizontalM, marginBottom: tokens.spacingVerticalM, flexWrap: 'wrap' },
  options: { display: 'flex', flexWrap: 'wrap', columnGap: tokens.spacingHorizontalL, rowGap: tokens.spacingVerticalS, margin: `${tokens.spacingVerticalM} 0` },
  actions: { display: 'flex', flexWrap: 'wrap', columnGap: tokens.spacingHorizontalS, rowGap: tokens.spacingVerticalS, margin: `${tokens.spacingVerticalM} 0` },
  /** Eigener Scroll-Container: eine breite Tabelle scrollt hier seitlich, nie die ganze Seite. */
  tableScroll: { overflowX: 'auto', maxWidth: '100%' },
  cards: { listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS },
  card: {
    display: 'grid',
    gridTemplateColumns: 'auto 1fr',
    columnGap: tokens.spacingHorizontalS,
    rowGap: tokens.spacingVerticalXXS,
    padding: tokens.spacingHorizontalM,
    borderRadius: tokens.borderRadiusMedium,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    backgroundColor: tokens.colorNeutralBackground1,
    minWidth: 0,
  },
  cardHead: { gridColumn: '1 / -1', display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalS, fontWeight: tokens.fontWeightSemibold },
  cardLabel: { color: tokens.colorNeutralForeground3, fontSize: tokens.fontSizeBase200 },
  cardValue: { minWidth: 0, overflowWrap: 'anywhere', fontSize: tokens.fontSizeBase200 },
  slotInput: { width: '72px' },
  previewGrid: { display: 'flex', flexWrap: 'wrap', gap: tokens.spacingHorizontalM, marginTop: tokens.spacingVerticalM },
  previewCard: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXS, alignItems: 'center' },
  previewImg: { maxWidth: '160px', borderRadius: tokens.borderRadiusMedium, boxShadow: tokens.shadow4 },
});

/** Ab dieser Breite werden die Platten als Karten statt als Tabelle gezeigt (responsiv bis 360 px). */
const NARROW_QUERY = '(max-width: 639px)';

function poolText(disk: DiskJson): string {
  if (!disk.pool) return '';
  return disk.vdev ? `${disk.pool}/${disk.vdev}` : disk.pool;
}

export function SshView(): JSX.Element {
  const { t } = useTranslation('datentraeger');
  const styles = useStyles();
  const [hosts, setHosts] = useState<SshHostJson[]>([]);
  const [hostsLoaded, setHostsLoaded] = useState(false);
  const [host, setHost] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<ApiError | null>(null);
  const [disks, setDisks] = useState<DiskJson[]>([]);
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [slots, setSlots] = useState<Record<string, string>>({});
  const [chain, setChain] = useState(false);
  const [cutMarks, setCutMarks] = useState(true);
  const [plan, setPlan] = useState<BatchPlanJson | null>(null);
  const [planning, setPlanning] = useState(false);
  const [hostsError, setHostsError] = useState<{ title: string; hint?: string } | null>(null);
  const [planError, setPlanError] = useState<{ title: string; hint?: string } | null>(null);

  const printFlow = usePrintFlow<SshSeriesRequest>((req, opts) => printSshSeries(req, opts));
  const narrow = useMediaQuery(NARROW_QUERY);
  /** Zählt jede Änderung an Auswahl, Slot, Kette oder Schnittmarken: eine ältere Vorschau (auch eine noch
   *  laufende Anfrage) passt dann nicht mehr und wird verworfen. Drucken geht erst nach neuer Vorschau. */
  const inputRevision = useRef(0);
  const invalidatePlan = () => {
    inputRevision.current += 1;
    setPlan(null);
  };

  useEffect(() => {
    fetchSshHosts()
      .then((r) => {
        setHosts(r.hosts);
        setHostsLoaded(true);
        if (r.hosts.length > 0) setHost((h) => h ?? r.hosts[0]!.name);
      })
      .catch((err: unknown) => setHostsError(errorText(err)));
  }, []);

  const selectedDisks = disks.filter((d) => checked[d.device] ?? true);

  const buildRequest = (): SshSeriesRequest | null => {
    if (!host || selectedDisks.length === 0) return null;
    return { host, disks: selectedDisks, slots, chain, cut_marks: cutMarks };
  };

  const scan = async () => {
    if (!host) return;
    setScanning(true);
    setScanError(null);
    setPlanError(null);
    invalidatePlan();
    try {
      const r = await scanSshHost(host);
      setDisks(r.disks);
      setChecked(Object.fromEntries(r.disks.map((d) => [d.device, true])));
      setSlots(Object.fromEntries(r.disks.map((d) => [d.device, d.device])));
    } catch (err) {
      if (err instanceof ApiError) setScanError(err);
      setDisks([]);
    } finally {
      setScanning(false);
    }
  };

  const runPlan = async () => {
    const req = buildRequest();
    if (!req) return;
    const revision = inputRevision.current;
    setPlanning(true);
    setPlanError(null);
    try {
      const result = await planSshSeries(req);
      if (revision === inputRevision.current) setPlan(result);
    } catch (err) {
      setPlan(null);
      if (revision === inputRevision.current) setPlanError(errorText(err));
    } finally {
      setPlanning(false);
    }
  };

  const toggleDisk = (device: string, value: boolean) => {
    setChecked((m) => ({ ...m, [device]: value }));
    invalidatePlan();
  };

  const changeSlot = (device: string, value: string) => {
    setSlots((m) => ({ ...m, [device]: value }));
    invalidatePlan();
  };

  const runPrint = () => {
    const req = buildRequest();
    if (!req) return;
    void printFlow.run(req, { chain, cut_marks: cutMarks });
  };

  const canPrint = plan !== null && plan.errors.length === 0 && !printFlow.busy;

  if (hostsError) {
    return (
      <MessageBar intent="error">
        <MessageBarBody>
          <MessageBarTitle>{hostsError.title}</MessageBarTitle>
          {hostsError.hint}
        </MessageBarBody>
      </MessageBar>
    );
  }

  if (hostsLoaded && hosts.length === 0) {
    return (
      <MessageBar intent="warning">
        <MessageBarBody>
          <MessageBarTitle>{t('ssh.hostsEmpty.title')}</MessageBarTitle>
          {t('ssh.hostsEmpty.before')} <code>ssh.hosts</code> {t('ssh.hostsEmpty.after')} {'{'}"name": "pmx10", "host": "192.0.2.60", "user": "root",
          "key": "%USERPROFILE%\\.ssh\\id_ed25519_homelab"{'}'}. <Link to="/einstellungen?abschnitt=modul-datentraeger">{t('ssh.hostsEmpty.link')}</Link>
        </MessageBarBody>
      </MessageBar>
    );
  }

  return (
    <div>
      <div className={styles.hostRow}>
        <Field label={t('ssh.host')}>
          <Dropdown
            value={host ?? ''}
            selectedOptions={host ? [host] : []}
            onOptionSelect={(_e, d) => {
              setHost(d.optionValue ?? null);
              setDisks([]);
              invalidatePlan();
              setScanError(null);
              setPlanError(null);
            }}
          >
            {hosts.map((h) => (
              <Option key={h.name} value={h.name}>
                {h.name}
              </Option>
            ))}
          </Dropdown>
        </Field>
        <Button appearance="primary" onClick={() => void scan()} disabled={!host || scanning}>
          {scanning ? <Spinner size="tiny" label={t('ssh.scanning')} labelPosition="after" /> : t('ssh.scan')}
        </Button>
      </div>

      {scanError ? (
        <MessageBar intent="error">
          <MessageBarBody>
            <MessageBarTitle>{scanError.message}</MessageBarTitle>
            {scanError.hint || undefined}
          </MessageBarBody>
        </MessageBar>
      ) : null}

      {disks.length > 0 ? (
        <>
          {narrow ? (
            <ul className={styles.cards} aria-label={t('ssh.foundDisks')}>
              {disks.map((disk) => (
                <li key={disk.device} className={styles.card}>
                  <div className={styles.cardHead}>
                    <Checkbox
                      checked={checked[disk.device] ?? true}
                      onChange={(_e, d) => toggleDisk(disk.device, Boolean(d.checked))}
                      aria-label={t('ssh.select', { device: disk.device })}
                    />
                    <span>{disk.device}</span>
                  </div>
                  <span className={styles.cardLabel}>{t('ssh.table.model')}</span>
                  <span className={styles.cardValue}>{disk.model}</span>
                  <span className={styles.cardLabel}>{t('ssh.table.serial')}</span>
                  <span className={styles.cardValue}>{disk.serial}</span>
                  <span className={styles.cardLabel}>{t('ssh.table.size')}</span>
                  <span className={styles.cardValue}>{disk.size}</span>
                  <span className={styles.cardLabel}>{t('ssh.table.pool')}</span>
                  <span className={styles.cardValue}>{poolText(disk)}</span>
                  <span className={styles.cardLabel}>{t('ssh.table.byId')}</span>
                  <span className={styles.cardValue}>{disk.by_id ?? ''}</span>
                  <span className={styles.cardLabel}>{t('ssh.table.slot')}</span>
                  <Input
                    className={styles.slotInput}
                    size="small"
                    value={slots[disk.device] ?? ''}
                    onChange={(_e, d) => changeSlot(disk.device, d.value)}
                    aria-label={t('ssh.slotFor', { device: disk.device })}
                  />
                </li>
              ))}
            </ul>
          ) : (
            <div className={styles.tableScroll}>
              <Table aria-label={t('ssh.foundDisks')}>
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell />
                    <TableHeaderCell>{t('ssh.table.device')}</TableHeaderCell>
                    <TableHeaderCell>{t('ssh.table.model')}</TableHeaderCell>
                    <TableHeaderCell>{t('ssh.table.serial')}</TableHeaderCell>
                    <TableHeaderCell>{t('ssh.table.size')}</TableHeaderCell>
                    <TableHeaderCell>{t('ssh.table.pool')}</TableHeaderCell>
                    <TableHeaderCell>{t('ssh.table.byId')}</TableHeaderCell>
                    <TableHeaderCell>{t('ssh.table.slot')}</TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {disks.map((disk) => (
                    <TableRow key={disk.device}>
                      <TableCell>
                        <Checkbox
                          checked={checked[disk.device] ?? true}
                          onChange={(_e, d) => toggleDisk(disk.device, Boolean(d.checked))}
                          aria-label={t('ssh.select', { device: disk.device })}
                        />
                      </TableCell>
                      <TableCell>{disk.device}</TableCell>
                      <TableCell>{disk.model}</TableCell>
                      <TableCell>{disk.serial}</TableCell>
                      <TableCell>{disk.size}</TableCell>
                      <TableCell>{poolText(disk)}</TableCell>
                      <TableCell>{disk.by_id ?? ''}</TableCell>
                      <TableCell>
                        <Input
                          className={styles.slotInput}
                          size="small"
                          value={slots[disk.device] ?? ''}
                          onChange={(_e, d) => changeSlot(disk.device, d.value)}
                          aria-label={t('ssh.slotFor', { device: disk.device })}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}

          <div className={styles.options}>
            <Switch
              label={t('ssh.chain')}
              checked={chain}
              onChange={(_e, d) => {
                setChain(d.checked);
                invalidatePlan();
              }}
            />
            <Switch
              label={t('ssh.cutMarks')}
              checked={cutMarks}
              onChange={(_e, d) => {
                setCutMarks(d.checked);
                invalidatePlan();
              }}
            />
          </div>

          <div className={styles.actions}>
            <Button onClick={() => void runPlan()} disabled={selectedDisks.length === 0 || planning}>
              {planning ? <Spinner size="tiny" label={t('ssh.planning')} labelPosition="after" /> : t('ssh.preview')}
            </Button>
            <Button appearance="primary" onClick={runPrint} disabled={!canPrint}>
              {t('ssh.print')}
            </Button>
          </div>

          {planError ? (
            <MessageBar intent="error">
              <MessageBarBody>
                <MessageBarTitle>{planError.title}</MessageBarTitle>
                {planError.hint}
              </MessageBarBody>
            </MessageBar>
          ) : null}

          {plan ? (
            <>
              <Text>{plan.summary}</Text>
              <WarningList errors={plan.errors} warnings={plan.warnings} />
              <div className={styles.previewGrid}>
                {plan.previews.map((p) => (
                  <div key={p.index} className={styles.previewCard}>
                    <img className={styles.previewImg} src={pngSrc(p.design_png)} alt={p.title} />
                    <Text size={200}>{p.title}</Text>
                  </div>
                ))}
              </div>
            </>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
