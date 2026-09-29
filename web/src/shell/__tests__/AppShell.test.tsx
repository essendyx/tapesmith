/**
 * Rahmen-, Palette- und Kürzel-Tests. Regel: nur Route, Seitentitel, aria-current und Rahmen-Elemente prüfen,
 * nie Seiteninhalte (die Platzhalter werden in Stufe 1 ersetzt). Deshalb mockApi(..., { quiet: true }).
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { FakeEventSource, findDialogByRole, fixtures, LocationProbe, mockApi, MockResponse, renderWithProviders } from '../../test/utils';
import { useRegisterCommands } from '../../commands/CommandProvider';
import { NAV_COLLAPSED_KEY } from '../AppShell';

function baseApi() {
  return mockApi(
    {
      'GET /api/v1/status': () => fixtures.statusJson,
    },
    { quiet: true },
  );
}

function location(): string {
  return screen.getByTestId('location').textContent ?? '';
}

function pageTitle(): string {
  return screen.getByTestId('page-title').textContent ?? '';
}

describe('Rahmen', () => {
  it('ohne Token zeigt NoTokenScreen (App-Fenster)', () => {
    window.pywebview = { api: { retry: vi.fn(() => Promise.resolve()) } };
    baseApi();
    renderWithProviders(<LocationProbe />, { withShell: true, token: null, route: '/schnelldruck' });
    expect(screen.getByText('Bitte über „p12 app“ öffnen')).toBeInTheDocument();
    expect(screen.queryByRole('navigation')).toBeNull();
    delete window.pywebview;
  });

  it('ohne Token im Browser (LAN): zeigt das Anmeldeformular statt der Seiten', () => {
    baseApi();
    renderWithProviders(<LocationProbe />, { withShell: true, token: null, route: '/schnelldruck' });
    expect(screen.getByText('Anmeldung nötig')).toBeInTheDocument();
    expect(screen.getByLabelText('Zugangstoken')).toBeInTheDocument();
    expect(screen.queryByRole('navigation')).toBeNull();
  });

  it('mit Token: Seitenleiste mit 13 Einträgen (alle Module an), aktive Route markiert', async () => {
    baseApi();
    renderWithProviders(<LocationProbe />, { withShell: true, route: '/verlauf' });
    const nav = await screen.findByRole('navigation', { name: 'Seiten' });
    const routeItems = () => within(nav).getAllByRole('button').filter((b) => b.hasAttribute('data-route'));
    await waitFor(() => expect(routeItems()).toHaveLength(13));
    const items = routeItems();
    const current = items.filter((b) => b.getAttribute('aria-current') === 'page');
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveAttribute('data-route', 'verlauf');
    expect(pageTitle()).toBe('Verlauf');
  });

  it('/ leitet auf /schnelldruck', async () => {
    baseApi();
    renderWithProviders(<LocationProbe />, { withShell: true, route: '/' });
    await waitFor(() => expect(location()).toBe('/schnelldruck'));
    expect(pageTitle()).toBe('Schnelldruck');
  });

  it('Klick in der Seitenleiste navigiert', async () => {
    baseApi();
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck' });
    const nav = await screen.findByRole('navigation', { name: 'Seiten' });
    await user.click(within(nav).getByText('Galerie'));
    expect(location()).toBe('/galerie');
    expect(pageTitle()).toBe('Galerie');
  });

  it('Strg+2 navigiert zu /editor, Strg+, zu den Einstellungen', async () => {
    baseApi();
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck' });
    await screen.findByRole('navigation', { name: 'Seiten' });
    await user.keyboard('{Control>}2{/Control}');
    expect(location()).toBe('/editor');
    expect(pageTitle()).toBe('Editor');
    await user.keyboard('{Control>},{/Control}');
    expect(location()).toBe('/einstellungen');
  });

  it('Strg+Umschalt+V navigiert zum Import aus der Zwischenablage', async () => {
    baseApi();
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck' });
    await screen.findByRole('navigation', { name: 'Seiten' });
    await user.keyboard('{Control>}{Shift>}V{/Shift}{/Control}');
    expect(location()).toBe('/vorlagen?import=zwischenablage');
  });

  it('Einklappen merkt sich den Zustand in localStorage', async () => {
    baseApi();
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck' });
    await screen.findByRole('navigation', { name: 'Seiten' });
    await user.click(screen.getByRole('button', { name: 'Seitenleiste einklappen' }));
    expect(localStorage.getItem(NAV_COLLAPSED_KEY)).toBe('1');
    expect(screen.getByRole('button', { name: 'Seitenleiste ausklappen' })).toBeInTheDocument();
  });

  it('/kompakt wird ohne Rahmen gerendert', async () => {
    baseApi();
    renderWithProviders(<LocationProbe />, { withShell: true, route: '/kompakt' });
    await waitFor(() => expect(location()).toBe('/kompakt'));
    expect(screen.queryByRole('navigation', { name: 'Seiten' })).toBeNull();
    expect(screen.queryByTestId('page-title')).toBeNull();
  });

  it('Dienst nicht erreichbar: Karte mit „Erneut versuchen“', async () => {
    mockApi({ 'GET /api/v1/app': () => Promise.reject(new TypeError('Failed to fetch')) }, { quiet: true });
    globalThis.fetch = vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))) as unknown as typeof fetch;
    renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck' });
    expect(await screen.findByText('Druckdienst nicht erreichbar')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Erneut versuchen' })).toBeInTheDocument();
  });
});

/** App-Fenster nachstellen: pywebview-Brücke mit `retry` (window.AppApi.retry im Druckdienst-Fenster). */
function fakeAppWindow() {
  const retry = vi.fn((_route?: string) => Promise.resolve());
  window.pywebview = { api: { retry } };
  return retry;
}

