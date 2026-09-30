/** Übersicht der eingeschalteten Integrationsmodule: eine Kachel je Modul mit Zustand aus /homelab/check. */
import type { ReactElement } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
  Badge,
  Button,
  Caption1,
  Card,
  CardHeader,
  Text,
  makeStyles,
  tokens,
  type BadgeProps,
} from '@fluentui/react-components';
import {
  Battery1024Regular,
  Cart24Regular,
  CheckmarkCircle16Filled,
  DocumentText24Regular,
  ErrorCircle16Filled,
  Notebook24Regular,
  PlugConnected24Regular,
  PuzzlePiece20Regular,
  PuzzlePiece24Regular,
  ScanCamera24Regular,
  Server24Regular,
  Tag24Regular,
  Warning16Filled,
} from '@fluentui/react-icons';
import { PageHeader } from '../../components/PageHeader';
import { EmptyState } from '../../components/EmptyState';
import { ErrorMessage } from '../../components/ErrorMessage';
import { useHomelabCheck } from '../HomelabEinstellungen/api';
import type { ServiceCheckJson } from '../HomelabEinstellungen/types';
import { HOMELAB_MODULES, moduleTexts, useModules, type ModuleDef } from '../../modules';
import { MODULES_SETTINGS_PATH } from '../../modules/ModuleGate';

const TILE_ICONS: Record<string, ReactElement> = {
  proxmox: <Server24Regular />,
  paperless: <DocumentText24Regular />,
  vault: <Notebook24Regular />,
  assets: <Tag24Regular />,
  kleinanzeigen: <Cart24Regular />,
  kabel: <PlugConnected24Regular />,
  homeassistant: <Battery1024Regular />,
  snscan: <ScanCamera24Regular />,
};

type TileState = { text: string; color: NonNullable<BadgeProps['color']>; icon?: ReactElement };

/** Zustand einer Kachel aus den Prüfergebnissen (Proxmox: alle Hosts `proxmox:<name>`). */
function tileState(module: ModuleDef, services: ServiceCheckJson[] | undefined, t: (key: string) => string): TileState | null {
  const service = module.integrations[0];
  if (service === undefined) return { text: t('state.noService'), color: 'subtle' };
  if (!services) return null;
  const matches = services.filter((s) => s.id === service || s.id.startsWith(`${service}:`));
  const configured = matches.filter((s) => s.configured);
  if (!configured.length) return { text: t('state.notConfigured'), color: 'warning', icon: <Warning16Filled /> };
  if (configured.some((s) => s.token_set === false)) return { text: t('state.tokenMissing'), color: 'danger', icon: <ErrorCircle16Filled /> };
  return { text: t('state.configured'), color: 'success', icon: <CheckmarkCircle16Filled /> };
}

const useStyles = makeStyles({
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
    gap: tokens.spacingHorizontalL,
    '@media (max-width: 480px)': { gridTemplateColumns: '1fr' },
  },
  link: {
    textDecorationLine: 'none',
    color: 'inherit',
    display: 'block',
    borderRadius: tokens.borderRadiusMedium,
    ':focus-visible': { outline: `2px solid ${tokens.colorStrokeFocus2}`, outlineOffset: '2px' },
  },
  card: { height: '100%', rowGap: tokens.spacingVerticalS },
  icon: { color: tokens.colorBrandForeground1, fontSize: '24px', display: 'flex' },
  description: { color: tokens.colorNeutralForeground2 },
  // Zustands-Plakette nie umbrechen (Englisch „no service needed“ lief sonst aus der Pille).
  badge: { whiteSpace: 'nowrap', flexShrink: 0 },
  // Zustand unter dem Namen statt daneben: lange Namen brechen so nicht um.
  state: { display: 'block', marginTop: tokens.spacingVerticalXXS },
});

export function HomelabHub(): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('homelab');
  const navigate = useNavigate();
  const modules = useModules();
  const enabled = HOMELAB_MODULES.filter((m) => modules.isEnabled(m.id));
  const check = useHomelabCheck({ enabled: enabled.some((m) => m.integrations.length > 0) });
  const services = check.data?.services;
  const manage = (
    <Button appearance="secondary" icon={<PuzzlePiece20Regular />} onClick={() => navigate(MODULES_SETTINGS_PATH)}>
      {t('manage')}
    </Button>
  );
  return (
    <>
      <PageHeader title={t('title')} subtitle={t('subtitle')} actions={enabled.length ? manage : undefined} />
      {check.error ? <ErrorMessage error={check.error} title={t('checkErrorTitle')} /> : null}
      {modules.loaded && enabled.length === 0 ? (
        <EmptyState
          icon={<PuzzlePiece24Regular />}
          title={t('empty.title')}
          body={t('empty.body')}
          action={
            <Button appearance="primary" onClick={() => navigate(MODULES_SETTINGS_PATH)}>
              {t('empty.action')}
            </Button>
          }
        />
      ) : (
        <nav aria-label={t('navAriaLabel')} className={styles.grid}>
          {enabled.map((m) => {
            const state = tileState(m, services, t);
            const texts = moduleTexts(m.id);
            return (
              <Link key={m.id} to={`/homelab/${m.nav.key}`} aria-label={texts.name} className={styles.link}>
                <Card className={styles.card}>
                  <CardHeader
                    image={<span className={styles.icon}>{TILE_ICONS[m.id]}</span>}
                    header={<Text weight="semibold">{texts.name}</Text>}
                    description={
                      state ? (
                        <span className={styles.state}>
                          <Badge appearance="tint" color={state.color} icon={state.icon} className={styles.badge}>
                            {state.text}
                          </Badge>
                        </span>
                      ) : undefined
                    }
                  />
                  <Caption1 className={styles.description}>{texts.description}</Caption1>
                </Card>
              </Link>
            );
          })}
        </nav>
      )}
    </>
  );
}
