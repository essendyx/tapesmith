/**
 * Seite eines Integrationsmoduls, das einen eingerichteten Dienst braucht (`setup` im Register): ist
 * der Dienst laut `/homelab/check` (ohne Netzzugriff) nicht eingetragen, zeigt die Seite nur den
 * Erklärsatz und den Weg zu den Einstellungen, statt Anfragen zu stellen, die scheitern müssen.
 */
import type { ReactNode } from 'react';
import { PlugDisconnected24Regular } from '@fluentui/react-icons';
import { useTranslation } from 'react-i18next';
import { EmptyState } from '../components/EmptyState';
import { LoadingState } from '../components/LoadingState';
import { PageHeader } from '../components/PageHeader';
import { useHomelabCheck } from '../pages/HomelabEinstellungen/api';
import { moduleDef, moduleTexts } from './index';
import { ModuleSettingsButton } from './ModuleSettingsButton';

export function ModuleSetupGate(props: { module: string; children: ReactNode }): JSX.Element {
  const { t } = useTranslation('modules');
  const def = moduleDef(props.module);
  const needsSetup = Boolean(def?.setup && def.integrations.length);
  const check = useHomelabCheck({ enabled: needsSetup });
  if (!needsSetup || !def) return <>{props.children}</>;
  if (check.isLoading) return <LoadingState variant="page" />;
  // Prüfung nicht möglich: die Seite selbst meldet, was fehlt.
  if (check.error || !check.data) return <>{props.children}</>;
  const services = check.data.services.filter((s) => def.integrations.some((id) => s.id === id || s.id.startsWith(`${id}:`)));
  if (services.some((s) => s.configured)) return <>{props.children}</>;
  const texts = moduleTexts(props.module);
  return (
    <>
      <PageHeader title={texts.name} subtitle={texts.description} />
      <EmptyState
        icon={<PlugDisconnected24Regular />}
        title={t('setup.title', { name: texts.name })}
        body={texts.requires ? t('setup.bodyRequires', { requires: texts.requires }) : t('setup.body')}
        action={<ModuleSettingsButton module={props.module} />}
      />
    </>
  );
}
