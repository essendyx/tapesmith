/** Wurzel der Oberfläche: Provider, Token-/Dienst-Prüfung, Routen. */
import { Suspense, useCallback, useEffect, useRef, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { ApiError, getToken } from './api/client';
import { useAppInfo } from './api/core';
import { ServerEventsProvider, useEventsConnected } from './api/events';
import { CommandProvider } from './commands/CommandProvider';
import { ConfirmProvider } from './components/ConfirmProvider';
import { LoadingState } from './components/LoadingState';
import { NotifyProvider } from './components/NotifyProvider';
import { AKTION_ELEMENT, KOMPAKT_ELEMENT, ROUTES } from './routes';
import { ModuleGate } from './modules/ModuleGate';
import { AppShell } from './shell/AppShell';
import { ErrorBoundary } from './shell/ErrorBoundary';
import { NoTokenScreen, OfflineScreen } from './shell/NoTokenScreen';
import { ThemeProvider } from './theme/ThemeProvider';
import { useLanguageSync } from './i18n';

export function makeQueryClient(opts?: { retry?: boolean }): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: opts?.retry === false ? false : (count, err) => !(err instanceof ApiError && err.status > 0 && err.status < 500) && count < 2,
        refetchOnWindowFocus: false,
        staleTime: 5_000,
      },
      mutations: { retry: false },
    },
  });
}

/**
 * Folgt der Einstellung `app.language` aus `AppInfo` (Wechsel ohne Neustart), bei "auto" der vom
 * Dienst gemeldeten Systemsprache. Nach einem Wechsel lädt sie alle Daten neu, denn der Dienst
 * liefert Texte (Warnungen, Status, Vorlagen) in der Sprache der Anfrage.
 */
function LanguageSync(): null {
  const app = useAppInfo();
  const queryClient = useQueryClient();
  const { i18n } = useTranslation();
  useLanguageSync(app.data?.language, app.data?.resolved_language ?? null);
  const language = i18n.language;
  const previous = useRef(language);
  useEffect(() => {
    if (previous.current === language) return;
    previous.current = language;
    void queryClient.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'app' });
  }, [language, queryClient]);
  return null;
}


/** Alle Provider unterhalb des Routers (Router kommt von außen: Browser oder Test). */
export function AppProviders(props: { queryClient: QueryClient; children: ReactNode }): JSX.Element {
  return (
    <QueryClientProvider client={props.queryClient}>
      <LanguageSync />
      <ThemeProvider>
        <ServerEventsProvider>
          <NotifyProvider>
            <ConfirmProvider>
              <CommandProvider>{props.children}</CommandProvider>
            </ConfirmProvider>
          </NotifyProvider>
        </ServerEventsProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

/**
 * Zeigt statt der Seiten eine Hinweiskarte, wenn der Dienst fehlt oder die Sitzung nicht mehr gilt.
 * Auch mit schon geladenen Daten: bricht der Ereignis-Strom ab, prüft `ServerEventsProvider` die
 * App-Info neu. 401 heißt dann neuer Dienst mit neuem Token, Status 0 ohne Strom heißt Dienst weg.
 */
function ServiceGate(props: { children: ReactNode }): JSX.Element {
  const app = useAppInfo();
  const connected = useEventsConnected();
  const { refetch } = app;
  const retry = useCallback(() => {
    void refetch();
  }, [refetch]);
  const err = app.error;
  if (err instanceof ApiError) {
    if (err.status === 401) return <NoTokenScreen expired />;
    if (err.status === 0 && (!app.data || !connected)) return <OfflineScreen onRetry={retry} retrying={app.isFetching} />;
  }
  return <>{props.children}</>;
}

function Lazy(props: { children: ReactNode }): JSX.Element {
  return (
    <Suspense fallback={<LoadingState variant="page" />}>
      {props.children}
    </Suspense>
  );
}

/** Routen samt Prüfung auf Token und erreichbaren Dienst. */
export function AppContent(): JSX.Element {
  if (!getToken()) return <NoTokenScreen />;
  return (
    <ErrorBoundary>
      <ServiceGate>
        <Routes>
          <Route
            path="/kompakt"
            element={
              <Lazy>
                <KOMPAKT_ELEMENT />
              </Lazy>
            }
          />
          <Route element={<AppShell />}>
            <Route index element={<Navigate to="/schnelldruck" replace />} />
            {ROUTES.map((r) => (
              <Route
                key={r.key}
                path={`${r.path}/*`}
                element={
                  r.module ? (
                    <ModuleGate module={r.module}>
                      <r.element />
                    </ModuleGate>
                  ) : (
                    <r.element />
                  )
                }
              />
            ))}
            <Route path="/aktion" element={<AKTION_ELEMENT />} />
            <Route path="*" element={<Navigate to="/schnelldruck" replace />} />
          </Route>
        </Routes>
      </ServiceGate>
    </ErrorBoundary>
  );
}

const queryClient = makeQueryClient();

export default function App(): JSX.Element {
  return (
    <BrowserRouter>
      <AppProviders queryClient={queryClient}>
        <AppContent />
      </AppProviders>
    </BrowserRouter>
  );
}
