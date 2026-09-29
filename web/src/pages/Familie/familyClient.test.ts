import { afterEach, describe, expect, it, vi } from 'vitest';
import { mockApi, MockResponse } from '../../test/utils';
import { TOKEN_KEY } from '../../api/client';
import {
  FAMILY_TOKEN_KEY,
  FamilyError,
  clearFamilyToken,
  familyFetch,
  getFamilyToken,
  getStatus,
  getTemplates,
  initFamilyToken,
  postPreview,
  postPrint,
  setFamilyTokenForTests,
} from './familyClient';

afterEach(() => {
  setFamilyTokenForTests(null);
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('initFamilyToken', () => {
  it('speichert #t=... dauerhaft, entfernt das Fragment und rührt sessionStorage p12.token nicht an', () => {
    window.history.replaceState(null, '', '/familie#t=p12_abc');
    const token = initFamilyToken();
    expect(token).toBe('p12_abc');
    expect(localStorage.getItem(FAMILY_TOKEN_KEY)).toBe('p12_abc');
    expect(window.location.hash).toBe('');
    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it('liefert ohne Fragment den gespeicherten Wert', () => {
    localStorage.setItem(FAMILY_TOKEN_KEY, 'p12_stored');
    window.history.replaceState(null, '', '/familie');
    expect(initFamilyToken()).toBe('p12_stored');
  });
});

describe('clearFamilyToken', () => {
  it('löscht den Speicher und den internen Wert', () => {
    setFamilyTokenForTests('p12_x');
    localStorage.setItem(FAMILY_TOKEN_KEY, 'p12_x');
    clearFamilyToken();
    expect(getFamilyToken()).toBeNull();
    expect(localStorage.getItem(FAMILY_TOKEN_KEY)).toBeNull();
  });
});

describe('familyFetch', () => {
  it('setzt Authorization: Bearer und ruft nur /api/v1/familie/... auf', async () => {
    setFamilyTokenForTests('p12_secret');
    const spy = vi.fn((_input: RequestInfo | URL, _init?: RequestInit) =>
      Promise.resolve(new Response(JSON.stringify({ online: true, text: 'ok', waiting: 0 }), { status: 200, headers: { 'Content-Type': 'application/json' } })),
    );
    vi.stubGlobal('fetch', spy);
    await getStatus();
    expect(spy).toHaveBeenCalledTimes(1);
    const [url, init] = spy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/familie/status');
    const headers = new Headers(init.headers);
    expect(headers.get('Authorization')).toBe('Bearer p12_secret');
    // Sprache der Seite (Handy-Browser), damit der Dienst in ihr antwortet
    expect(headers.get('X-Tapesmith-Language')).toBe('de');
  });

  it('401 ergibt FamilyError mit Status 401', async () => {
    setFamilyTokenForTests('p12_bad');
    const api = mockApi(
      {
        'GET /api/v1/familie/status': () =>
          new MockResponse(401, { error: { kind: 'Auth', message: 'Nicht angemeldet: Token fehlt oder ist falsch', hint: '', exit_code: 1, details: null } }),
      },
      { quiet: true },
    );
    await expect(getStatus()).rejects.toBeInstanceOf(FamilyError);
    expect(api.calls).toHaveLength(1);
  });

  it('Netzfehler ergibt „Keine Verbindung zum Drucker-PC“', async () => {
    setFamilyTokenForTests('p12_x');
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new TypeError('network down'))),
    );
    await expect(familyFetch('GET', '/status')).rejects.toMatchObject({ status: 0, message: 'Keine Verbindung zum Drucker-PC' });
  });
});

describe('Familienrouten', () => {
  it('getTemplates ruft GET /vorlagen auf', async () => {
    setFamilyTokenForTests('p12_x');
    const api = mockApi({ 'GET /api/v1/familie/vorlagen': () => ({ templates: [], max_copies: 5 }) });
    await getTemplates();
    expect(api.calls[0]).toMatchObject({ method: 'GET', path: '/api/v1/familie/vorlagen' });
  });

  it('postPreview ruft POST /vorschau mit template und values auf', async () => {
    setFamilyTokenForTests('p12_x');
    const api = mockApi({
      'POST /api/v1/familie/vorschau': () => ({ ok: true, errors: [], warnings: [], design_png: null, width: null, height: null, length_mm: null }),
    });
    await postPreview('gefriergut', { inhalt: 'Suppe' });
    expect(api.calls[0]).toMatchObject({ method: 'POST', path: '/api/v1/familie/vorschau', body: { template: 'gefriergut', values: { inhalt: 'Suppe' } } });
  });

  it('postPrint ruft POST /drucken mit copies und confirmed auf', async () => {
    setFamilyTokenForTests('p12_x');
    const api = mockApi({ 'POST /api/v1/familie/drucken': () => ({ status: 'ok', message: '', reasons: [], queue_id: null }) });
    await postPrint('gefriergut', { inhalt: 'Suppe' }, 2, true);
    expect(api.calls[0]).toMatchObject({
      method: 'POST',
      path: '/api/v1/familie/drucken',
      body: { template: 'gefriergut', values: { inhalt: 'Suppe' }, copies: 2, confirmed: true },
    });
  });
});
