/**
 * Rückfrage beim Verlassen der Seite, solange ungespeicherte Änderungen vorliegen.
 *
 * Die App nutzt `BrowserRouter` (kein Daten-Router), daher steht `useBlocker` nicht zur Verfügung.
 * Stattdessen werden `push`/`replace` des Router-Navigators umhüllt (erfasst Seitenleiste, Tastenkürzel
 * und alle `navigate()`-Aufrufe) und zusätzlich `beforeunload` für das Schließen oder Neuladen des Fensters gesetzt.
 */
import { useContext, useEffect, useRef } from 'react';
import { UNSAFE_NavigationContext, useLocation, type To } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useConfirm } from '../../components/ConfirmProvider';

type NavFn = (to: To, ...rest: unknown[]) => void;

function targetPath(to: To): string | undefined {
  return typeof to === 'string' ? to.split(/[?#]/)[0] : to.pathname;
}

export function useLeaveGuard(active: boolean): void {
  const { navigator } = useContext(UNSAFE_NavigationContext);
  const confirm = useConfirm();
  const { t } = useTranslation('einstellungen');
  const location = useLocation();
  const pathRef = useRef(location.pathname);
  pathRef.current = location.pathname;

  useEffect(() => {
    if (!active) return undefined;

    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);

    const nav = navigator as unknown as { push: NavFn; replace: NavFn };
    const origPush = nav.push;
    const origReplace = nav.replace;
    const guard =
      (orig: NavFn): NavFn =>
      (to, ...rest) => {
        const path = targetPath(to);
        // Sprünge innerhalb der Seite (nur Hash oder Suche) verlieren nichts.
        if (!path || path === pathRef.current) {
          orig.call(nav, to, ...rest);
          return;
        }
        void confirm({
          title: t('leaveGuard.title'),
          message: t('leaveGuard.message'),
          confirmText: t('leaveGuard.confirm'),
          cancelText: t('leaveGuard.cancel'),
          danger: true,
        }).then((ok) => {
          if (ok) orig.call(nav, to, ...rest);
        });
      };
    nav.push = guard(origPush);
    nav.replace = guard(origReplace);

    return () => {
      window.removeEventListener('beforeunload', onBeforeUnload);
      nav.push = origPush;
      nav.replace = origReplace;
    };
  }, [active, navigator, confirm, t]);
}
