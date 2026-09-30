/**
 * Assistent „Platte tauschen": Host scannen, defektes Gerät und neue Platte wählen,
 * `zpool replace`-Befehl nur zum Kopieren anzeigen (nie ausführen), Changelog-Entwurf für den
 * Vault, Labels „defekt" (alt) und „datentraeger" (neu) drucken.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Body1,
  Button,
  Field,
  Input,
  RadioGroup,
  Radio,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Textarea,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Copy20Regular, Print20Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import type { Role } from '../../api/types';
import { EmptyState } from '../../components/EmptyState';
import { ErrorMessage } from '../../components/ErrorMessage';
import { LoadingState } from '../../components/LoadingState';
import { PageHeader } from '../../components/PageHeader';
import { ModuleSettingsButton } from '../../modules/ModuleSettingsButton';
import { Section } from '../../components/Section';
import { WarningList } from '../../components/WarningList';
import { usePrintFlow } from '../../components/usePrint';
import { printLabel, useLabelRender } from '../../api/labels';
import { pngSrc } from '../../api/client';
import { useLayoutStyles } from '../../theme/layout';
import { fetchSshHosts, planZfs, scanZfs } from './api';
import type { PoolDeviceJson, ReplacePlanJson, ZfsOverviewJson } from './types';
import type { TemplateSource } from '../../api/types';

const useStyles = makeStyles({
  hostRow: { display: 'flex', alignItems: 'flex-end', columnGap: tokens.spacingHorizontalM, flexWrap: 'wrap' },
  hostSelect: { minWidth: '200px' },
  tableScroll: { overflowX: 'auto', maxWidth: '100%' },
  form: { display: 'flex', flexWrap: 'wrap', columnGap: tokens.spacingHorizontalL, rowGap: tokens.spacingVerticalM },
  code: { display: 'block', padding: tokens.spacingVerticalM, borderRadius: tokens.borderRadiusMedium, backgroundColor: tokens.colorNeutralBackground3, fontFamily: 'monospace', overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' },
  radios: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXS },
  mono: { fontFamily: tokens.fontFamilyMonospace, fontSize: tokens.fontSizeBase200, overflowWrap: 'anywhere' },
  field: { minWidth: '200px', flex: '1 1 200px', maxWidth: '320px' },
  previews: { display: 'flex', flexWrap: 'wrap', gap: tokens.spacingHorizontalM },
  preview: { maxWidth: '240px', borderRadius: tokens.borderRadiusMedium, boxShadow: tokens.shadow4 },
});

function badgeRole(state: string): Role {
  return state === 'ONLINE' ? 'success' : 'warning'; // i18n-ignore (Server-Wert)
}

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // Zwischenablage nicht verfügbar: Text bleibt zum manuellen Kopieren sichtbar
  }
}

/** Assistent als Reiter der Seite Datenträger (`embedded`: ohne eigenen Seitenkopf). */
export default function PlattentauschPage(props: { embedded?: boolean }): JSX.Element {
  const styles = useStyles();
  const layout = useLayoutStyles();
  const { t } = useTranslation('plattentausch');
  const [hosts, setHosts] = useState<{ name: string }[]>([]);
  const [hostsLoaded, setHostsLoaded] = useState(false);
  const [hostsError, setHostsError] = useState<unknown>(null);
  const [host, setHost] = useState<string | null>(null);

  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState<unknown>(null);
  const [overview, setOverview] = useState<ZfsOverviewJson | null>(null);

  const [oldName, setOldName] = useState<string | null>(null);
  const [newDevice, setNewDevice] = useState<string | null>(null);
  const [slot, setSlot] = useState('');
  const [reason, setReason] = useState('');

  const [planning, setPlanning] = useState(false);
  const [planError, setPlanError] = useState<unknown>(null);
  const [plan, setPlan] = useState<ReplacePlanJson | null>(null);

  const printOld = usePrintFlow<TemplateSource>((req, opts) => printLabel(req, opts));
  const printNew = usePrintFlow<TemplateSource>((req, opts) => printLabel(req, opts));

  const oldSource = useMemo<TemplateSource | null>(
    () => (plan ? { kind: 'template', template: plan.old_label.template, values: plan.old_label.values } : null),
    [plan],
  );
  const newSource = useMemo<TemplateSource | null>(
    () => (plan ? { kind: 'template', template: plan.new_label.template, values: plan.new_label.values } : null),
    [plan],
  );
  const oldPreview = useLabelRender(oldSource);
  const newPreview = useLabelRender(newSource);

  useEffect(() => {
    fetchSshHosts()
      .then((r) => {
        setHosts(r.hosts);
        setHostsLoaded(true);
        if (r.hosts.length > 0) setHost((h) => h ?? r.hosts[0]!.name);
      })
      .catch((err: unknown) => setHostsError(err));
  }, []);

  const resetSelection = () => {
    setOldName(null);
    setNewDevice(null);
    setSlot('');
    setReason('');
    setPlan(null);
    setPlanError(null);
  };

  const scan = async () => {
    if (!host) return;
    setScanning(true);
    setScanError(null);
    resetSelection();
    try {
      const r = await scanZfs(host);
      setOverview(r);
    } catch (err) {
      setOverview(null);
      setScanError(err);
    } finally {
      setScanning(false);
    }
  };

  const selectOld = (name: string) => {
    setOldName(name);
    setPlan(null);
    setPlanError(null);
  };

  const selectNew = (device: string) => {
    setNewDevice(device);
    setPlan(null);
    setPlanError(null);
  };

  const canPlan = Boolean(host && oldName && newDevice && slot.trim());

  const createPlan = async () => {
    if (!host || !oldName || !newDevice || !slot.trim()) return;
    setPlanning(true);
    setPlanError(null);
    try {
      const result = await planZfs({ host, old: oldName, new_device: newDevice, slot: slot.trim(), reason: reason.trim() || undefined });
      setPlan(result);
    } catch (err) {
      setPlan(null);
      setPlanError(err);
    } finally {
      setPlanning(false);
    }
  };

  const problems = overview?.problems ?? [];
  const candidates = overview?.candidates ?? [];

  const printLabelOld = () => {
    if (!plan) return;
    const source: TemplateSource = { kind: 'template', template: plan.old_label.template, values: plan.old_label.values };
    void printOld.run(source);
  };
  const printLabelNew = () => {
    if (!plan) return;
    const source: TemplateSource = { kind: 'template', template: plan.new_label.template, values: plan.new_label.values };
    void printNew.run(source);
  };

  if (hostsError) {
    return <ErrorMessage error={hostsError} />;
  }

  return (
    <div className={layout.stack}>
      {props.embedded ? null : <PageHeader title={t('title')} subtitle={t('subtitle')} />}

      <Section title={t('steps.scan')}>
        {!hostsLoaded ? <LoadingState variant="inline" /> : null}
        {hostsLoaded && hosts.length === 0 ? (
          <EmptyState title={t('noHosts.title')} body={t('noHosts.body')} action={<ModuleSettingsButton module="datentraeger" />} />
        ) : hostsLoaded ? (
          <div className={styles.hostRow}>
            <Field label={t('host')}>
              <Select
                className={styles.hostSelect}
                value={host ?? ''}
                onChange={(_e, d) => {
                  setHost(d.value || null);
                  setOverview(null);
                  resetSelection();
                  setScanError(null);
                }}
              >
                {hosts.map((h) => (
                  <option key={h.name} value={h.name}>
                    {h.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Button appearance="primary" onClick={() => void scan()} disabled={!host || scanning}>
              {scanning ? t('scanning') : t('scan')}
            </Button>
          </div>
        ) : null}
        {scanError ? <ErrorMessage error={scanError} /> : null}
      </Section>

      {overview ? (
        <Section title={t('steps.broken')}>
          {problems.length === 0 ? (
            <EmptyState title={t('noBroken')} />
          ) : (
            <div className={styles.tableScroll}>
              <Table aria-label={t('table.ariaLabel')} size="small">
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell>
                      <span className="p12-visually-hidden">{t('table.selectColumn')}</span>
                    </TableHeaderCell>
                    <TableHeaderCell>{t('table.pool')}</TableHeaderCell>
                    <TableHeaderCell>{t('table.vdev')}</TableHeaderCell>
                    <TableHeaderCell>{t('table.state')}</TableHeaderCell>
                    <TableHeaderCell>{t('table.oldSerial')}</TableHeaderCell>
                    <TableHeaderCell>{t('table.note')}</TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {problems.map((p: PoolDeviceJson) => (
                    <TableRow key={p.name}>
                      <TableCell>
                        <Radio
                          name="old-device"
                          value={p.name}
                          aria-label={t('table.select', { name: p.name })}
                          checked={oldName === p.name}
                          onChange={() => selectOld(p.name)}
                        />
                      </TableCell>
                      <TableCell>{p.pool}</TableCell>
                      <TableCell>{p.vdev ?? ''}</TableCell>
                      <TableCell>
                        <Badge color={badgeRole(p.state) === 'success' ? 'success' : 'warning'}>{p.state}</Badge>
                      </TableCell>
                      <TableCell className={styles.mono}>{p.by_id ?? p.name}</TableCell>
                      <TableCell>{p.note}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </Section>
      ) : null}

      {overview && problems.length > 0 ? (
        <Section title={t('steps.newDisk')}>
          {candidates.length === 0 ? (
            <EmptyState title={t('noCandidates.title')} body={t('noCandidates.body')} />
          ) : (
            <RadioGroup
              className={styles.radios}
              value={newDevice ?? ''}
              onChange={(_e, d) => selectNew(d.value)}
            >
              {candidates.map((c) => (
                <Radio
                  key={c.disk.device}
                  value={c.disk.device}
                  label={`${c.disk.device} · ${c.disk.model} · ${c.reason}`}
                />
              ))}
            </RadioGroup>
          )}
          <div className={styles.form}>
            <Field label={t('slot')} className={styles.field}>
              <Input value={slot} onChange={(_e, d) => setSlot(d.value)} />
            </Field>
            <Field label={t('reason')} className={styles.field}>
              <Input value={reason} onChange={(_e, d) => setReason(d.value)} placeholder={t('reasonPlaceholder')} />
            </Field>
          </div>
          <div className={layout.rowWrap}>
            <Button appearance="primary" onClick={() => void createPlan()} disabled={!canPlan || planning}>
              {planning ? t('planning') : t('createPlan')}
            </Button>
          </div>
          {planError ? <ErrorMessage error={planError} /> : null}
        </Section>
      ) : null}

      {plan ? (
        <Section title={t('steps.commandChangelog')}>
          <Body1>{t('commandLabel')}</Body1>
          <code className={styles.code}>{plan.command}</code>
          <div className={layout.rowWrap}>
            <Button icon={<Copy20Regular />} onClick={() => void copyText(plan.command)}>
              {t('copyCommand')}
            </Button>
          </div>
          <WarningList notes={plan.hints} />
          <Field label={t('changelogDraft')}>
            <Textarea readOnly value={plan.changelog_md} rows={8} />
          </Field>
          <div className={layout.rowWrap}>
            <Button icon={<Copy20Regular />} onClick={() => void copyText(plan.changelog_md)}>
              {t('copyChangelog')}
            </Button>
          </div>
        </Section>
      ) : null}

      {plan ? (
        <Section title={t('steps.printLabels')}>
          <div className={styles.previews}>
            {oldPreview.data?.preview ? (
              <img className={styles.preview} src={pngSrc(oldPreview.data.preview.design_png)} alt={t('previewOldAlt')} />
            ) : null}
            {newPreview.data?.preview ? (
              <img className={styles.preview} src={pngSrc(newPreview.data.preview.design_png)} alt={t('previewNewAlt')} />
            ) : null}
          </div>
          <div className={layout.rowWrap}>
            <Button appearance="primary" icon={<Print20Regular />} onClick={printLabelOld} disabled={printOld.busy}>
              {t('printOldLabel')}
            </Button>
            <Button icon={<Print20Regular />} onClick={printLabelNew} disabled={printNew.busy}>
              {t('printNewLabel')}
            </Button>
          </div>
        </Section>
      ) : null}
    </div>
  );
}
