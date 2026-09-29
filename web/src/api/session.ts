/** Fenster-Sitzung für Entwürfe: eine Kennung je Browserfenster bzw. App-Fenster. */

export const WINDOW_SESSION_KEY = 'p12.window';

let memory: string | null = null;

function newId(): string {
  try {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  } catch {
    // Rückfall unten
  }
  return `w-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

/** Stabil innerhalb eines Fensters (sessionStorage `p12.window`), sonst eine neue UUID. */
export function windowSessionId(): string {
  try {
    const stored = sessionStorage.getItem(WINDOW_SESSION_KEY);
    if (stored) return stored;
    const id = memory ?? newId();
    sessionStorage.setItem(WINDOW_SESSION_KEY, id);
    memory = id;
    return id;
  } catch {
    // Speicher gesperrt: Kennung nur im Speicher
    memory ??= newId();
    return memory;
  }
}

/** Nur für Tests: vergisst die Kennung im Speicher. */
export function resetWindowSessionForTests(): void {
  memory = null;
}
