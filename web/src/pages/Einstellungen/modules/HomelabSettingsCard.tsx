/**
 * Einstellungskarte eines Moduls aus homelab.json im Raster der Einstellungsseite (FieldRow mit
 * fester Steuerspalte, Einheiten, Platzhalter „Nicht gesetzt“ bzw. „Standard: …“). Speichern und
 * Verwerfen je Karte, „Prüfen“ zeigt ohne Netzzugriff, ob der Dienst eingetragen ist und das Token
 * gefunden wird. Tokens stehen als Kennwortfelder (`SecretField`) direkt in der Karte und werden
 * sofort in den Windows-Anmeldeinformationen gespeichert, nie in homelab.json.
 */
import { useId, useMemo, useState, type ReactNode } from 'react';
import {
  Badge,
  Button,
  Checkbox,
  Input,
  MessageBar,
  MessageBarBody,
  Spinner,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { Add20Regular, ArrowClockwise20Regular, Delete20Regular } from '@fluentui/react-icons';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { ApiError } from '../../../api/client';
import { Section } from '../../../components/Section';
import { SecretField, SecretStateBadge } from '../../../components/SecretField';
import { useSecrets } from '../../../api/secrets';
import { useNotify } from '../../../components/NotifyProvider';
import { homelabKeys, patchHomelabSettings, useHomelabCheck } from '../../HomelabEinstellungen/api';
import type { HomelabSettings, ProxmoxHostJson, ServiceCheckJson } from '../../HomelabEinstellungen/types';
import { FieldRow, FieldRows, ToggleControl } from '../../../components/FieldRow';
import { UnitText } from '../fields/SettingFieldRow';
import { formatNumberText, parseNumberText } from '../fields/numberText';
import { HOMELAB_FIELDS, fieldI18nId, type HomelabFieldDef } from './homelabFields';

const WARRANTY_KEYS: { id: string; labelKey: string }[] = [
  { id: 'kaufdatum', labelKey: 'kaufdatum' },
  { id: 'garantie_monate', labelKey: 'garantieMonate' },
  { id: 'garantie_bis', labelKey: 'garantieBis' },
];

const useStyles = makeStyles({
  actions: { display: 'flex', columnGap: tokens.spacingHorizontalS, alignItems: 'center', flexWrap: 'wrap' },
  tableWrap: { overflowX: 'auto', maxWidth: '100%' },
  hostInput: { minWidth: '140px', width: '100%' },
  hostActions: { display: 'flex', columnGap: tokens.spacingHorizontalS, paddingTop: tokens.spacingVerticalS },
  muted: { color: tokens.colorNeutralForeground3 },
  states: { display: 'flex', flexDirection: 'column', alignItems: 'flex-end', rowGap: tokens.spacingVerticalXS },
  stateLine: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalS, flexWrap: 'wrap', justifyContent: 'flex-end' },
  warranty: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalS, width: '100%' },
});

function getValue(settings: HomelabSettings | undefined, key: string): unknown {
  const [section, name] = key.split('.') as [string, string];
  return settings?.[section]?.[name];
}

function toText(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) return value.join(', ');
  return String(value);
}

/** Eingabe eines Felds als Wert für homelab.json. Ungültige Zahlen bleiben Text (der Dienst meldet sie). */
function toValue(field: HomelabFieldDef, raw: unknown): unknown {
  if (field.kind === 'bool' || field.kind === 'warranty' || field.kind === 'hosts') return raw;
  const text = String(raw ?? '').trim();
  switch (field.kind) {
    case 'optionalText':
    case 'tokenRef':
      return text === '' ? null : text;
    case 'number':
    case 'int': {
      const parsed = parseNumberText(text);
      return parsed !== null && Number.isFinite(parsed) ? parsed : text;
    }
    case 'list':
      return text
        .split(',')
        .map((part) => part.trim())
        .filter((part) => part !== '');
    default:
      return text;
  }
}

function cleanHost(host: ProxmoxHostJson): ProxmoxHostJson {
  return { name: host.name, url: host.url, token_ref: host.token_ref ?? null, verify_tls: Boolean(host.verify_tls) };
}

function placeholderFor(field: HomelabFieldDef, t: TFunction<'einstellungen'>, lang: string): string {
  if (field.default === undefined) return t('field.notSet');
  const value = typeof field.default === 'number' ? formatNumberText(field.default, lang) : field.default;
  return t('field.defaultValue', { value });
}

