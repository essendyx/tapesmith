/**
 * Seite Homelab: Übersicht der eingeschalteten Integrationsmodule (Hub) und ihre Seiten als
 * Unterseiten unter /homelab/<unterseite>. Ausgeschaltete Module zeigen nur einen Hinweis. Den Pfad
 * „Homelab › Modul“ zeigt allein die Kopfzeile (`TopBar`, mit Link zurück zur Übersicht); die
 * Unterseite wiederholt ihn nicht über ihrem Titel.
 * Frühere Adressen leiten weiter: /homelab/einstellungen zu Einstellungen > Module,
 * /homelab/plattentausch zum Reiter Plattentausch der Seite Datenträger.
 */
import { Suspense, lazy, type ComponentType, type LazyExoticComponent, type ReactNode } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { Spinner, makeStyles } from '@fluentui/react-components';
import { HOMELAB_MODULES } from '../../modules';
import { MODULES_SETTINGS_PATH, ModuleGate } from '../../modules/ModuleGate';
import { ModuleSetupGate } from '../../modules/ModuleSetupGate';
import { HomelabHub } from './HomelabHub';

const SUBPAGES: Record<string, LazyExoticComponent<ComponentType>> = {
  proxmox: lazy(() => import('../Proxmox')),
  paperless: lazy(() => import('../Paperless')),
  vault: lazy(() => import('../Vault')),
  assets: lazy(() => import('../Assets')),
  kleinanzeigen: lazy(() => import('../Kleinanzeigen')),
  kabel: lazy(() => import('../Kabel')),
  batterien: lazy(() => import('../Batterien')),
  'sn-scan': lazy(() => import('../SnScan')),
};

const useStyles = makeStyles({
  loading: { display: 'grid', placeItems: 'center', height: '100%', minHeight: '200px' },
});

function Lazy(props: { children: ReactNode }): JSX.Element {
  const styles = useStyles();
  return (
    <Suspense
      fallback={
        <div className={styles.loading}>
          <Spinner />
        </div>
      }
    >
      {props.children}
    </Suspense>
  );
}

function Subpage(props: { page: LazyExoticComponent<ComponentType>; module: string }): JSX.Element {
  const Page = props.page;
  return (
    <ModuleGate module={props.module}>
      <ModuleSetupGate module={props.module}>
        <Lazy>
          <Page />
        </Lazy>
      </ModuleSetupGate>
    </ModuleGate>
  );
}

export default function HomelabPage(): JSX.Element {
  return (
    <Routes>
      <Route index element={<HomelabHub />} />
      {HOMELAB_MODULES.map((m) => {
        const page = SUBPAGES[m.nav.key];
        return page ? <Route key={m.id} path={`${m.nav.key}/*`} element={<Subpage page={page} module={m.id} />} /> : null;
      })}
      <Route path="einstellungen" element={<Navigate to={MODULES_SETTINGS_PATH} replace />} />
      <Route path="plattentausch" element={<Navigate to="/datentraeger?tab=plattentausch" replace />} />
      <Route path="*" element={<Navigate to="/homelab" replace />} />
    </Routes>
  );
}
