/** Test-Helfer für alle Seiten: mockApi (fetch-Stub), renderWithProviders, LocationProbe. */
import type { ReactElement } from 'react';
import { render, screen, waitFor, type RenderResult } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import type { QueryClient } from '@tanstack/react-query';
import { vi } from 'vitest';
import { AppContent, AppProviders, makeQueryClient } from '../App';
import { setTokenForTests } from '../api/client';
import type { AppInfo } from '../api/types';
import { i18n, type Language } from '../i18n';
import { fixtures } from './fixtures';

export { fixtures } from './fixtures';
export { FakeEventSource } from './fakeEventSource';

/** Stellt die Sprache für den laufenden Test um (nach jedem Test wieder Deutsch). */
export function setTestLanguage(lang: Language): void {
  void i18n.changeLanguage(lang);
  document.documentElement.lang = lang;
}

/** Wartezeit für Dialoge, die unter voller Parallellast (alle jsdom-Worker) spät erscheinen. */
export const SLOW_UI_MS = 15000;

/**
 * Findet einen offenen Fluent-Dialog (auch Rückfragen mit role="alertdialog") über seinen Titel,
 * auch wenn er aria-hidden trägt.
 *
 * Unter voller Parallellast bleibt in jsdom gelegentlich ein Tabster-Modalizer eines bereits
 * entfernten Dialogs aktiv. Tabster markiert dann jede neue DialogSurface dauerhaft mit
 * aria-hidden; `getByRole('dialog')` findet sie nie, egal wie lange es wartet (im
 * Fehlerfall per DOM-Abzug belegt). Deshalb: Titeltext suchen und zum Dialog hochgehen, und im
 * Dialog mit `hidden: true` abfragen.
 */
export function findDialog(title: string): Promise<HTMLElement> {
  return waitFor(
    () => {
      // Titeltext auch dann, wenn er in Kindelementen steckt (Rückfrage: Warnsymbol plus
      // Screenreader-Präfix vor dem Titel); die Surface selbst braucht in jsdom kein Layout.
      const dialog = Array.from(document.querySelectorAll<HTMLElement>('.fui-DialogTitle'))
        .filter((el) => {
          const text = (el.textContent ?? '').replace(/\s+/g, ' ').trim();
          return text === title || text.endsWith(` ${title}`);
        })
        .map((el) => el.closest<HTMLElement>('[role="dialog"], [role="alertdialog"]'))
        .find((el): el is HTMLElement => el !== null);
      if (!dialog) throw new Error(`Dialog „${title}“ nicht gefunden`);
      return dialog;
    },
    { timeout: SLOW_UI_MS },
  );
}

