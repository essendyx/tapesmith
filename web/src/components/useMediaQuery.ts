/** Breite-Erkennung für responsives Layout (gemeinsam für Vorlagen, Serie/Import, SSH und Verleih). */
import { useEffect, useState } from 'react';

export function useMediaQuery(query: string): boolean {
  const get = () => {
    try {
      return typeof window.matchMedia === 'function' && window.matchMedia(query).matches;
    } catch {
      return false;
    }
  };
  const [matches, setMatches] = useState(get);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined;
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener?.('change', onChange);
    return () => mql.removeEventListener?.('change', onChange);
  }, [query]);
  return matches;
}
