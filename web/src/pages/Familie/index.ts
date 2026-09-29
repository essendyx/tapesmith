/**
 * Einstieg der Familienseite: eigenständig, kein Zusammenhang mit ../../App. Nur der lazy-
 * Import ist hier verdrahtet (kein zusätzlicher statischer Re-Export von FamilyApp), sonst zieht
 * Vite das Modul ins Haupt-Bundle statt in einen eigenen Chunk.
 */
import { lazy } from 'react';

export const LazyFamilyApp = lazy(() => import('./FamilyApp'));

/**
 * Ob ein Pfad zur Familienseite gehört (`/familie`, `/familie/...`), unabhängig von Suchparametern
 * oder Fragment. `/familienfoto` gehört nicht dazu (kein Pfadtrenner nach dem Präfix).
 */
export function isFamilyPath(pathname: string): boolean {
  const path = pathname.split(/[?#]/)[0] ?? '';
  return path === '/familie' || path.startsWith('/familie/');
}