function accessibleName(el: HTMLElement): string {
  const label = el.getAttribute('aria-label');
  if (label) return label.trim();
  const ids = (el.getAttribute('aria-labelledby') ?? '').split(/\s+/).filter(Boolean);
  return ids
    .map((id) => document.getElementById(id)?.textContent ?? '')
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Wie `findDialog`, aber über die Rolle (und optional den zugänglichen Namen) statt über den
 * Titel: für Dialoge ohne `DialogTitle` (Schublade) und für Tests, die den Titel nicht kennen.
 * Findet auch Dialoge mit aria-hidden (Tabster-Rest unter Volllast); liefert den zuletzt
 * geöffneten. Abfragen im Dialog brauchen dann `hidden: true`.
 */
export function findDialogByRole(role: 'dialog' | 'alertdialog' = 'dialog', name?: string): Promise<HTMLElement> {
  return waitFor(
    () => {
      const all = Array.from(document.querySelectorAll<HTMLElement>(`[role="${role}"]`)).filter(
        (el) => name === undefined || accessibleName(el) === name,
      );
      const dialog = all[all.length - 1];
      if (!dialog) throw new Error(`Kein ${role}${name ? ` „${name}“` : ''} gefunden`);
      return dialog;
    },
    { timeout: SLOW_UI_MS },
  );
}

/** Ob gerade irgendein Dialog im DOM steckt (auch aria-hidden, siehe findDialog). */
export function anyDialogInDom(): boolean {
  return document.querySelector('[role="dialog"], [role="alertdialog"]') !== null;
}

type UserEvent = ReturnType<typeof userEvent.setup>;

export class MockResponse {
  constructor(
    public status: number,
    public body: unknown,
    public headers?: Record<string, string>,
  ) {}
}

export type MockHandler = (req: {
  method: string;
  path: string;
  params: Record<string, string>;
  query: URLSearchParams;
  body: unknown;
}) => unknown | MockResponse | Promise<unknown | MockResponse>;

export interface MockApi {
  calls: { method: string; path: string; body: unknown }[];
  unmatched: { method: string; path: string }[];
  restore(): void;
}

interface CompiledRoute {
  key: string;
  method: string;
  regex: RegExp;
  names: string[];
  handler: MockHandler;
}

interface ActiveMock {
  api: MockApi;
  routes: CompiledRoute[];
}

const active: ActiveMock[] = [];

function compile(key: string, handler: MockHandler): CompiledRoute {
  const space = key.indexOf(' ');
  const method = key.slice(0, space).toUpperCase();
  const pattern = key.slice(space + 1).trim();
  const names: string[] = [];
  const source = pattern
    .split('/')
    .map((seg) => {
      if (seg.startsWith(':')) {
        names.push(seg.slice(1));
        return '([^/]+)';
      }
      return seg.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    })
    .join('/');
  return { key, method, regex: new RegExp(`^${source}$`), names, handler };
}

function jsonResponse(status: number, body: unknown, headers?: Record<string, string>): Response {
  if (body instanceof Blob || body instanceof ArrayBuffer || body instanceof Uint8Array) {
    return new Response(body as BodyInit, { status, headers });
  }
  if (typeof body === 'string' && headers && Object.keys(headers).some((h) => h.toLowerCase() === 'content-type')) {
    return new Response(body, { status, headers });
  }
  const text = body === undefined ? '' : JSON.stringify(body);
  return new Response(status === 204 ? null : text, {
    status,
    headers: { 'Content-Type': 'application/json', ...(headers ?? {}) },
  });
}

function errorBody(kind: string, message: string) {
  return { error: { kind, message, hint: '', exit_code: 1, details: null } };
}

/**
 * Stubbt `globalThis.fetch`. Schlüssel wie "GET /api/v1/status", Pfadparameter ":id".
 * Unbekannte Routen liefern 404 im Fehlerformat, landen in `unmatched` und werden (ohne `quiet`) per console.error gemeldet.
 */
export function mockApi(routes: Record<string, MockHandler>, opts?: { quiet?: boolean }): MockApi {
  const compiled = Object.entries(routes).map(([k, h]) => compile(k, h));
  const previous = globalThis.fetch;
  const calls: MockApi['calls'] = [];
  const unmatched: MockApi['unmatched'] = [];
  const quiet = opts?.quiet ?? false;

  const fake = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const rawUrl = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(rawUrl, 'http://127.0.0.1');
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    let body: unknown = undefined;
    const rawBody = init?.body;
    if (typeof rawBody === 'string') {
      try {
        body = JSON.parse(rawBody);
      } catch {
        body = rawBody;
      }
    }
    if (init?.signal?.aborted) throw new DOMException('Abgebrochen', 'AbortError');
    calls.push({ method, path: url.pathname + url.search, body });
    for (const route of compiled) {
      if (route.method !== method) continue;
      const m = route.regex.exec(url.pathname);
      if (!m) continue;
      const params: Record<string, string> = {};
      route.names.forEach((name, i) => {
        params[name] = decodeURIComponent(m[i + 1] ?? '');
      });
      try {
        const result = await route.handler({ method, path: url.pathname, params, query: url.searchParams, body });
        if (result instanceof MockResponse) return jsonResponse(result.status, result.body, result.headers);
        return jsonResponse(200, result ?? {});
      } catch (err) {
        return jsonResponse(500, errorBody('Mock', err instanceof Error ? err.message : String(err)));
      }
    }
    unmatched.push({ method, path: url.pathname });
    if (!quiet) console.error(`mockApi: keine Route für ${method} ${url.pathname}`);
    return jsonResponse(404, errorBody('NotFound', `Nicht gefunden: ${url.pathname}`));
  };

  globalThis.fetch = vi.fn(fake) as unknown as typeof fetch;
  const entry: ActiveMock = {
    routes: compiled,
    api: {
      calls,
      unmatched,
      restore() {
        const i = active.indexOf(entry);
        if (i >= 0) active.splice(i, 1);
        if (globalThis.fetch === previous) return;
        globalThis.fetch = previous;
      },
    },
  };
  active.push(entry);
  return entry.api;
}

