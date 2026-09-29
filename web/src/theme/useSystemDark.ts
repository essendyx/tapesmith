import { useEffect, useState } from 'react';

const QUERY = '(prefers-color-scheme: dark)';

function current(): boolean {
  try {
    return typeof window.matchMedia === 'function' && window.matchMedia(QUERY).matches;
  } catch {
    return false;
  }
}

/** true, wenn Windows (bzw. der Browser) den dunklen Modus meldet; folgt Änderungen live. */
export function useSystemDark(): boolean {
  const [dark, setDark] = useState(current);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const mql = window.matchMedia(QUERY);
    const onChange = (e: MediaQueryListEvent) => setDark(e.matches);
    setDark(mql.matches);
    if (typeof mql.addEventListener === 'function') {
      mql.addEventListener('change', onChange);
      return () => mql.removeEventListener('change', onChange);
    }
    mql.addListener(onChange);
    return () => mql.removeListener(onChange);
  }, []);
  return dark;
}

export type ThemeSetting = 'system' | 'hell' | 'dunkel';

/** Dunkel ja oder nein aus der Einstellung `app.theme`; "system" (bzw. unbekannt) folgt Windows. */
export function resolveDark(setting: ThemeSetting | null | undefined, systemDark: boolean): boolean {
  if (setting === 'dunkel') return true;
  if (setting === 'hell') return false;
  return systemDark;
}

/** Wie `useSystemDark`, aber mit fester Wahl hell oder dunkel aus der Einstellung. */
export function useColorScheme(setting: ThemeSetting | null | undefined): boolean {
  const systemDark = useSystemDark();
  return resolveDark(setting, systemDark);
}
