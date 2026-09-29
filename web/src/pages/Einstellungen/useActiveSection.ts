/** Ermittelt den Abschnitt, der beim Scrollen gerade die Bildschirmmitte überquert, für die Hervorhebung in `SectionNav`. */
import { useEffect, useRef, useState } from 'react';
import type { NavItem } from './SectionNav';

export function useActiveSection(items: NavItem[]): string | null {
  const [activeId, setActiveId] = useState<string | null>(null);
  const visibleRef = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined' || items.length === 0) return undefined;
    const ids = items.map((item) => item.id);
    const elements = ids
      .map((id) => document.getElementById(id))
      .filter((el): el is HTMLElement => el !== null);
    if (elements.length === 0) return undefined;

    visibleRef.current = new Map();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const id = entry.target.id;
          if (entry.isIntersecting) {
            visibleRef.current.set(id, entry.intersectionRatio);
          } else {
            visibleRef.current.delete(id);
          }
        }
        // Erster im DOM stehender sichtbarer Abschnitt gewinnt (Reihenfolge wie in der Sprungliste).
        const next = ids.find((id) => visibleRef.current.has(id)) ?? null;
        setActiveId(next);
      },
      // Zählt einen Abschnitt als "aktiv", sobald er den oberen oder mittleren Bereich des Fensters erreicht.
      { rootMargin: '-15% 0px -70% 0px', threshold: [0, 1] },
    );
    elements.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
  }, [items]);

  return activeId;
}
