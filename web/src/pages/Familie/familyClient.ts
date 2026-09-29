/**
 * Eigener HTTP-Client der Familienseite. Eigener Token-Speicher (localStorage, dauerhaft auf
 * dem Handy), unabhängig von ../../api/client (das nutzt das Admin-Token in sessionStorage).
 * Ruft ausschließlich die vier Familienrouten unter /api/v1/familie/... auf.
 */
import { currentLanguage, i18n } from '../../i18n';
import type { FamilyPreview, FamilyPrintResult, FamilyStatus, FamilyTemplatesResponse } from './types';

export const FAMILY_TOKEN_KEY = 'p12.familie.token';

const FAMILY_BASE = '/api/v1/familie';

export class FamilyError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'FamilyError';
    this.status = status;
  }
}

let token: string | null = null;

function storageGet(): string | null {
  try {
    return localStorage.getItem(FAMILY_TOKEN_KEY);
  } catch {
    return null;
  }
}

function storageSet(value: string): void {
  try {
    localStorage.setItem(FAMILY_TOKEN_KEY, value);
  } catch {
    // Speicher gesperrt: Token bleibt nur im Speicher dieser Sitzung
  }
}

function storageRemove(): void {
  try {
    localStorage.removeItem(FAMILY_TOKEN_KEY);
  } catch {
    // ignorieren
  }
}

/**
 * Liest `#t=...` aus dem Fragment, speichert es dauerhaft und entfernt das Fragment aus der
 * Adresse (kein Verbleib in der Chronik). Ohne Fragment: gespeicherten Wert liefern. Schreibt nie
 * nach sessionStorage `p12.token` (das Admin-Token bliebe sonst unberührt, dieser Speicher ist
 * komplett getrennt).
 */
export function initFamilyToken(): string | null {
  const hash = window.location.hash.replace(/^#/, '');
  if (hash) {
    const params = new URLSearchParams(hash);
    const fromHash = params.get('t');
    if (fromHash) {
      token = fromHash;
      storageSet(fromHash);
      params.delete('t');
      const rest = params.toString();
      const url = window.location.pathname + window.location.search + (rest ? `#${rest}` : '');
      try {
        window.history.replaceState(window.history.state, '', url);
      } catch {
        // ignorieren
      }
      return token;
    }
  }
  token = storageGet();
  return token;
}

export function getFamilyToken(): string | null {
  return token;
}

/** Vom Hinweisschirm: Token übernehmen und dauerhaft speichern. */
export function setFamilyToken(value: string): void {
  token = value;
  storageSet(value);
}

export function clearFamilyToken(): void {
  token = null;
  storageRemove();
}

export function setFamilyTokenForTests(value: string | null): void {
  token = value;
}

function isAbort(err: unknown): boolean {
  return err instanceof DOMException ? err.name === 'AbortError' : (err as { name?: string } | null)?.name === 'AbortError';
}

/**
 * Ruft ausschließlich `/api/v1/familie/<path>` auf. `Authorization: Bearer <token>`,
 * `Content-Type: application/json`, `credentials: 'same-origin'`. Fehlerantworten werden
 * zu `FamilyError(status, message)`, ein Netzfehler zu „Keine Verbindung zum Drucker-PC“.
 */
export async function familyFetch<T>(method: string, path: string, body?: unknown): Promise<T> {
  // Sprache der Seite (Browser des Handys): der Dienst antwortet in ihr.
  const headers: Record<string, string> = { 'Content-Type': 'application/json', 'X-Tapesmith-Language': currentLanguage() };
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${FAMILY_BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'same-origin',
    });
  } catch (err) {
    if (isAbort(err)) throw err;
    throw new FamilyError(0, i18n.t('familie:errors.offline'));
  }
  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  if (!res.ok) {
    const err = (parsed as { error?: { message?: string } } | null)?.error;
    throw new FamilyError(res.status, err?.message ?? `Unerwartete Antwort vom Druckdienst (HTTP ${res.status})`);
  }
  return (parsed ?? {}) as T;
}

export function getTemplates(): Promise<FamilyTemplatesResponse> {
  return familyFetch<FamilyTemplatesResponse>('GET', '/vorlagen');
}

export function postPreview(template: string, values: Record<string, string>): Promise<FamilyPreview> {
  return familyFetch<FamilyPreview>('POST', '/vorschau', { template, values });
}

export function postPrint(
  template: string,
  values: Record<string, string>,
  copies: number,
  confirmed: boolean,
): Promise<FamilyPrintResult> {
  return familyFetch<FamilyPrintResult>('POST', '/drucken', { template, values, copies, confirmed });
}

export function getStatus(): Promise<FamilyStatus> {
  return familyFetch<FamilyStatus>('GET', '/status');
}
