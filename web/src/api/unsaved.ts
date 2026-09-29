/**
 * Register für ungespeicherte Änderungen. Quellen melden sich mit einer Zählfunktion
 * an; `window.p12UnsavedCount` (für das App-Fenster) und der `beforeunload`-Handler lesen die Summe.
 */

declare global {
  interface Window {
    p12UnsavedCount?: () => number;
  }
}

const sources = new Map<string, () => number>();
let installed = false;

function onBeforeUnload(event: BeforeUnloadEvent): void {
  if (unsavedCount() > 0) {
    event.preventDefault();
    // Ältere Browser brauchen zusätzlich returnValue für die Rückfrage.
    event.returnValue = '';
  }
}

function install(): void {
  if (installed || typeof window === 'undefined') return;
  installed = true;
  window.p12UnsavedCount = unsavedCount;
  window.addEventListener('beforeunload', onBeforeUnload);
}

/** Summe aller angemeldeten Quellen (Fehler einer Quelle zählen als 0). */
export function unsavedCount(): number {
  let sum = 0;
  for (const count of sources.values()) {
    try {
      const n = count();
      if (Number.isFinite(n) && n > 0) sum += n;
    } catch {
      // Quelle defekt: nicht mitzählen
    }
  }
  return sum;
}

/** Meldet eine Quelle an (gleicher Name ersetzt die alte); die Rückgabe meldet sie wieder ab. */
export function registerUnsaved(source: string, count: () => number): () => void {
  install();
  sources.set(source, count);
  return () => {
    if (sources.get(source) === count) sources.delete(source);
  };
}

/** Nur für Tests: leert das Register und installiert Handler und `window.p12UnsavedCount` neu. */
export function resetUnsavedForTests(): void {
  sources.clear();
  if (installed && typeof window !== 'undefined') {
    window.removeEventListener('beforeunload', onBeforeUnload);
    delete window.p12UnsavedCount;
  }
  installed = false;
  install();
}

install();