/** Hebt alle noch aktiven mockApi-Stubs auf (läuft nach jedem Test). */
export function restoreAllMocks(): void {
  while (active.length) active[active.length - 1]?.api.restore();
}

export function LocationProbe(): JSX.Element {
  const location = useLocation();
  return <output data-testid="location">{location.pathname + location.search}</output>;
}

/**
 * Rendert mit Token (Standard "test-token"), QueryClient ohne Retries, Theme, Router (MemoryRouter),
 * Confirm-, Notify-, Command- und ServerEvents-Provider. `withShell` rendert zusätzlich den ganzen Rahmen mit Routen.
 * `/api/v1/app` wird mit `fixtures.appInfo` gemockt, falls der Test es nicht selbst mockt.
 * `language` (Standard `de`) stellt die Oberfläche vor dem Rendern um; das gemockte `AppInfo`
 * bekommt dieselbe Sprache (außer `app.language` ist gesetzt), damit `LanguageSync` sie nicht überschreibt.
 */
export function renderWithProviders(
  ui: ReactElement,
  opts?: { route?: string; token?: string | null; app?: Partial<AppInfo>; withShell?: boolean; language?: Language },
): RenderResult & { user: UserEvent; queryClient: QueryClient } {
  const token = opts && 'token' in opts ? (opts.token ?? null) : 'test-token';
  setTokenForTests(token);
  const language = opts?.language ?? 'de';
  setTestLanguage(language);
  const appInfo: AppInfo = { ...fixtures.appInfo, language, ...(opts?.app ?? {}) };
  const appHandler: MockHandler = () => appInfo;
  const current = active[active.length - 1];
  if (!current) {
    mockApi({ 'GET /api/v1/app': appHandler });
  } else if (!current.routes.some((r) => r.method === 'GET' && r.regex.test('/api/v1/app'))) {
    current.routes.push(compile('GET /api/v1/app', appHandler));
  }
  const queryClient = makeQueryClient({ retry: false });
  const user = vi.isFakeTimers() ? userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) }) : userEvent.setup();
  const result = render(
    <MemoryRouter initialEntries={[opts?.route ?? '/']}>
      <AppProviders queryClient={queryClient}>
        {opts?.withShell ? (
          <>
            <AppContent />
            {ui}
          </>
        ) : (
          <Routes>
            <Route path="*" element={ui} />
          </Routes>
        )}
      </AppProviders>
    </MemoryRouter>,
  );
  return Object.assign(result, { user, queryClient });
}

/**
 * Simuliert eine schmale (oder breite) Fensterbreite über matchMedia. Nur Breiten-Abfragen
 * (`max-width`) matchen, die Dunkelmodus-Abfrage des ThemeProviders bleibt unberührt.
 * Gibt eine Funktion zum Zurücksetzen zurück.
 */
export function mockNarrowScreen(matches: boolean): () => void {
  const spy = vi.spyOn(window, 'matchMedia').mockImplementation(
    (query: string) =>
      ({
        matches: matches && query.includes('max-width'),
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  );
  return () => spy.mockRestore();
}

/**
 * Wählt eine Zeilenaktion aus dem „Mehr“-Menü (`RowActions`): öffnet das Menü der Zeile `rowTitle`
 * (zugänglicher Name „Weitere Aktionen für …“ bzw. „More actions for …“) und klickt den Eintrag
 * `action` (Text oder Muster). Untermenüs: `action` als Liste, z. B. `['Exportieren', 'PDF']`.
 */
export async function chooseRowAction(
  user: UserEvent,
  rowTitle: string,
  action: string | RegExp | (string | RegExp)[],
): Promise<void> {
  const trigger = screen.getByRole('button', { name: new RegExp(`^(Weitere Aktionen für|More actions for) ${escapeRegExp(rowTitle)}$`) });
  await user.click(trigger);
  const steps = Array.isArray(action) ? action : [action];
  for (const step of steps) {
    const item = await screen.findByRole('menuitem', { name: step }, { timeout: SLOW_UI_MS });
    await user.click(item);
  }
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
