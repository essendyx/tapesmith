/**
 * Wurzel der Familienseite: eigener Token-Speicher, eigener QueryClient, eigenes Theme.
 * Kein Zusammenhang mit ../../App (kein SSE, keine AppShell, kein Admin-Token, keine anderen
 * Routen als die vier Familienrouten).
 */
import { useCallback, useEffect, useState } from 'react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { Body1, Caption1, makeStyles, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { LoadingState } from '../../components/LoadingState';
import { clearFamilyToken, FamilyError, getStatus, getTemplates, initFamilyToken, setFamilyToken } from './familyClient';
import { FamilyThemeProvider } from './FamilyThemeProvider';
import { TokenGate, type GateVariant } from './TokenGate';
import { TemplateGrid } from './TemplateGrid';
import { TemplateForm } from './TemplateForm';
import type { FamilyTemplate } from './types';

const STATUS_POLL_MS = 30000;

const useStyles = makeStyles({
  root: { minHeight: '100%', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    columnGap: tokens.spacingHorizontalM,
    rowGap: tokens.spacingVerticalXS,
    padding: `${tokens.spacingVerticalM} ${tokens.spacingHorizontalL}`,
    position: 'sticky',
    top: 0,
    backgroundColor: tokens.colorNeutralBackground2,
    zIndex: 1,
  },
  title: { margin: 0, fontWeight: tokens.fontWeightSemibold, fontSize: tokens.fontSizeBase500 },
  statusRow: { display: 'flex', alignItems: 'center', columnGap: tokens.spacingHorizontalXS, minWidth: 0 },
  dot: { width: '10px', height: '10px', borderRadius: '50%', flexShrink: 0 },
  dotOn: { backgroundColor: tokens.colorPaletteGreenForeground1 },
  dotOff: { backgroundColor: tokens.colorNeutralForeground4 },
  main: { flex: 1, padding: `0 ${tokens.spacingHorizontalL} ${tokens.spacingVerticalXL}`, boxSizing: 'border-box' },
  center: { minHeight: '50vh', display: 'grid', placeItems: 'center' },
});

function currentVorlage(): string | null {
  return new URLSearchParams(window.location.search).get('vorlage');
}

function urlWith(vorlage: string | null): string {
  const url = new URL(window.location.href);
  if (vorlage) url.searchParams.set('vorlage', vorlage);
  else url.searchParams.delete('vorlage');
  return url.pathname + url.search;
}

function authErrorVariant(status: number): GateVariant | null {
  if (status === 401) return 'invalid';
  if (status === 403) return 'forbidden';
  if (status === 429) return 'ratelimited';
  return null;
}

function FamilyContent(): JSX.Element {
  const styles = useStyles();
  const { t } = useTranslation('familie');
  const [token, setToken] = useState<string | null>(() => initFamilyToken());
  const [gate, setGate] = useState<GateVariant>('invite');
  const [selected, setSelected] = useState<string | null>(() => currentVorlage());

  useEffect(() => {
    const onPop = () => setSelected(currentVorlage());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const handleAuthError = useCallback((status: number) => {
    const variant = authErrorVariant(status);
    if (!variant) return;
    if (status === 401) {
      clearFamilyToken();
      setToken(null);
    }
    setGate(variant);
  }, []);

  const templatesQuery = useQuery({
    queryKey: ['familie', 'vorlagen', token],
    queryFn: getTemplates,
    enabled: token !== null,
    retry: false,
  });
  const statusQuery = useQuery({
    queryKey: ['familie', 'status', token],
    queryFn: getStatus,
    enabled: token !== null,
    retry: false,
    refetchInterval: STATUS_POLL_MS,
  });

  useEffect(() => {
    const err = templatesQuery.error ?? statusQuery.error;
    if (err instanceof FamilyError) handleAuthError(err.status);
  }, [templatesQuery.error, statusQuery.error, handleAuthError]);

  const selectTemplate = (name: string) => {
    window.history.pushState({}, '', urlWith(name));
    setSelected(name);
  };
  const backToGrid = () => {
    window.history.pushState({}, '', urlWith(null));
    setSelected(null);
  };

  const handleTokenSubmit = (value: string) => {
    setGate('invite');
    setFamilyToken(value);
    setToken(value);
  };

  if (token === null) {
    return <TokenGate variant={gate === 'invalid' ? 'invalid' : 'invite'} onSubmit={handleTokenSubmit} />;
  }
  if (gate === 'forbidden' || gate === 'ratelimited') {
    return <TokenGate variant={gate} />;
  }

  const templates: FamilyTemplate[] = templatesQuery.data?.templates ?? [];
  const maxCopies = templatesQuery.data?.max_copies ?? 1;
  const selectedTemplate = selected ? (templates.find((t) => t.name === selected) ?? null) : null;

  const status = statusQuery.data;
  const online = status?.online ?? false;

  return (
    <div className={styles.root}>
      <div className={styles.header}>
        <Body1 as="h1" className={styles.title}>
          {t('header.title')}
        </Body1>
        <div className={styles.statusRow}>
          <span className={`${styles.dot} ${online ? styles.dotOn : styles.dotOff}`} aria-hidden="true" />
          <Caption1>
            {status?.text ?? t('status.checking')}
            {status && status.waiting > 0 ? t('status.waitingSuffix', { count: status.waiting }) : ''}
          </Caption1>
        </div>
      </div>
      <div className={styles.main}>
        {templatesQuery.isLoading ? (
          <div className={styles.center}>
            <LoadingState variant="inline" label={t('templates.loading')} />
          </div>
        ) : selectedTemplate ? (
          <TemplateForm template={selectedTemplate} maxCopies={maxCopies} onBack={backToGrid} onAuthError={handleAuthError} />
        ) : (
          <TemplateGrid templates={templates} onSelect={selectTemplate} />
        )}
      </div>
    </div>
  );
}

export default function FamilyApp(): JSX.Element {
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } }),
  );
  return (
    <QueryClientProvider client={client}>
      <FamilyThemeProvider>
        <FamilyContent />
      </FamilyThemeProvider>
    </QueryClientProvider>
  );
}
