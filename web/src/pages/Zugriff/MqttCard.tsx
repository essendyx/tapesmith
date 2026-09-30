/** Karte „Home Assistant (MQTT)“: Broker-Verbindung, Discovery, Passwort, erlaubte Vorlagen. */
import { useId, useState } from 'react';
import { Badge, Button, Input, MessageBar, MessageBarBody } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { FieldRow, FieldRows, ToggleControl } from '../../components/FieldRow';
import { Section } from '../../components/Section';
import { CardActions } from './CardActions';
import { NumberInput } from './NumberInput';
import { SecretDialog } from './SecretDialog';
import { TemplatePicker } from './TemplatePicker';
import type { AccessJson, AccessMqtt } from './types';
import { useSectionEdit } from './useSectionEdit';
import { useAccessSave } from './useAccessSave';

export function MqttCard(props: { data: AccessJson }): JSX.Element {
  const { t } = useTranslation('zugriff');
  const edit = useSectionEdit<AccessMqtt>(props.data.mqtt);
  const { save, saving, error } = useAccessSave();
  const [dialogOpen, setDialogOpen] = useState(false);
  const v = edit.values;
  const idBase = useId();
  const title = t('mqtt.title');
  const notSet = t('einstellungen:field.notSet');

  const onSave = async () => {
    const ok = await save(edit.changes('mqtt'), t('mqtt.saveSuccess'));
    if (ok) edit.discard();
  };

  return (
    <Section
      id="mqtt"
      title={title}
      actions={
        edit.dirty ? (
          <CardActions title={title} dirty={edit.dirty} saving={saving} onSave={() => void onSave()} onDiscard={edit.discard} />
        ) : undefined
      }
    >
      <FieldRows>
        <FieldRow
          htmlFor={`${idBase}-enabled`}
          label={t('mqtt.enableLabel')}
          help={t('mqtt.enableHint')}
          align="end"
          control={<ToggleControl id={`${idBase}-enabled`} checked={v.enabled} onChange={(on) => edit.set('enabled', on)} />}
        />
        <FieldRow
          htmlFor={`${idBase}-host`}
          label={t('mqtt.hostLabel')}
          help={t('mqtt.hostHint')}
          control={<Input id={`${idBase}-host`} value={v.host ?? ''} placeholder={notSet} onChange={(_e, d) => edit.set('host', d.value === '' ? null : d.value)} />}
        />
        <FieldRow
          htmlFor={`${idBase}-port`}
          label={t('mqtt.portLabel')}
          help={t('mqtt.portHint')}
          control={
            <NumberInput id={`${idBase}-port`} value={v.port} min={1} max={65535} integer onChange={(n) => edit.set('port', n)} />
          }
        />
        <FieldRow
          htmlFor={`${idBase}-tls`}
          label={t('mqtt.tlsLabel')}
          help={t('mqtt.tlsHint')}
          align="end"
          control={<ToggleControl id={`${idBase}-tls`} checked={v.tls} onChange={(on) => edit.set('tls', on)} />}
        />
        <FieldRow
          htmlFor={`${idBase}-user`}
          label={t('mqtt.userLabel')}
          help={t('mqtt.userHint')}
          control={
            <Input
              id={`${idBase}-user`}
              value={v.username ?? ''}
              placeholder={notSet}
              onChange={(_e, d) => edit.set('username', d.value === '' ? null : d.value)}
            />
          }
        />
        <FieldRow
          label={t('mqtt.passwordLabel')}
          badges={
            <Badge appearance="tint" size="small" color={v.password_set ? 'success' : 'warning'}>
              {v.password_set ? t('mqtt.passwordSet') : t('mqtt.passwordMissing')}
            </Badge>
          }
          help={t('secret.storage', { source: v.password_describe })}
          control={
            <Button appearance="secondary" onClick={() => setDialogOpen(true)}>
              {t('mqtt.setPassword')}
            </Button>
          }
        />
        <FieldRow
          htmlFor={`${idBase}-topic`}
          label={t('mqtt.baseTopicLabel')}
          help={t('mqtt.baseTopicHint')}
          control={
            <Input
              id={`${idBase}-topic`}
              value={v.base_topic}
              title={v.base_topic || undefined}
              placeholder={t('einstellungen:field.defaultValue', { value: 'tapesmith' })}
              onChange={(_e, d) => edit.set('base_topic', d.value)}
            />
          }
        />
        <FieldRow
          htmlFor={`${idBase}-discovery`}
          label={t('mqtt.discoveryLabel')}
          help={t('mqtt.discoveryHint')}
          control={
            <Input
              id={`${idBase}-discovery`}
              value={v.discovery_prefix}
              title={v.discovery_prefix || undefined}
              placeholder={t('einstellungen:field.defaultValue', { value: 'homeassistant' })}
              onChange={(_e, d) => edit.set('discovery_prefix', d.value)}
            />
          }
        />
        <TemplatePicker
          label={t('mqtt.templatesLabel')}
          help={t('mqtt.templatesHint')}
          available={props.data.family.available}
          saved={props.data.mqtt.templates}
          value={v.templates}
          emptyCount={t('mqtt.templatesAll')}
          onChange={(templates) => edit.set('templates', templates)}
        />
      </FieldRows>
      {error ? (
        <MessageBar intent="error">
          <MessageBarBody>{error}</MessageBarBody>
        </MessageBar>
      ) : null}
      <SecretDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        name="mqtt"
        title={t('mqtt.secretDialogTitle')}
        fieldLabel={t('mqtt.secretFieldLabel')}
      />
    </Section>
  );
}
