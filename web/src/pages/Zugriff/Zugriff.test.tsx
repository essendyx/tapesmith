/** Seite „Zugriff“: Tokens, LAN, Familie, MCP, Hotfolder, MQTT, Telegram, Zusatzdienste. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { findDialog, findDialogByRole, mockApi, MockResponse, renderWithProviders, SLOW_UI_MS } from '../../test/utils';
import { baseAccessRoutes, makeAccess } from './testFixtures';
import ZugriffPage from './index';

function renderPage(overrides?: Parameters<typeof baseAccessRoutes>[0]) {
  const api = mockApi(baseAccessRoutes(overrides));
  const utils = renderWithProviders(<ZugriffPage />, { route: '/zugriff' });
  return { api, ...utils };
}

const CARD_TITLES = [
  'API-Tokens',
  'LAN-Freigabe',
  'Familienseite',
  'MCP für Claude',
  'Hotfolder',
  'Home Assistant (MQTT)',
  'Telegram',
  'Zusatzdienste',
];

beforeEach(() => {
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn(() => Promise.resolve()) },
    configurable: true,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('Seite Zugriff: Grundgerüst', () => {
  it('zeigt alle acht Karten-Überschriften und die Token-Tabelle, nie ein Feld secret', async () => {
    renderPage();
    for (const title of CARD_TITLES) {
      expect(await screen.findByRole('heading', { name: title })).toBeInTheDocument();
    }
    expect(screen.getByText('Handy')).toBeInTheDocument();
    expect(screen.getAllByText('Familie').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Verwaltung').length).toBeGreaterThan(0);
    expect(screen.queryByText(/"secret"/)).toBeNull();
  });

  it('403 auf GET /api/v1/access zeigt die Hinweiskarte „Nur mit Verwaltungs-Token“', async () => {
    renderPage({
      'GET /api/v1/access': () =>
        new MockResponse(403, { error: { kind: 'Forbidden', message: 'Keine Berechtigung für diese Aktion', hint: '', exit_code: 1, details: null } }),
    });
    expect(await screen.findByText('Nur mit Verwaltungs-Token')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'API-Tokens' })).toBeNull();
  });

  it('Zusatzdienste: mqtt mit error zeigt „Fehler:“ und den Text', async () => {
    renderPage({
      'GET /api/v1/access': () =>
        makeAccess({
          addons: [
            { name: 'hotfolder', running: false, error: null, detail: 'aus' },
            { name: 'mqtt', running: false, error: 'Broker nicht erreichbar', detail: '' },
            { name: 'telegram', running: true, error: null, detail: 'verbunden' },
          ],
        }),
    });
    await screen.findByRole('heading', { name: 'Zusatzdienste' });
    expect(screen.getByText(/Fehler: Broker nicht erreichbar/)).toBeInTheDocument();
  });

  it('Zusatzdienste: Addon "update" zeigt „Update“ mit Status, ohne Farbe allein', async () => {
    renderPage({
      'GET /api/v1/access': () =>
        makeAccess({
          addons: [
            { name: 'hotfolder', running: false, error: null, detail: 'aus' },
            { name: 'mqtt', running: false, error: null, detail: 'aus' },
            { name: 'telegram', running: false, error: null, detail: 'aus' },
            { name: 'update', running: true, error: null, detail: 'bereit' },
          ],
        }),
    });
    await screen.findByRole('heading', { name: 'Zusatzdienste' });
    expect(screen.getByText('Update')).toBeInTheDocument();
    expect(screen.getByText(/läuft/)).toBeInTheDocument();
  });
});

describe('Tokens', () => {
  it('Neues Token: Name „Handy“, Rolle Familie, Anlegen sendet POST, zeigt Token und Familienlink, verschwindet nach Schließen', async () => {
    const { api, user } = renderPage({
      'POST /api/v1/access/tokens': () => ({
        token: { id: 'x1', name: 'Handy', role: 'familie', role_label: 'Familie', created: '2026-09-28T10:00:00', last_used: null, hint: 'p12_x1_...' },
        secret: 'p12_x1_geheimwert',
        family_urls: ['http://192.0.2.5:8712/familie#t=p12_x1_geheimwert'],
      }),
    });
    await screen.findByRole('heading', { name: 'API-Tokens' });
    const getCallsBefore = api.calls.filter((c) => c.method === 'GET' && c.path === '/api/v1/access').length;
    await user.click(screen.getByRole('button', { name: 'Neues Token' }));
    const dialog = await findDialog('Neues Token');
    await user.type(within(dialog).getByLabelText('Name'), 'Handy');
    await user.click(within(dialog).getByRole('radio', { name: /Familie/, hidden: true }));
    await user.click(within(dialog).getByRole('button', { name: 'Anlegen', hidden: true }));

    await waitFor(() =>
      expect(api.calls.some((c) => c.method === 'POST' && c.path === '/api/v1/access/tokens')).toBe(true),
    );
    const call = api.calls.find((c) => c.method === 'POST' && c.path === '/api/v1/access/tokens');
    expect(call?.body).toEqual({ name: 'Handy', role: 'familie' });

    expect(await screen.findByDisplayValue('p12_x1_geheimwert')).toBeInTheDocument();
    expect(screen.getByText('http://192.0.2.5:8712/familie#t=p12_x1_geheimwert')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Schließen' }));

    expect(screen.queryByDisplayValue('p12_x1_geheimwert')).toBeNull();
    await waitFor(() =>
      expect(api.calls.filter((c) => c.method === 'GET' && c.path === '/api/v1/access').length).toBeGreaterThan(getCallsBefore),
    );
  }, SLOW_UI_MS);

  it('Widerrufen: Abbrechen sendet nichts', async () => {
    const { api, user } = renderPage();
    await screen.findByRole('heading', { name: 'API-Tokens' });
    const row = screen.getByText('Handy').closest('tr') as HTMLElement;

    await user.click(within(row).getByRole('button', { name: /^Widerrufen: / }));
    const dialog = await findDialogByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Abbrechen', hidden: true }));
    expect(api.calls.some((c) => c.method === 'DELETE')).toBe(false);
  }, SLOW_UI_MS);

  it('Widerrufen: Bestätigen sendet DELETE', async () => {
    const { api, user } = renderPage();
    await screen.findByRole('heading', { name: 'API-Tokens' });
    const row = screen.getByText('Handy').closest('tr') as HTMLElement;

    await user.click(within(row).getByRole('button', { name: /^Widerrufen: / }));
    const dialog = await findDialogByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Widerrufen', hidden: true }));
    await waitFor(() => expect(api.calls.some((c) => c.method === 'DELETE' && c.path === '/api/v1/access/tokens/a1b2c3d4')).toBe(true));
  }, SLOW_UI_MS);
});

describe('LAN-Freigabe', () => {
  it('Schalter einschalten und Speichern sendet genau {"changes": {"lan.enabled": true}}; restart_needed zeigt den Hinweis', async () => {
    let sentBody: unknown = null;
    const { user } = renderPage({
      'PATCH /api/v1/access/settings': ({ body }) => {
        sentBody = body;
        return makeAccess({ lan: { ...makeAccess().lan, enabled: true, restart_needed: true } });
      },
    });
    await screen.findByRole('heading', { name: 'LAN-Freigabe' });
    await user.click(screen.getByLabelText('Im Heimnetz freigeben'));
    await user.click(screen.getByRole('button', { name: 'Speichern' }));

    await waitFor(() => expect(sentBody).toEqual({ changes: { 'lan.enabled': true } }));
    expect(await screen.findByText(/Neustart des Druckdienstes nötig/)).toBeInTheDocument();
  });

  it('Erlaubte Netze als Textarea: zwei Zeilen werden als Liste gesendet, leere Zeilen entfernt', async () => {
    let sentBody: unknown = null;
    const { user } = renderPage({
      'PATCH /api/v1/access/settings': ({ body }) => {
        sentBody = body;
        return makeAccess();
      },
    });
    await screen.findByRole('heading', { name: 'LAN-Freigabe' });
    const textarea = screen.getByLabelText('Erlaubte Netze');
    await user.clear(textarea);
    await user.type(textarea, '192.0.2.0/24\n\n198.51.100.0/24\n');
    await user.tab();
    await user.click(screen.getByRole('button', { name: 'Speichern' }));

    await waitFor(() =>
      expect(sentBody).toEqual({ changes: { 'lan.allowed_networks': ['192.0.2.0/24', '198.51.100.0/24'] } }),
    );
  });

  it('Server-Validierungsfehler (422): Meldung sichtbar, Eingaben bleiben stehen', async () => {
    const { user } = renderPage({
      'PATCH /api/v1/access/settings': () =>
        new MockResponse(422, { error: { kind: 'Validierung', message: 'lan.bind ungültig', hint: '', exit_code: 1, details: null } }),
    });
    await screen.findByRole('heading', { name: 'LAN-Freigabe' });
    const bindInput = screen.getByLabelText('Adresse, an die gebunden wird');
    await user.clear(bindInput);
    await user.type(bindInput, '999.999.999.999');
    await user.click(screen.getByRole('button', { name: 'Speichern' }));

    expect(await screen.findByText('lan.bind ungültig')).toBeInTheDocument();
    expect(bindInput).toHaveValue('999.999.999.999');
  });
});

describe('Familie', () => {
  it('Kontrollkästchen „vorratsdose“ abwählen und speichern: family.templates ohne vorratsdose, Reihenfolge erhalten', async () => {
    let sentBody: unknown = null;
    const { user } = renderPage({
      'PATCH /api/v1/access/settings': ({ body }) => {
        sentBody = body;
        return makeAccess();
      },
    });
    await screen.findByRole('heading', { name: 'Familienseite' });
    const card = document.getElementById('familie') as HTMLElement;
    await user.click(within(card).getByRole('checkbox', { name: /vorratsdose/ }));
    await user.click(within(card).getByRole('button', { name: 'Speichern' }));

    await waitFor(() =>
      expect(sentBody).toEqual({ changes: { 'family.templates': ['gefriergut', 'geoeffnet-am'] } }),
    );
  });
});

describe('MQTT', () => {
  it('Passwort setzen: Dialog, Eingabe, PUT /access/secrets/mqtt {"value": "pw"}; Passwort erscheint danach nirgends im DOM', async () => {
    const { api, user } = renderPage({
      'PUT /api/v1/access/secrets/mqtt': () => ({ set: true, describe: 'Windows-Anmeldeinformationen tapesmith/mqtt' }),
    });
    await screen.findByRole('heading', { name: 'Home Assistant (MQTT)' });
    await user.click(screen.getByRole('button', { name: 'Passwort setzen' }));
    const dialog = await findDialog('MQTT-Passwort setzen');
    await user.type(within(dialog).getByLabelText('Passwort'), 'pw');
    await user.click(within(dialog).getByRole('button', { name: 'Speichern', hidden: true }));

    await waitFor(() => expect(api.calls.some((c) => c.method === 'PUT' && c.path === '/api/v1/access/secrets/mqtt')).toBe(true));
    const call = api.calls.find((c) => c.method === 'PUT' && c.path === '/api/v1/access/secrets/mqtt');
    expect(call?.body).toEqual({ value: 'pw' });
    expect(screen.queryByDisplayValue('pw')).toBeNull();
    expect(screen.queryByText('pw')).toBeNull();
  }, SLOW_UI_MS);
});

describe('Telegram', () => {
  it('Testnachricht senden: Antwort ok:false zeigt die Fehlermeldung', async () => {
    const { user } = renderPage({
      'POST /api/v1/access/telegram/test': () => ({ ok: false, error: 'Chat-ID fehlt' }),
    });
    await screen.findByRole('heading', { name: 'Telegram' });
    await user.click(screen.getByRole('button', { name: 'Testnachricht senden' }));
    expect(await screen.findByText('Chat-ID fehlt')).toBeInTheDocument();
  });

  it('token_ref file:… : kein Knopf „Token setzen“, stattdessen Hinweis mit token_describe', async () => {
    renderPage({
      'GET /api/v1/access': () =>
        makeAccess({
          telegram: {
            ...makeAccess().telegram,
            token_ref: 'file:C:\\Tokens\\.telegram_bot_token',
            token_describe: 'Datei C:\\Tokens\\.telegram_bot_token',
          },
        }),
    });
    await screen.findByRole('heading', { name: 'Telegram' });
    expect(screen.queryByRole('button', { name: 'Token setzen' })).toBeNull();
    expect(screen.getByText(/Token kommt aus Datei/)).toBeInTheDocument();
  });
});
