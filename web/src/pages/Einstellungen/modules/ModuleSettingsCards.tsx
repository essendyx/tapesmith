/**
 * Einstellungskarten der eingeschalteten Module, eine Karte je Modul (Reihenfolge wie im Register).
 * Karten aus config.json (`config:<abschnitt>`) kommen aus dem Server-Schema, Karten aus homelab.json
 * (`homelab:<abschnitt>`) aus `HomelabSettingsCard`.
 */
import { MessageBar, MessageBarBody, MessageBarTitle } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/client';
import type { SettingsSection } from '../../../api/types';
import { moduleTexts, type ModulesState } from '../../../modules';
import { moduleCardId, modulesWithSettings } from '../sectionIds';
import { useHomelabSettings } from '../../HomelabEinstellungen/api';
import { GenericSectionCard } from '../GenericSectionCard';
import { HomelabSettingsCard } from './HomelabSettingsCard';

export function ModuleSettingsCards(props: { modules: ModulesState; sections: SettingsSection[]; searchTerm?: string }): JSX.Element | null {
  const { t } = useTranslation('homelabEinstellungen');
  const list = modulesWithSettings(props.modules);
  const needsHomelab = list.some((m) => m.settings.some((s) => s.startsWith('homelab:')));
  const homelab = useHomelabSettings({ enabled: needsHomelab });
  if (!list.length) return null;
  const error = homelab.error;
  return (
    <>
      {error ? (
        <MessageBar intent="error">
          <MessageBarBody>
            <MessageBarTitle>{t('settingsUnreadable')}</MessageBarTitle>
            {error instanceof ApiError ? `${error.message}${error.hint ? ` ${error.hint}` : ''}` : String(error)}
          </MessageBarBody>
        </MessageBar>
      ) : null}
      {list.map((m) => {
        const texts = moduleTexts(m.id);
        const configSections = m.settings.filter((s) => s.startsWith('config:')).map((s) => s.slice('config:'.length));
        const homelabSections = m.settings.filter((s) => s.startsWith('homelab:')).map((s) => s.slice('homelab:'.length));
        if (configSections.length) {
          const section = props.sections.find((s) => s.id === configSections[0]);
          if (!section) return null;
          return (
            <GenericSectionCard
              key={m.id}
              section={section}
              searchTerm={props.searchTerm}
              domId={moduleCardId(m.id)}
              titleOverride={texts.name}
              description={texts.requires}
            />
          );
        }
        return (
          <HomelabSettingsCard
            key={m.id}
            id={moduleCardId(m.id)}
            title={texts.name}
            description={texts.requires}
            sections={homelabSections}
            services={m.integrations}
            settings={homelab.data?.settings}
          />
        );
      })}
    </>
  );
}
