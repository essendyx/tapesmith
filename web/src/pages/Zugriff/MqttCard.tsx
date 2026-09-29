/** Karte „Home Assistant (MQTT)“: Broker-Verbindung, Discovery, Passwort. */
import { useState } from 'react';
import { Body1, Body1Strong, Button, Checkbox, Field, Input, MessageBar, MessageBarBody, SpinButton, Switch, makeStyles, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { Section } from '../../components/Section';
import { SecretDialog } from './SecretDialog';
import type { AccessJson, AccessMqtt } from './types';
import { useSectionEdit } from './useSectionEdit';
import { useAccessSave } from './useAccessSave';

const useStyles = makeStyles({
  grid: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
  // Eigene Gruppe statt Fluent-`Field`: mehrere Kontrollkästchen dürfen nicht dieselbe generierte
  // Kennung teilen (jedes Kästchen trägt seine eigene sichtbare Beschriftung).
  group: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXS },
  checks: { display: 'flex', flexDirection: 'column' },
  row: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalS, flexWrap: 'wrap', rowGap: tokens.spacingVerticalXS },
  // Lange Pfade (Secret-Referenzen) umbrechen statt die Karte auf dem Handy zu sprengen.
  wrap: { overflowWrap: 'anywhere', minWidth: 0 },
});

function toggleTemplate(templates: string[], name: string, checked: boolean): string[] {
  if (checked) return templates.includes(name) ? templates : [...templates, name];
  return templates.filter((t) => t !== name);
}

export function MqttCard(props: { data: AccessJson }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('zugriff');
  const edit = useSectionEdit<AccessMqtt>(props.data.mqtt);
  const { save, saving, error } = useAccessSave();
  const [dialogOpen, setDialogOpen] = useState(false);
  const v = edit.values;
  const secretDialogTitle = t('mqtt.secretDialogTitle');

  const onSave = async () => {
    const ok = await save(edit.changes('mqtt'), t('mqtt.saveSuccess'));
    if (ok) edit.discard();
  };

  return (
    <Section
      id="mqtt"
      title={t('mqtt.title')}
      actions={
        edit.dirty ? (
          <>
            <Button appearance="secondary" disabled={saving} onClick={edit.discard}>
              {t('common:actions.cancel')}
            </Button>
            <Button appearance="primary" disabled={saving} aria-busy={saving} onClick={() => void onSave()}>
              {t('common:actions.save')}
            </Button>
          </>
        ) : undefined
      }
    >
      <div className={styles.grid}>
        <Field label={t('mqtt.enableLabel')}>
          <Switch checked={v.enabled} onChange={(_e, d) => edit.set('enabled', d.checked)} />
        </Field>
        <Field label={t('mqtt.hostLabel')}>
          <Input value={v.host} onChange={(_e, d) => edit.set('host', d.value)} />
        </Field>
        <Field label={t('mqtt.portLabel')}>
          <SpinButton
            value={v.port}
            min={1}
            max={65535}
            onChange={(_e, d) => {
              const n = d.value ?? (d.displayValue ? Number(d.displayValue) : null);
              if (n !== null && Number.isFinite(n)) edit.set('port', Math.min(65535, Math.max(1, Math.round(n))));
            }}
          />
        </Field>
        <Field label={t('mqtt.userLabel')}>
          <Input value={v.username ?? ''} onChange={(_e, d) => edit.set('username', d.value === '' ? null : d.value)} />
        </Field>
        <Field label={t('mqtt.baseTopicLabel')}>
          <Input value={v.base_topic} onChange={(_e, d) => edit.set('base_topic', d.value)} />
        </Field>
        <Field label={t('mqtt.discoveryLabel')}>
          <Input value={v.discovery_prefix} onChange={(_e, d) => edit.set('discovery_prefix', d.value)} />
        </Field>
        <Field label={t('mqtt.tlsLabel')}>
          <Switch checked={v.tls} onChange={(_e, d) => edit.set('tls', d.checked)} />
        </Field>

        <div className={styles.group}>
          <Body1Strong>{t('mqtt.templatesLabel')}</Body1Strong>
          <Body1>{t('mqtt.templatesHint')}</Body1>
          <div className={styles.checks}>
            {props.data.family.available.map((a) => (
              <Checkbox
                key={a.name}
                label={a.description ? `${a.name} (${a.description})` : a.name}
                checked={v.templates.includes(a.name)}
                onChange={(_e, d) => edit.set('templates', toggleTemplate(v.templates, a.name, Boolean(d.checked)))}
              />
            ))}
          </div>
        </div>

        <Field label={t('mqtt.passwordLabel')}>
          <div className={styles.row}>
            <Body1 className={styles.wrap}>
              {v.password_set ? t('mqtt.passwordSet') : t('mqtt.passwordMissing')} ({v.password_describe})
            </Body1>
            <Button appearance="secondary" onClick={() => setDialogOpen(true)}>
              {t('mqtt.setPassword')}
            </Button>
          </div>
        </Field>

        {error ? (
          <MessageBar intent="error">
            <MessageBarBody>{error}</MessageBarBody>
          </MessageBar>
        ) : null}
      </div>
      <SecretDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        name="mqtt"
        title={secretDialogTitle}
        fieldLabel={t('mqtt.secretFieldLabel')}
      />
    </Section>
  );
}
