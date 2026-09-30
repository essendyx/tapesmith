/** Karte „LAN-Freigabe“: Freigabe fürs Heimnetz, erlaubte Netze/Hostnamen, öffentliche Adresse. */
import { useId } from 'react';
import { Input, MessageBar, MessageBarBody, makeStyles, tokens } from '@fluentui/react-components';
import { Warning20Regular } from '@fluentui/react-icons';
import { Trans, useTranslation } from 'react-i18next';
import { FieldRow, FieldRows, ToggleControl } from '../../components/FieldRow';
import { Section } from '../../components/Section';
import { CardActions } from './CardActions';
import { ListTextarea } from './ListTextarea';
import type { AccessJson, AccessLan } from './types';
import { useSectionEdit } from './useSectionEdit';
import { useAccessSave } from './useAccessSave';

const useStyles = makeStyles({
  // Lange Befehle und Adressen in <code> umbrechen statt die Karte auf dem Handy zu sprengen.
  wrap: { overflowWrap: 'anywhere' },
  status: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalXXS },
  urls: { margin: 0, paddingLeft: tokens.spacingHorizontalXL },
});

export function LanCard(props: { data: AccessJson }): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('zugriff');
  const edit = useSectionEdit<AccessLan>(props.data.lan);
  const { save, saving, error } = useAccessSave();
  const v = edit.values;
  const idBase = useId();
  const title = t('lan.title');

  const onSave = async () => {
    const ok = await save(edit.changes('lan'), t('lan.saveSuccess'));
    if (ok) edit.discard();
  };

  return (
    <Section
      id="lan"
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
          label={t('lan.enableLabel')}
          help={v.active ? t('lan.activeStatus', { listen: v.listen.join(', ') }) : t('lan.localOnlyStatus')}
          align="end"
          control={<ToggleControl id={`${idBase}-enabled`} checked={v.enabled} onChange={(on) => edit.set('enabled', on)} />}
        />
        {v.restart_needed ? (
          <MessageBar intent="warning">
            <MessageBarBody>
              <Warning20Regular aria-hidden="true" /> <Trans i18nKey="zugriff:lan.restartNeeded" components={{ code: <code /> }} />
            </MessageBarBody>
          </MessageBar>
        ) : null}
        <FieldRow
          htmlFor={`${idBase}-bind`}
          label={t('lan.bindLabel')}
          help={t('lan.bindHint')}
          control={<Input id={`${idBase}-bind`} value={v.bind} onChange={(_e, d) => edit.set('bind', d.value)} />}
        />
        <FieldRow
          htmlFor={`${idBase}-networks`}
          label={t('lan.networksLabel')}
          help={t('lan.networksHint')}
          control={
            <ListTextarea id={`${idBase}-networks`} value={v.allowed_networks} onChange={(lines) => edit.set('allowed_networks', lines)} />
          }
        />
        <FieldRow
          htmlFor={`${idBase}-hosts`}
          label={t('lan.hostnamesLabel')}
          help={t('lan.hostnamesHint')}
          control={<ListTextarea id={`${idBase}-hosts`} value={v.hostnames} onChange={(lines) => edit.set('hostnames', lines)} />}
        />
        <FieldRow
          htmlFor={`${idBase}-public`}
          label={t('lan.publicUrlLabel')}
          help={t('lan.publicUrlHint')}
          control={
            <Input
              id={`${idBase}-public`}
              value={v.public_url ?? ''}
              onChange={(_e, d) => edit.set('public_url', d.value === '' ? null : d.value)}
            />
          }
        />
        <FieldRow
          label={v.base_urls.length > 0 ? t('lan.reachableLabel') : t('lan.firewallTitle')}
          help={
            <span className={styles.wrap}>
              <Trans i18nKey="zugriff:lan.firewallHint" components={{ code: <code /> }} />
            </span>
          }
          details={
            v.base_urls.length > 0 ? (
              <ul className={styles.urls}>
                {v.base_urls.map((u) => (
                  <li key={u}>{u}</li>
                ))}
              </ul>
            ) : undefined
          }
        />
      </FieldRows>
      {error ? (
        <MessageBar intent="error">
          <MessageBarBody>{error}</MessageBarBody>
        </MessageBar>
      ) : null}
    </Section>
  );
}
