/**
 * App-Rahmen: Sprungmarke, Seitenleiste, Kopfzeile mit Pfad, Fortschritt, Schneidpause,
 * Hinweis auf verwaiste Entwürfe und die Seite mit sanftem Einblenden.
 */
import { Suspense, useCallback, useEffect, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { makeStyles, tokens } from '@fluentui/react-components';
import { useTranslation } from 'react-i18next';
import { matchesCombo, parseCombo, useShortcut } from '../commands/shortcuts';
import { LoadingState } from '../components/LoadingState';
import { useMediaQuery } from '../components/useMediaQuery';
import { CORE_TOP_ROUTES, routeBreadcrumb, routeTitle } from '../routes';
import { setWindowTitle } from '../platform';
import { motion } from '../theme/motion';
import { CutPauseBar } from './CutPauseBar';
import { ErrorBoundary } from './ErrorBoundary';
import { JobProgressBar } from './JobProgressBar';
import { RecoveryBanner } from './RecoveryBanner';
import { Sidebar } from './Sidebar';
import { CONTENT_ID, SkipLink } from './SkipLink';
import { TopBar } from './TopBar';

export const NAV_COLLAPSED_KEY = 'p12.nav.collapsed';

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(NAV_COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
}

function writeCollapsed(value: boolean): void {
  try {
    localStorage.setItem(NAV_COLLAPSED_KEY, value ? '1' : '0');
  } catch {
    // ohne Speicher gilt der Zustand nur bis zum Neuladen
  }
}

const useStyles = makeStyles({
  shell: {
    display: 'flex',
    height: '100vh',
    width: '100%',
    overflow: 'hidden',
    backgroundColor: tokens.colorNeutralBackground2,
  },
  main: {
    flexGrow: 1,
    minWidth: 0,
    display: 'flex',
    flexDirection: 'column',
    backgroundColor: tokens.colorNeutralBackground2,
  },
  surface: {
    flexGrow: 1,
    minHeight: 0,
    display: 'flex',
    flexDirection: 'column',
    backgroundColor: tokens.colorNeutralBackground2,
  },
  content: {
    flexGrow: 1,
    minHeight: 0,
    overflowY: 'auto',
    overflowX: 'hidden',
    scrollbarGutter: 'stable',
    ':focus': { outlineStyle: 'none' },
    ':focus-visible': { outlineStyle: 'none' },
  },
  page: {
    boxSizing: 'border-box',
    maxWidth: '1320px',
    margin: '0 auto',
    padding: `${tokens.spacingVerticalXL} ${tokens.spacingHorizontalXXXL} ${tokens.spacingVerticalXXXL}`,
    ...motion.fadeIn,
    '@media (max-width: 639px)': { padding: `${tokens.spacingVerticalL} ${tokens.spacingHorizontalL}` },
  },
});

export function AppShell(): JSX.Element {
  const styles = useStyles();
  const location = useLocation();
  const navigate = useNavigate();
  const narrow = useMediaQuery('(max-width: 639px)');
  const medium = useMediaQuery('(max-width: 1023px)');
  const [userCollapsed, setUserCollapsed] = useState(readCollapsed);
  const [drawerOpen, setDrawerOpen] = useState(false);
  // useTranslation rendert bei einem Sprachwechsel neu: Titel und Pfad folgen der Sprache.
  const { t } = useTranslation('shell');
  const title = routeTitle(location.pathname);
  const crumbs = routeBreadcrumb(location.pathname);

  const collapsed = medium ? true : userCollapsed;
  const toggle = useCallback(() => {
    setUserCollapsed((prev) => {
      writeCollapsed(!prev);
      return !prev;
    });
  }, []);

  useEffect(() => {
    void setWindowTitle(t('windowTitle', { title }));
  }, [title, t]);

  useEffect(() => {
    if (!narrow) setDrawerOpen(false);
  }, [narrow]);

  useEffect(() => {
    const combos = CORE_TOP_ROUTES.slice(0, 9).map((r, i) => ({ combo: parseCombo(`Ctrl+${i + 1}`), path: r.path }));
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing || e.defaultPrevented) return;
      const hit = combos.find((c) => matchesCombo(e, c.combo));
      if (!hit) return;
      e.preventDefault();
      navigate(hit.path);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [navigate]);
  useShortcut('Ctrl+,', () => navigate('/einstellungen'), { allowInInputs: true });
  useShortcut('Ctrl+Shift+V', () => navigate('/vorlagen?import=zwischenablage'));

  return (
    <div className={styles.shell}>
      <SkipLink targetId={CONTENT_ID} />
      <Sidebar
        collapsed={collapsed}
        canToggle={!medium}
        onToggle={toggle}
        overlay={narrow}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
      />
      <div className={styles.main}>
        <TopBar crumbs={crumbs} onMenu={narrow ? () => setDrawerOpen(true) : undefined} compact={narrow} />
        <div className={styles.surface}>
          <JobProgressBar />
          <CutPauseBar />
          <RecoveryBanner />
          <main className={styles.content} id={CONTENT_ID} tabIndex={-1}>
            <ErrorBoundary resetKey={location.pathname}>
              <div className={styles.page} key={location.pathname}>
                <Suspense fallback={<LoadingState variant="page" label={t('loadingPage')} />}>
                  <Outlet />
                </Suspense>
              </div>
            </ErrorBoundary>
          </main>
        </div>
      </div>
    </div>
  );
}