/** /api/v1/app liefert erst Daten, danach das Ergebnis von `later` (Dienst weg oder neu gestartet). */
function appThen(later: () => unknown) {
  let n = 0;
  return mockApi(
    {
      'GET /api/v1/status': () => fixtures.statusJson,
      'GET /api/v1/app': () => {
        n += 1;
        return n === 1 ? fixtures.appInfo : later();
      },
    },
    { quiet: true },
  );
}

/** Ereignis-Strom öffnen und abbrechen lassen, wie beim Ende des Druckdienstes. */
function dropEvents() {
  act(() => FakeEventSource.latest()?.open());
  act(() => FakeEventSource.latest()?.fail());
}

describe('Wiederverbinden nach Dienst-Ende', () => {
  afterEach(() => {
    delete window.pywebview;
  });

  it('App-Fenster offline: „Erneut versuchen“ startet den Dienst über pywebview neu, gleiche Route', async () => {
    const retry = fakeAppWindow();
    mockApi({ 'GET /api/v1/app': () => Promise.reject(new TypeError('Failed to fetch')) }, { quiet: true });
    globalThis.fetch = vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))) as unknown as typeof fetch;
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/verlauf?suche=ssd' });
    await user.click(await screen.findByRole('button', { name: 'Erneut versuchen' }));
    await waitFor(() => expect(retry).toHaveBeenCalledWith('/verlauf?suche=ssd'));
  });

  it('Browser offline: „Erneut versuchen“ fragt nur neu an, keine pywebview-Brücke nötig', async () => {
    mockApi({ 'GET /api/v1/app': () => Promise.reject(new TypeError('Failed to fetch')) }, { quiet: true });
    globalThis.fetch = vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))) as unknown as typeof fetch;
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck' });
    const button = await screen.findByRole('button', { name: 'Erneut versuchen' });
    const before = (globalThis.fetch as unknown as { mock: { calls: unknown[] } }).mock.calls.length;
    await user.click(button);
    await waitFor(() => expect((globalThis.fetch as unknown as { mock: { calls: unknown[] } }).mock.calls.length).toBeGreaterThan(before));
  });

  it('Dienst endet unter geladener Oberfläche: Karte „nicht erreichbar“ statt totem Fenster', async () => {
    appThen(() => fixtures.appInfo);
    renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck' });
    await screen.findByRole('navigation', { name: 'Seiten' });
    globalThis.fetch = vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))) as unknown as typeof fetch;
    dropEvents();
    expect(await screen.findByText('Druckdienst nicht erreichbar')).toBeInTheDocument();
  });

  it('Dienst mit neuem Token: „Sitzung abgelaufen“ auch bei geladenen Daten, im App-Fenster mit „Neu verbinden“', async () => {
    const retry = fakeAppWindow();
    appThen(() => new MockResponse(401, { error: { kind: 'Token', message: 'Token ungültig', hint: '', exit_code: 1, details: null } }));
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/inventar?tab=verleih' });
    await screen.findByRole('navigation', { name: 'Seiten' });
    dropEvents();
    expect(await screen.findByText('Sitzung abgelaufen')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Neu verbinden' }));
    await waitFor(() => expect(retry).toHaveBeenCalledWith('/inventar?tab=verleih'));
  });

  it('Sitzung abgelaufen im Browser: kein „Neu verbinden“, nur der Hinweis auf p12 app', async () => {
    appThen(() => new MockResponse(401, { error: { kind: 'Token', message: 'Token ungültig', hint: '', exit_code: 1, details: null } }));
    renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck' });
    await screen.findByRole('navigation', { name: 'Seiten' });
    dropEvents();
    expect(await screen.findByText('Sitzung abgelaufen')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Neu verbinden' })).toBeNull();
  });
});

