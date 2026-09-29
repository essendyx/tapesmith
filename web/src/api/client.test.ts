import { describe, expect, it, afterEach, vi } from 'vitest';
import {
  ApiError,
  apiGet,
  apiPost,
  authUrl,
  clearToken,
  getToken,
  initToken,
  pngSrc,
  REMEMBER_KEY,
  setToken,
  setTokenForTests,
  TOKEN_KEY,
} from './client';
import { mockApi, MockResponse } from '../test/utils';

afterEach(() => {
  setTokenForTests(null);
  sessionStorage.clear();
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('client', () => {
  it('initToken liest #t=, speichert und entfernt das Fragment', () => {
    window.history.replaceState(null, '', '/schnelldruck?x=1#t=abc');
    const token = initToken();
    expect(token).toBe('abc');
    expect(sessionStorage.getItem(TOKEN_KEY)).toBe('abc');
    expect(window.location.hash).toBe('');
    expect(window.location.pathname + window.location.search).toBe('/schnelldruck?x=1');
    expect(getToken()).toBe('abc');
  });

  it('initToken nimmt ohne Fragment den Wert aus sessionStorage', () => {
    window.history.replaceState(null, '', '/');
    sessionStorage.setItem(TOKEN_KEY, 'gespeichert');
    expect(initToken()).toBe('gespeichert');
  });

  it('apiGet sendet X-P12-Token', async () => {
    setTokenForTests('tok');
    const spy = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(new Response(JSON.stringify({ ok: 1 }), { status: 200, headers: { 'Content-Type': 'application/json' } })),
    );
    vi.stubGlobal('fetch', spy);
    const data = await apiGet<{ ok: number }>('/api/v1/app');
    expect(data.ok).toBe(1);
    const init = spy.mock.calls[0]?.[1];
    const headers = new Headers(init?.headers);
    expect(headers.get('X-P12-Token')).toBe('tok');
    expect(headers.get('X-Tapesmith-Language')).toBe('de');
    vi.unstubAllGlobals();
  });

  it('Fehlerkörper wird zu ApiError', async () => {
    setTokenForTests('tok');
    const api = mockApi({
      'POST /api/v1/labels/print': () =>
        new MockResponse(422, { error: { kind: 'TemplateError', message: 'Kaputt', hint: 'Vorlage prüfen', exit_code: 6, details: null } }),
    });
    const err = await apiPost('/api/v1/labels/print', {}).catch((e: unknown) => e);
    api.restore();
    expect(err).toBeInstanceOf(ApiError);
    const e = err as ApiError;
    expect(e.status).toBe(422);
    expect(e.kind).toBe('TemplateError');
    expect(e.hint).toBe('Vorlage prüfen');
    expect(e.exitCode).toBe(6);
    expect(e.message).toBe('Kaputt');
  });

  it('nicht-JSON-Fehler ergibt kind Network', async () => {
    vi.stubGlobal('fetch', () => Promise.resolve(new Response('<html>kaputt</html>', { status: 502 })));
    const err = (await apiGet('/api/v1/app').catch((e: unknown) => e)) as ApiError;
    vi.unstubAllGlobals();
    expect(err.kind).toBe('Network');
    expect(err.status).toBe(502);
  });

  it('fetch wirft: ApiError Offline mit status 0', async () => {
    vi.stubGlobal('fetch', () => Promise.reject(new TypeError('Failed to fetch')));
    const err = (await apiGet('/api/v1/app').catch((e: unknown) => e)) as ApiError;
    vi.unstubAllGlobals();
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
    expect(err.kind).toBe('Offline');
    expect(err.message).toBe('Druckdienst nicht erreichbar');
  });

  it('Fehlerkörper mit code ergibt err.code', async () => {
    const api = mockApi({
      'GET /api/v1/status': () =>
        new MockResponse(503, {
          error: { kind: 'ConnectTimeout', code: 'printer.unreachable', message: 'Zeitüberschreitung', hint: 'Hinweis', exit_code: 5, details: null },
        }),
    });
    const err = (await apiGet('/api/v1/status').catch((e: unknown) => e)) as ApiError;
    api.restore();
    expect(err.code).toBe('printer.unreachable');
    expect(err.message).toBe('Zeitüberschreitung');
  });

  it('Fehlerkörper ohne code ergibt http.error', async () => {
    const api = mockApi({
      'GET /api/v1/status': () => new MockResponse(409, { error: { kind: 'Konflikt', message: 'Belegt', hint: '', exit_code: 7, details: null } }),
    });
    const err = (await apiGet('/api/v1/status').catch((e: unknown) => e)) as ApiError;
    api.restore();
    expect(err.code).toBe('http.error');
    expect(new ApiError(500, 'X', 'y').code).toBe('http.error');
  });

  it('Offline ergibt client.offline, kaputtes JSON client.bad_response', async () => {
    vi.stubGlobal('fetch', () => Promise.reject(new TypeError('Failed to fetch')));
    const offline = (await apiGet('/api/v1/app').catch((e: unknown) => e)) as ApiError;
    vi.stubGlobal('fetch', () => Promise.resolve(new Response('{kaputt', { status: 200 })));
    const broken = (await apiGet('/api/v1/app').catch((e: unknown) => e)) as ApiError;
    vi.stubGlobal('fetch', () => Promise.resolve(new Response('<html>kaputt</html>', { status: 502 })));
    const html = (await apiGet('/api/v1/app').catch((e: unknown) => e)) as ApiError;
    vi.unstubAllGlobals();
    expect(offline.code).toBe('client.offline');
    expect(broken).toBeInstanceOf(ApiError);
    expect(broken.code).toBe('client.bad_response');
    expect(broken.message).toBe('Antwort des Druckdienstes ist kein gültiges JSON');
    expect(html.code).toBe('client.bad_response');
  });

  it('authUrl hängt Sprache und t= an', () => {
    setTokenForTests('a b');
    expect(authUrl('/api/v1/events')).toBe('/api/v1/events?lang=de&t=a+b');
    expect(authUrl('/api/v1/gallery/thumb/x.png', { tape: 'w12', leer: null })).toBe('/api/v1/gallery/thumb/x.png?tape=w12&lang=de&t=a+b');
    expect(authUrl('/api/v1/x?lang=en')).toBe('/api/v1/x?lang=en&t=a+b');
  });

  it('pngSrc baut data-URL', () => {
    expect(pngSrc('AAA')).toBe('data:image/png;base64,AAA');
  });

  it('initToken ohne Fragment und ohne sessionStorage nimmt den Wert aus localStorage (REMEMBER_KEY)', () => {
    window.history.replaceState(null, '', '/');
    localStorage.setItem(REMEMBER_KEY, 'gemerkt');
    expect(initToken()).toBe('gemerkt');
  });

  it('setToken(x, true) merkt sich das Token in sessionStorage und localStorage', () => {
    setToken('x', true);
    expect(getToken()).toBe('x');
    expect(sessionStorage.getItem(TOKEN_KEY)).toBe('x');
    expect(localStorage.getItem(REMEMBER_KEY)).toBe('x');
  });

  it("setToken('x', false) löscht einen vorher gemerkten localStorage-Wert", () => {
    localStorage.setItem(REMEMBER_KEY, 'alt');
    setToken('x', false);
    expect(getToken()).toBe('x');
    expect(sessionStorage.getItem(TOKEN_KEY)).toBe('x');
    expect(localStorage.getItem(REMEMBER_KEY)).toBeNull();
  });

  it('clearToken löscht Speicher und sessionStorage/localStorage', () => {
    setToken('x', true);
    clearToken();
    expect(getToken()).toBeNull();
    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(localStorage.getItem(REMEMBER_KEY)).toBeNull();
  });
});
