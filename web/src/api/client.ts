/**
 * HTTP-Client der Web-Oberfläche: Token, Sprache, Fehlerformat, Downloads.
 *
 * Jede Anfrage sendet die Sprache der Oberfläche (`X-Tapesmith-Language`), Links für `<img src>`,
 * Downloads und den Ereignis-Strom tragen sie als Parameter `lang`: der Dienst liefert Meldungen,
 * Warnungen, Status und Vorlagen dann in dieser Sprache.
 */
import { currentLanguage, i18n } from '../i18n';
import type { ApiErrorBody } from './types';

export const LANGUAGE_HEADER = 'X-Tapesmith-Language';

export class ApiError extends Error {
  status: number;
  kind: string;
  hint: string;
  exitCode: number;
  details: Record<string, unknown> | null;
  /** Stabiler Fehlercode, z. B. `printer.unreachable`; Titel und Hinweis übersetzt die Oberfläche. */
  code: string;

  constructor(
    status: number,
    kind: string,
    message: string,
    hint = '',
    exitCode = 1,
    details: Record<string, unknown> | null = null,
    code = 'http.error',
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.kind = kind;
    this.hint = hint;
    this.exitCode = exitCode;
    this.details = details;
    this.code = code;
  }
}

export const TOKEN_KEY = 'p12.token';
export const REMEMBER_KEY = 'p12.token.remember';

let token: string | null = null;

function storageGet(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function storageSet(value: string): void {
  try {
    sessionStorage.setItem(TOKEN_KEY, value);
  } catch {
    // Speicher gesperrt: Token bleibt nur im Speicher
  }
}

function rememberGet(): string | null {
  try {
    return localStorage.getItem(REMEMBER_KEY);
  } catch {
    return null;
  }
}

function rememberSet(value: string): void {
  try {
    localStorage.setItem(REMEMBER_KEY, value);
  } catch {
    // Speicher gesperrt: kein dauerhaftes Merken möglich
  }
}

function rememberClear(): void {
  try {
    localStorage.removeItem(REMEMBER_KEY);
  } catch {
    // ignorieren
  }
}

function storageClear(): void {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignorieren
  }
}

/** Liest `#t=...` aus dem Fragment (und entfernt es), sonst sessionStorage, sonst das gemerkte Token. */
export function initToken(): string | null {
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
  token = storageGet() ?? rememberGet();
  return token;
}

export function getToken(): string | null {
  return token;
}

export function setTokenForTests(value: string | null): void {
  token = value;
}

/** Setzt das Token im Speicher und in sessionStorage; `remember` merkt es zusätzlich dauerhaft (localStorage). */
export function setToken(value: string, remember: boolean): void {
  token = value;
  storageSet(value);
  if (remember) rememberSet(value);
  else rememberClear();
}

/** Löscht das Token überall (Abmelden, oder 401 nach zuvor eingegebenem Token). */
export function clearToken(): void {
  token = null;
  storageClear();
  rememberClear();
}

function isAbort(err: unknown): boolean {
  return err instanceof DOMException ? err.name === 'AbortError' : (err as { name?: string } | null)?.name === 'AbortError';
}

async function request(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<Response> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json', [LANGUAGE_HEADER]: currentLanguage() };
  if (token) headers['X-P12-Token'] = token;
  let res: Response;
  try {
    res = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
      credentials: 'same-origin',
    });
  } catch (err) {
    if (isAbort(err)) throw err;
    throw new ApiError(
      0,
      'Offline',
      i18n.t('errors:client.offline.title'),
      i18n.t('errors:client.offline.hint'),
      1,
      null,
      'client.offline',
    );
  }
  if (!res.ok) throw await toApiError(res);
  return res;
}

async function toApiError(res: Response): Promise<ApiError> {
  let parsed: unknown = null;
  try {
    parsed = await res.json();
  } catch {
    parsed = null;
  }
  const err = (parsed as ApiErrorBody | null)?.error;
  if (err && typeof err === 'object' && typeof err.message === 'string') {
    const code = typeof err.code === 'string' && err.code ? err.code : 'http.error';
    return new ApiError(res.status, err.kind ?? 'Error', err.message, err.hint ?? '', err.exit_code ?? 1, err.details ?? null, code);
  }
  return new ApiError(
    res.status,
    'Network',
    i18n.t('common:errors.badStatus', { status: res.status }),
    '',
    1,
    null,
    'client.bad_response',
  );
}

async function json<T>(res: Response): Promise<T> {
  if (res.status === 204) return {} as T;
  const text = await res.text();
  if (!text) return {} as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(res.status, 'Network', i18n.t('common:errors.badJson'), '', 1, null, 'client.bad_response');
  }
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  return json<T>(await request('GET', path, undefined, signal));
}

export async function apiPost<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  return json<T>(await request('POST', path, body ?? {}, signal));
}

export async function apiPut<T>(path: string, body?: unknown): Promise<T> {
  return json<T>(await request('PUT', path, body ?? {}));
}

export async function apiPatch<T>(path: string, body?: unknown): Promise<T> {
  return json<T>(await request('PATCH', path, body ?? {}));
}

export async function apiDelete<T>(path: string): Promise<T> {
  return json<T>(await request('DELETE', path));
}

function filenameFrom(disposition: string | null): string | null {
  if (!disposition) return null;
  const star = /filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i.exec(disposition);
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ''));
    } catch {
      // weiter mit filename=
    }
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(disposition);
  return plain?.[1]?.trim() ?? null;
}

/** Lädt eine Datei (Blob) und löst den Download über `<a download>` aus. */
export async function apiDownload(
  path: string,
  body: unknown | undefined,
  fallbackName: string,
  method: 'GET' | 'POST' = body === undefined ? 'GET' : 'POST',
): Promise<void> {
  const res = await request(method, path, method === 'GET' ? undefined : (body ?? {}));
  const blob = await res.blob();
  const name = filenameFrom(res.headers.get('Content-Disposition')) ?? fallbackName;
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

/** Hängt die Sprache (`lang`) und `t=<token>` an (für `<img src>` und EventSource). */
export function authUrl(path: string, params?: Record<string, string | number | boolean | undefined | null>): string {
  const [base, existing] = path.split('?', 2) as [string, string | undefined];
  const search = new URLSearchParams(existing ?? '');
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value === undefined || value === null) continue;
    search.set(key, String(value));
  }
  if (!search.has('lang')) search.set('lang', currentLanguage());
  if (token) search.set('t', token);
  const qs = search.toString();
  return qs ? `${base}?${qs}` : base;
}

export function pngSrc(b64: string): string {
  return `data:image/png;base64,${b64}`;
}