function PrintCommand(props: { onRun: () => void }) {
  useRegisterCommands([{ id: 'druck.aktuell', title: 'Aktuelles Label drucken', group: 'Drucken', run: props.onRun }], [props.onRun]);
  return null;
}

describe('Kommandopalette und Kürzel', () => {
  it('Strg+K öffnet die Palette, „ssd“ findet das Datenträger-Etikett zuerst, Enter navigiert', async () => {
    baseApi();
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck' });
    await screen.findByRole('navigation', { name: 'Seiten' });
    await user.keyboard('{Control>}k{/Control}');
    const input = await screen.findByRole('combobox', { name: 'Befehl suchen' });
    await waitFor(() => expect(input).toHaveFocus());
    await user.type(input, 'ssd');
    const options = within(screen.getByRole('listbox', { name: 'Befehle' })).getAllByRole('option');
    expect(options[0]).toHaveTextContent('Neues SSD-/Datenträger-Etikett');
    expect(options[0]).toHaveAttribute('aria-selected', 'true');
    await user.keyboard('{Enter}');
    await waitFor(() => expect(location()).toBe('/vorlagen?vorlage=datentraeger'));
    await waitFor(() => expect(screen.queryByRole('combobox', { name: 'Befehl suchen' })).toBeNull());
  });

  it('Pfeiltasten wählen, Gehe-zu-Befehle zeigen ihr Kürzel', async () => {
    baseApi();
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck' });
    await screen.findByRole('navigation', { name: 'Seiten' });
    await user.click(screen.getByRole('button', { name: 'Befehle (Strg+K)' }));
    const input = await screen.findByRole('combobox', { name: 'Befehl suchen' });
    await user.type(input, 'gehe zu');
    const list = screen.getByRole('listbox', { name: 'Befehle' });
    expect(within(list).getByText('Gehe zu Editor').closest('[role="option"]')).toHaveTextContent('Strg+2');
    await user.keyboard('{ArrowDown}');
    const options = within(list).getAllByRole('option');
    expect(options[1]).toHaveAttribute('aria-selected', 'true');
  });

  it('Strg+P ruft das registrierte druck.aktuell auf und verhindert den Browser-Druck', async () => {
    baseApi();
    const onRun = vi.fn();
    renderWithProviders(
      <>
        <LocationProbe />
        <PrintCommand onRun={onRun} />
      </>,
      { withShell: true, route: '/schnelldruck' },
    );
    await screen.findByRole('navigation', { name: 'Seiten' });
    const ev = new KeyboardEvent('keydown', { key: 'p', code: 'KeyP', ctrlKey: true, bubbles: true, cancelable: true });
    act(() => {
      window.dispatchEvent(ev);
    });
    expect(ev.defaultPrevented).toBe(true);
    expect(onRun).toHaveBeenCalledTimes(1);
  });

  it('Strg+P ohne registrierten Befehl verhindert trotzdem den Browser-Druck', async () => {
    baseApi();
    renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck' });
    await screen.findByRole('navigation', { name: 'Seiten' });
    const ev = new KeyboardEvent('keydown', { key: 'p', code: 'KeyP', ctrlKey: true, bubbles: true, cancelable: true });
    act(() => {
      window.dispatchEvent(ev);
    });
    expect(ev.defaultPrevented).toBe(true);
  });

  it('Befehl „Warteschlange pausieren“ ruft POST /queue/pause', async () => {
    const api = mockApi(
      {
        'GET /api/v1/status': () => fixtures.statusJson,
        'GET /api/v1/queue': () => ({ jobs: [], paused: false, auto_retry: true, next_try: null, probe: '', waiting_reason: '' }),
        'POST /api/v1/queue/pause': () => ({}),
      },
      { quiet: true },
    );
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck' });
    await screen.findByRole('navigation', { name: 'Seiten' });
    await user.keyboard('{Control>}k{/Control}');
    const input = await screen.findByRole('combobox', { name: 'Befehl suchen' });
    await user.type(input, 'pausieren');
    await waitFor(() =>
      expect(within(screen.getByRole('listbox', { name: 'Befehle' })).getAllByRole('option')[0]).toHaveTextContent(
        'Warteschlange pausieren',
      ),
    );
    await user.keyboard('{Enter}');
    await waitFor(() => expect(api.calls.some((c) => c.method === 'POST' && c.path === '/api/v1/queue/pause')).toBe(true));
  });

  it('Rahmen-Tests bleiben grün, wenn Seiten beliebige Endpunkte abfragen (quiet)', async () => {
    const api = baseApi();
    const errors = vi.spyOn(console, 'error');
    renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck' });
    await screen.findByRole('navigation', { name: 'Seiten' });
    await act(async () => {
      await fetch('/api/v1/history');
    });
    expect(api.unmatched).toContainEqual({ method: 'GET', path: '/api/v1/history' });
    expect(errors).not.toHaveBeenCalledWith(expect.stringContaining('mockApi'));
  });
});

