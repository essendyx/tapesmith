import { useEffect, useState } from 'react';

/** `true`, solange die Medienabfrage zutrifft (ohne matchMedia: false). */
export function useMediaQuery(query: string): boolean {
  const get = () => {
    try {
      return typeof window.matchMedia === 'function' ? window.matchMedia(query).matches : false;
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

/** Breite eines Elements (ResizeObserver), 0 solange unbekannt. */
export function useElementWidth(el: HTMLElement | null): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!el) return undefined;
    setWidth(el.clientWidth);
    if (typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w !== undefined) setWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  return width;
}
