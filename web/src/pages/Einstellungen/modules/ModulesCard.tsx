/**
 * Karte „Module“: je Modul ein Schalter mit Erklärsatz und Beispiel. Einschalten wirkt ohne Neustart:
 * der Dienst liest config.json bei jeder Anfrage, die Oberfläche lädt `AppInfo` neu und aktualisiert
 * Seitenleiste, Befehlspalette und Galerie.
 */
import { useState } from 'react';
import { Caption1, makeStyles, tokens } from '@fluentui/react-components';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Section } from '../../../components/Section';
import { useNotify } from '../../../components/NotifyProvider';
import { qk } from '../../../api/core';
import { MODULES, moduleTexts, useModules, type ModuleDef } from '../../../modules';
import { putModule } from '../../../modules/api';
import { FieldRow, FieldRows, ToggleControl } from '../../../components/FieldRow';
import { MODULES_CARD_ID } from '../sectionIds';

const useStyles = makeStyles({
  example: { color: tokens.colorNeutralForeground3 },
});

function ModuleRow(props: { module: ModuleDef; checked: boolean; busy: boolean; onChange: (on: boolean) => void }): JSX.Element {
  const { t } = useTranslation('modules');
  const styles = useStyles();
  const texts = moduleTexts(props.module.id);
  const id = `modul-schalter-${props.module.id}`;
  return (
    <FieldRow
      htmlFor={id}
      label={texts.name}
      help={texts.description}
      details={
        <>
          <Caption1 className={styles.example}>{texts.example}</Caption1>
          {texts.requires ? <Caption1 className={styles.example}>{t('card.requires', { text: texts.requires })}</Caption1> : null}
        </>
      }
      align="end"
      control={<ToggleControl id={id} checked={props.checked} disabled={props.busy} onChange={props.onChange} />}
    />
  );
}

export function ModulesCard(): JSX.Element {
  const { t } = useTranslation('modules');
  const client = useQueryClient();
  const notify = useNotify();
  const modules = useModules();
  const [busy, setBusy] = useState<string | null>(null);

  const onChange = async (module: ModuleDef, enabled: boolean) => {
    setBusy(module.id);
    const name = moduleTexts(module.id).name;
    try {
      const result = await putModule(module.id, enabled);
      client.setQueryData(qk.modules, result);
      await client.invalidateQueries({ queryKey: qk.app });
      for (const key of [qk.settings, qk.templates, qk.gallery, ['homelab']]) void client.invalidateQueries({ queryKey: key });
      notify(
        enabled
          ? {
              intent: 'success',
              title: t('card.switchedOn', { name }),
              body: module.nav.area === 'homelab' ? t('card.switchedOnHomelab') : t('card.switchedOnBody'),
            }
          : { intent: 'info', title: t('card.switchedOff', { name }) },
      );
    } catch (err) {
      notify({ intent: 'error', title: t('card.failed'), body: err instanceof Error ? err.message : String(err) });
    } finally {
      setBusy(null);
    }
  };

  const tools = MODULES.filter((m) => m.kind === 'werkzeug');
  const integrations = MODULES.filter((m) => m.kind === 'integration');
  const rows = (list: readonly ModuleDef[]) =>
    list.map((m) => (
      <ModuleRow
        key={m.id}
        module={m}
        checked={modules.isEnabled(m.id)}
        busy={busy !== null || !modules.loaded}
        onChange={(on) => void onChange(m, on)}
      />
    ));

  return (
    <div id={MODULES_CARD_ID}>
      <Section title={t('card.title')} description={t('card.description')}>
        <FieldRows>
          <FieldRow labelAs="h3" label={t('card.groupTools')} />
          {rows(tools)}
          <FieldRow labelAs="h3" label={t('card.groupIntegrations')} />
          {rows(integrations)}
        </FieldRows>
      </Section>
    </div>
  );
}