describe('StatusChip', () => {
  it('zeigt view.chip, Klick öffnet Detail, „Status abfragen“ ruft refresh', async () => {
    const api = mockApi(
      {
        'GET /api/v1/status': () => fixtures.statusJson,
        'POST /api/v1/status/refresh': () => ({ ...fixtures.statusJson, view: { ...fixtures.statusJson.view, chip: 'Frisch' } }),
      },
      { quiet: true },
    );
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck' });
    const chip = await screen.findByTestId('status-chip');
    await waitFor(() => expect(chip).toHaveTextContent('Bereit'));
    await user.click(chip);
    const dialog = await findDialogByRole('dialog');
    // Werte als Definitionsliste (Name, Wert) statt Festbreitentext
    const detail = within(dialog).getByTestId('status-detail');
    expect(detail.tagName).toBe('DL');
    expect([...detail.querySelectorAll('dt')].map((e) => e.textContent)).toEqual(['Zustand', 'Verbindung']);
    expect([...detail.querySelectorAll('dd')].map((e) => e.textContent)).toEqual(['bereit', 'bt:COM5']);
    await user.click(within(dialog).getByRole('button', { name: 'Status abfragen', hidden: true }));
    await waitFor(() => expect(api.calls.some((c) => c.method === 'POST' && c.path === '/api/v1/status/refresh')).toBe(true));
    await waitFor(() => expect(screen.getByTestId('status-chip')).toHaveTextContent('Frisch'));
  });

  it('Fehler beim Abfragen zeigt Meldung mit Hinweis', async () => {
    const { MockResponse } = await import('../../test/utils');
    mockApi(
      {
        'GET /api/v1/status': () => fixtures.statusJson,
        'POST /api/v1/status/refresh': () =>
          new MockResponse(503, { error: { kind: 'PrinterOffline', message: 'Drucker aus', hint: 'Einschalten', exit_code: 5, details: null } }),
      },
      { quiet: true },
    );
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck' });
    await user.click(await screen.findByTestId('status-chip'));
    const dialog = await findDialogByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Status abfragen', hidden: true }));
    expect(await within(dialog).findByText('Drucker aus')).toBeInTheDocument();
    expect(within(dialog).getByText('Einschalten')).toBeInTheDocument();
  });
});

describe('Seitentitel', () => {
  it('Unterseiten im Homelab: Pfad „Homelab › Proxmox“, page-title ist der letzte Teil', async () => {
    baseApi();
    renderWithProviders(<LocationProbe />, { withShell: true, route: '/homelab/proxmox' });
    const path = await screen.findByRole('navigation', { name: 'Pfad' });
    expect(path).toHaveTextContent('Homelab›Proxmox');
    expect(within(path).getByRole('link', { name: 'Homelab' })).toHaveAttribute('href', '/homelab');
    expect(pageTitle()).toBe('Proxmox');
  });

  it('Kopfzeile zeigt den Titel aus ROUTES, Strg+8 gehört fest zur Statistik', async () => {
    baseApi();
    renderWithProviders(<LocationProbe />, { withShell: true, route: '/datentraeger?tab=ssh' });
    await screen.findByRole('navigation', { name: 'Seiten' });
    expect(pageTitle()).toBe('Datenträger');
    fireEvent.keyDown(window, { key: '8', code: 'Digit8', ctrlKey: true });
    expect(location()).toBe('/statistik');
  });
});
