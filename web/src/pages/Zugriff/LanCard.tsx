/** Karte „LAN-Freigabe“: Freigabe fürs Heimnetz, erlaubte Netze/Hostnamen, öffentliche Adresse. */
import { Body1, Button, Field, Input, MessageBar, MessageBarBody, Switch, makeStyles, tokens } from '@fluentui/react-components';
import { Warning20Regular } from '@fluentui/react-icons';
import { Trans, useTranslation } from 'react-i18next';
import { Section } from '../../components/Section';
import { ListTextarea } from './ListTextarea';
import type { AccessJson, AccessLan } from './types';
import { useSectionEdit } from './useSectionEdit';
import { useAccessSave } from './useAccessSave';

const useStyles = makeStyles({
  grid: { display: 'flex', flexDirection: 'column', rowGap: tokens.spacingVerticalM },
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

  const onSave = async () => {
    const ok = await save(edit.changes('lan'), t('lan.saveSuccess'));
    if (ok) edit.discard();
  };

  return (
    <Section
      id="lan"
      title={t('lan.title')}
      actions={
        edit.dirty ? (
          <>
            <Button appearance="primary" disabled={saving} aria-busy={saving} onClick={() => void onSave()}>
              {t('common:actions.save')}
            </Button>
            <Button appearance="secondary" disabled={saving} onClick={edit.discard}>
              {t('common:actions.cancel')}
            </Button>
          </>
        ) : undefined
      }
    >
      <div className={styles.grid}>
        <Field label={t('lan.enableLabel')}>
          <Switch checked={v.enabled} onChange={(_e, d) => edit.set('enabled', d.checked)} />
        </Field>

        <div className={styles.status}>
          {v.active ? (
            <Body1>{t('lan.activeStatus', { listen: v.listen.join(', ') })}</Body1>
          ) : (
            <Body1>{t('lan.localOnlyStatus')}</Body1>
          )}
        </div>

        {v.restart_needed ? (
          <MessageBar intent="warning">
            <MessageBarBody>
              <Warning20Regular aria-hidden="true" /> <Trans i18nKey="zugriff:lan.restartNeeded" components={{ code: <code /> }} />
            </MessageBarBody>
          </MessageBar>
        ) : null}

        <Field label={t('lan.bindLabel')} hint={t('lan.bindHint')}>
          <Input value={v.bind} onChange={(_e, d) => edit.set('bind', d.value)} />
        </Field>

        <Field label={t('lan.networksLabel')} hint={t('lan.networksHint')}>
          <ListTextarea value={v.allowed_networks} onChange={(lines) => edit.set('allowed_networks', lines)} />
        </Field>

        <Field label={t('lan.hostnamesLabel')} hint={t('lan.hostnamesHint')}>
          <ListTextarea value={v.hostnames} onChange={(lines) => edit.set('hostnames', lines)} />
        </Field>

        <Field label={t('lan.publicUrlLabel')} hint={t('lan.publicUrlHint')}>
          <Input
            value={v.public_url ?? ''}
            onChange={(_e, d) => edit.set('public_url', d.value === '' ? null : d.value)}
          />
        </Field>

        <Body1 className={styles.wrap}>
          <Trans i18nKey="zugriff:lan.firewallHint" components={{ code: <code /> }} />
        </Body1>

        {v.base_urls.length > 0 ? (
          <Field label={t('lan.reachableLabel')}>
            <ul className={styles.urls}>
              {v.base_urls.map((u) => (
                <li key={u}>{u}</li>
              ))}
            </ul>
          </Field>
        ) : null}

        {error ? (
          <MessageBar intent="error">
            <MessageBarBody>{error}</MessageBarBody>
          </MessageBar>
        ) : null}
      </div>
    </Section>
  );
}
