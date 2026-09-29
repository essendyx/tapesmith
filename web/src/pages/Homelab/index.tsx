/**
 * Seite Homelab: Übersicht der eingeschalteten Integrationsmodule (Hub) und ihre Seiten als
 * Unterseiten unter /homelab/<unterseite>. Ausgeschaltete Module zeigen nur einen Hinweis.
 * Frühere Adressen leiten weiter: /homelab/einstellungen zu Einstellungen > Module,
 * /homelab/plattentausch zum Reiter Plattentausch der Seite Datenträger.
 */
import { Suspense, lazy, type ComponentType, type LazyExoticComponent, type ReactNode } from 'react';
import { Link, Navigate, Route, Routes } from 'react-router-dom';
import { Spinner, makeStyles, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { HOMELAB_MODULES, moduleTexts } from '../../modules';
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
  // Nachbildung des Pfads aus PageHeader: eigener, kleiner Rahmen, weil die
  // Unterseiten hier nur eingehängt werden und ihre eigene PageHeader-Instanz unberührt bleibt.
  breadcrumb: {
    display: 'block',
    marginBottom: tokens.spacingVerticalM,
    color: tokens.colorNeutralForeground3,
    fontSize: tokens.fontSizeBase200,
    lineHeight: tokens.lineHeightBase200,
  },
  breadcrumbLink: {
    color: 'inherit',
    ':hover': { color: tokens.colorBrandForegroundLinkHover },
  },
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
  const styles = useStyles();
  const { t } = useTranslation('homelab');
  const Page = props.page;
  return (
    <>
      <nav aria-label={t('breadcrumbAriaLabel')} className={styles.breadcrumb}>
        <Link to="/homelab" className={styles.breadcrumbLink}>
          {t('title')}
        </Link>
        {' › '}
        {moduleTexts(props.module).name}
      </nav>
      <ModuleGate module={props.module}>
        <ModuleSetupGate module={props.module}>
          <Lazy>
            <Page />
          </Lazy>
        </ModuleSetupGate>
      </ModuleGate>
    </>
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