function ServiceState(props: { service: ServiceCheckJson }): JSX.Element {
  const { t } = useTranslation('homelabEinstellungen');
  const styles = useStyles();
  const { service } = props;
  return (
    <span className={styles.stateLine}>
      <span>{service.label}</span>
      <Badge appearance="tint" color={service.configured ? 'success' : 'warning'}>
        {service.configured ? t('check.configured') : t('check.notConfigured')}
      </Badge>
      {service.token_set === null ? null : (
        <Badge appearance="tint" color={service.token_set ? 'success' : 'danger'}>
          {service.token_set ? t('check.tokenPresent') : t('check.tokenMissing')}
        </Badge>
      )}
    </span>
  );
}

export function HomelabSettingsCard(props: {
  /** DOM-ID (Sprungziel `?abschnitt=`). */
  id: string;
  title: string;
  description?: ReactNode;
  /** Abschnitte aus homelab.json in dieser Karte (z. B. `assets` und `shortlink`). */
  sections: string[];
  /** Dienst-Kennungen aus /homelab/check für „Prüfen“ (leer: kein Prüfen-Knopf). */
  services: string[];
  settings: HomelabSettings | undefined;
}): JSX.Element {
  const { t, i18n } = useTranslation('homelabEinstellungen');
  const { t: tSettings } = useTranslation('einstellungen');
  const styles = useStyles();
  const queryClient = useQueryClient();
  const notify = useNotify();
  const reactId = useId();
  const lang = i18n.language;
  const { settings } = props;
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [hostsDraft, setHostsDraft] = useState<ProxmoxHostJson[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string[]>>({});
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  const check = useHomelabCheck({ enabled: checked });
  const secrets = useSecrets();

  const fields = useMemo(() => props.sections.flatMap((section) => HOMELAB_FIELDS[section] ?? []), [props.sections]);
  const hasHosts = fields.some((f) => f.kind === 'hosts');
  const originalHosts = useMemo(
    () => ((getValue(settings, 'proxmox.hosts') as ProxmoxHostJson[] | undefined) ?? []).map(cleanHost),
    [settings],
  );
  const hosts = hostsDraft ?? originalHosts;

  const changes = useMemo(() => {
    const result: Record<string, unknown> = {};
    for (const field of fields) {
      if (field.kind === 'hosts' || !(field.key in draft)) continue;
      const value = toValue(field, draft[field.key]);
      if (JSON.stringify(value) !== JSON.stringify(getValue(settings, field.key) ?? null)) result[field.key] = value;
    }
    if (hasHosts && hostsDraft !== null && JSON.stringify(hostsDraft.map(cleanHost)) !== JSON.stringify(originalHosts)) {
      result['proxmox.hosts'] = hostsDraft.map(cleanHost);
    }
    return result;
  }, [draft, fields, hasHosts, hostsDraft, originalHosts, settings]);
  const dirty = Object.keys(changes).length > 0;

  const edit = (key: string, value: unknown) => setDraft((prev) => ({ ...prev, [key]: value }));
  const discard = () => {
    setDraft({});
    setHostsDraft(null);
    setFieldErrors({});
    setGeneralError(null);
  };
  const shown = (field: HomelabFieldDef): unknown => (field.key in draft ? draft[field.key] : getValue(settings, field.key));

  const save = async () => {
    setSaving(true);
    setFieldErrors({});
    setGeneralError(null);
    try {
      const result = await patchHomelabSettings(changes);
      queryClient.setQueryData(homelabKeys.settings, result);
      setDraft({});
      setHostsDraft(null);
      void queryClient.invalidateQueries({ queryKey: homelabKeys.check });
      notify({ intent: 'success', title: tSettings('notify.savedTitle', { title: props.title }) });
    } catch (err) {
      const apiError = err instanceof ApiError ? err : null;
      const errors = Array.isArray(apiError?.details?.errors) ? (apiError?.details?.errors as unknown[]).map(String) : [];
      if (errors.length) {
        const byField: Record<string, string[]> = {};
        const general: string[] = [];
        for (const message of errors) {
          const key = Object.keys(changes).find((k) => message.includes(`'${k}`));
          if (key) byField[key] = [...(byField[key] ?? []), message];
          else general.push(message);
        }
        setFieldErrors(byField);
        setGeneralError(general.length ? general.join(' ') : null);
      } else {
        setGeneralError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setSaving(false);
    }
  };

  const onCheck = () => {
    if (checked) void check.refetch();
    else setChecked(true);
  };

  const matching = (check.data?.services ?? []).filter((s) =>
    props.services.some((id) => s.id === id || s.id.startsWith(`${id}:`)),
  );

  const renderHosts = (field: HomelabFieldDef): JSX.Element => {
    const id = fieldI18nId(field.key);
    const errors = fieldErrors['proxmox.hosts'];
    const infos = (getValue(settings, 'proxmox.hosts') as ProxmoxHostJson[] | undefined) ?? [];
    return (
      <FieldRow key={field.key} label={t(`fields.${id}.label`)} help={t(`fields.${id}.help`)} layout="stacked">
        {hosts.length ? (
          <div className={styles.tableWrap}>
            <Table size="small" aria-label={t('hosts.tableAriaLabel')}>
              <TableHeader>
                <TableRow>
                  <TableHeaderCell>{t('hosts.columns.name')}</TableHeaderCell>
                  <TableHeaderCell>{t('hosts.columns.url')}</TableHeaderCell>
                  <TableHeaderCell>{t('hosts.columns.verifyTls')}</TableHeaderCell>
                  <TableHeaderCell>{t('hosts.columns.token')}</TableHeaderCell>
                  <TableHeaderCell>
                    <span className="p12-visually-hidden">{t('hosts.actionsColumn')}</span>
                  </TableHeaderCell>
                </TableRow>
              </TableHeader>
              <TableBody>
                {hosts.map((host, index) => {
                  const saved = infos.some((entry) => entry.name === host.name);
                  const slot = saved ? secrets.data?.slots.find((s) => s.id === `proxmox:${host.name}`) : undefined;
                  const n = index + 1;
                  const update = (patch: Partial<ProxmoxHostJson>) =>
                    setHostsDraft(hosts.map((h, i) => (i === index ? { ...h, ...patch } : h)));
                  return (
                    <TableRow key={index}>
                      <TableCell>
                        <Input className={styles.hostInput} aria-label={t('hosts.nameAria', { n })} value={host.name} onChange={(_e, d) => update({ name: d.value })} />
                      </TableCell>
                      <TableCell>
                        <Input
                          className={styles.hostInput}
                          aria-label={t('hosts.urlAria', { n })}
                          placeholder={t('hosts.urlPlaceholder')}
                          value={host.url}
                          onChange={(_e, d) => update({ url: d.value })}
                        />
                      </TableCell>
                      <TableCell>
                        <Checkbox
                          aria-label={t('hosts.verifyTlsAria', { n })}
                          checked={Boolean(host.verify_tls)}
                          onChange={(_e, d) => update({ verify_tls: d.checked === true })}
                        />
                      </TableCell>
                      <TableCell>
                        {saved ? <SecretStateBadge slot={slot} /> : <span className={styles.muted}>{t('hosts.tokenAfterSave')}</span>}
                      </TableCell>
                      <TableCell>
                        <Button
                          appearance="subtle"
                          icon={<Delete20Regular />}
                          aria-label={t('hosts.removeAria', { n })}
                          onClick={() => setHostsDraft(hosts.filter((_h, i) => i !== index))}
                        />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        ) : (
          <p className={styles.muted}>{t('hosts.empty')}</p>
        )}
        {errors?.length ? (
          <MessageBar intent="error">
            <MessageBarBody>{errors.join(' ')}</MessageBarBody>
          </MessageBar>
        ) : null}
        <div className={styles.hostActions}>
          <Button icon={<Add20Regular />} onClick={() => setHostsDraft([...hosts, { name: '', url: '', token_ref: null, verify_tls: false }])}>
            {t('hosts.add')}
          </Button>
        </div>
      </FieldRow>
    );
  };

  const renderField = (field: HomelabFieldDef): JSX.Element => {
    if (field.kind === 'hosts') return renderHosts(field);
    const i18nId = fieldI18nId(field.key);
    if (field.kind === 'tokenRef') {
      return <SecretField key={field.key} slotId={field.key.split('.')[0] ?? ''} label={t(`fields.${i18nId}.label`)} help={t('token.help')} />;
    }
    const domId = `${reactId}-${i18nId}`;
    const label = t(`fields.${i18nId}.label`);
    const errors = fieldErrors[field.key];
    const help = t(`fields.${i18nId}.help`);
    const details = errors?.length ? (
      <MessageBar intent="error">
        <MessageBarBody>{errors.join(' ')}</MessageBarBody>
      </MessageBar>
    ) : undefined;
    const value = shown(field);
    if (field.kind === 'bool') {
      return (
        <FieldRow
          key={field.key}
          htmlFor={domId}
          label={label}
          help={help}
          details={details}
          align="end"
          control={<ToggleControl id={domId} checked={Boolean(value)} onChange={(v) => edit(field.key, v)} />}
        />
      );
    }
    if (field.kind === 'warranty') {
      const current = (value as Record<string, string> | undefined) ?? {};
      return (
        <FieldRow
          key={field.key}
          label={label}
          help={help}
          details={details}
          control={
            <div className={styles.warranty} role="group" aria-label={label}>
              {WARRANTY_KEYS.map((entry) => (
                <Input
                  key={entry.id}
                  aria-label={t(`warranty.${entry.labelKey}`)}
                  title={t(`warranty.${entry.labelKey}`)}
                  value={current[entry.id] ?? ''}
                  onChange={(_e, d) => edit(field.key, { ...current, [entry.id]: d.value })}
                />
              ))}
            </div>
          }
        />
      );
    }
    const isNumber = field.kind === 'number' || field.kind === 'int';
    const text = field.key in draft ? String(draft[field.key] ?? '') : isNumber ? formatNumberText(typeof value === 'number' ? value : null, lang) : toText(value);
    return (
      <FieldRow
        key={field.key}
        htmlFor={domId}
        label={label}
        help={help}
        details={details}
        control={
          <Input
            id={domId}
            inputMode={isNumber ? 'decimal' : undefined}
            value={text}
            placeholder={placeholderFor(field, tSettings, lang)}
            contentAfter={<UnitText unit={field.unit} />}
            onChange={(_e, d) => edit(field.key, d.value)}
          />
        }
      />
    );
  };

  const rows: JSX.Element[] = [];
  for (const section of props.sections) {
    if (props.sections.length > 1) {
      rows.push(<FieldRow key={`h-${section}`} labelAs="h3" label={t(`subheadings.${section}`)} />);
    }
    for (const field of HOMELAB_FIELDS[section] ?? []) {
      rows.push(renderField(field));
      if (field.kind === 'hosts') {
        for (const host of originalHosts) {
          rows.push(
            <SecretField
              key={`token-${host.name}`}
              slotId={`proxmox:${host.name}`}
              label={t('hosts.tokenLabel', { name: host.name })}
              help={t('hosts.tokenHelp')}
            />,
          );
        }
      }
    }
  }
  if (props.services.length) {
    rows.push(
      <FieldRow
        key="zustand"
        label={t('check.title')}
        help={t('check.help')}
        control={
          <div className={styles.states} role="status" aria-live="polite">
            {!checked ? (
              <span className={styles.muted}>{t('check.notChecked')}</span>
            ) : check.isFetching ? (
              <Spinner size="tiny" label={t('check.running')} />
            ) : check.error ? (
              <span>{t('check.failed')}</span>
            ) : (
              matching.map((service) => <ServiceState key={service.id} service={service} />)
            )}
          </div>
        }
      />,
    );
  }

  return (
    <div id={props.id}>
      <Section
        title={props.title}
        description={props.description}
        actions={
          <div className={styles.actions}>
            {saving ? <Spinner size="tiny" /> : null}
            {dirty ? (
              <>
                <Button appearance="primary" disabled={saving} onClick={() => void save()}>
                  {tSettings('generic.save')}
                </Button>
                <Button appearance="secondary" disabled={saving} onClick={discard}>
                  {tSettings('generic.discard')}
                </Button>
              </>
            ) : null}
            {props.services.length ? (
              <Button appearance="secondary" icon={<ArrowClockwise20Regular />} disabled={check.isFetching} onClick={onCheck}>
                {t('check.action')}
              </Button>
            ) : null}
          </div>
        }
      >
        {generalError ? (
          <MessageBar intent="error">
            <MessageBarBody>{generalError}</MessageBarBody>
          </MessageBar>
        ) : null}
        <FieldRows>{rows}</FieldRows>
      </Section>
    </div>
  );
}
