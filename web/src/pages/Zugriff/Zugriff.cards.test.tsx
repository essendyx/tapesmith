/** Karten der Seite Zugriff im einheitlichen Raster: Vorlagenauswahl, Zahlenfelder, Kopieren, Kartenaktionen. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { mockApi, renderWithProviders, SLOW_UI_MS } from '../../test/utils';
import type { Language } from '../../i18n';
import { baseAccessRoutes, makeAccess } from './testFixtures';
import ZugriffPage from './index';

beforeEach(() => {
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn(() => Promise.resolve()) },
    configurable: true,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderPage(routes = baseAccessRoutes(), language: Language = 'de') {
  const api = mockApi(routes);
  const utils = renderWithProviders(<ZugriffPage />, { route: '/zugriff', language });
  return { api, ...utils };
}

function card(id: string): HTMLElement {
  return document.getElementById(id) as HTMLElement;
}

function capturePatch(): { routes: ReturnType<typeof baseAccessRoutes>; sent: () => unknown } {
  let body: unknown = null;
  const routes = baseAccessRoutes({
    'PATCH /api/v1/access/settings': ({ body: b }) => {
      body = b;
      return makeAccess();
    },
  });
  return { routes, sent: () => body };
}

describe('Vorlagenauswahl (Familienseite)', () => {
  it('zeigt die Anzahl, filtert per Suche und „Alle abwählen“ leert die Auswahl', async () => {
    const patch = capturePatch();
    const { user } = renderPage(patch.routes);
    await screen.findByRole('heading', { name: 'Familienseite' });
    const family = card('familie');

    expect(within(family).getByText('3 von 5 gewählt')).toBeInTheDocument();
    // Gespeicherte Vorlagen stehen oben.
    const names = within(family)
      .getAllByRole('checkbox')
      .map((c) => (c.closest('label') ?? c.parentElement)?.textContent ?? '');
    expect(names[0]).toMatch(/gefriergut/);
    expect(names[3]).toMatch(/schule|eigentum/);

    await user.type(within(family).getByRole('searchbox', { name: 'Suchen in Freigegebene Vorlagen' }), 'schul');
    expect(within(family).getAllByRole('checkbox')).toHaveLength(1);
    expect(within(family).getByRole('checkbox', { name: /schule/ })).not.toBeChecked();

    await user.clear(within(family).getByRole('searchbox', { name: 'Suchen in Freigegebene Vorlagen' }));
    await user.type(within(family).getByRole('searchbox', { name: 'Suchen in Freigegebene Vorlagen' }), 'gibtesnicht');
    expect(within(family).queryAllByRole('checkbox')).toHaveLength(0);
    expect(within(family).getByText('Keine Vorlage passt zu „gibtesnicht“')).toBeInTheDocument();

    await user.click(within(family).getByRole('button', { name: 'Alle abwählen: Freigegebene Vorlagen' }));
    expect(within(family).getByText('0 von 5 gewählt')).toBeInTheDocument();
    expect(within(family).getByRole('button', { name: 'Alle abwählen: Freigegebene Vorlagen' })).toBeDisabled();
    await user.click(within(family).getByRole('button', { name: 'Speichern: Familienseite' }));
    await waitFor(() => expect(patch.sent()).toEqual({ changes: { 'family.templates': [] } }));
  }, SLOW_UI_MS);

  it('Tastatur: Leertaste auf einem Kontrollkästchen wählt die Vorlage, Verwerfen setzt zurück', async () => {
    const { user } = renderPage();
    await screen.findByRole('heading', { name: 'Familienseite' });
    const family = card('familie');
    const schule = within(family).getByRole('checkbox', { name: /schule/ });
    schule.focus();
    await user.keyboard(' ');
    expect(schule).toBeChecked();
    expect(within(family).getByText('4 von 5 gewählt')).toBeInTheDocument();

    const discard = within(family).getByRole('button', { name: 'Verwerfen: Familienseite' });
    discard.focus();
    await user.keyboard('{Enter}');
    expect(within(family).getByText('3 von 5 gewählt')).toBeInTheDocument();
    expect(within(family).queryByRole('button', { name: 'Speichern: Familienseite' })).toBeNull();
  }, SLOW_UI_MS);

  it('MQTT: ohne Auswahl „alle erlaubt“, eigene eindeutige Namen für Suche und Abwählen', async () => {
    renderPage();
    await screen.findByRole('heading', { name: 'Home Assistant (MQTT)' });
    const mqtt = card('mqtt');
    expect(within(mqtt).getByText('Keine gewählt, alle erlaubt')).toBeInTheDocument();
    expect(within(mqtt).getByRole('button', { name: 'Alle abwählen: Erlaubte Vorlagen' })).toBeDisabled();
    expect(screen.getAllByRole('searchbox', { name: 'Suchen in Erlaubte Vorlagen' })).toHaveLength(1);
    expect(screen.getAllByRole('searchbox', { name: 'Suchen in Freigegebene Vorlagen' })).toHaveLength(1);
  });
});

describe('Zahlenfelder mit Einheit', () => {
  it('Hotfolder: Pfeil hoch zählt um 0,5 s weiter und wird gespeichert', async () => {
    const patch = capturePatch();
    const { user } = renderPage(patch.routes);
    await screen.findByRole('heading', { name: 'Hotfolder' });
    const hot = card('hotfolder');
    const poll = within(hot).getByRole('spinbutton', { name: 'Abfrage-Intervall' });
    expect(poll).toHaveValue('2');
    expect(poll).toHaveAccessibleDescription('s');
    poll.focus();
    await user.keyboard('{ArrowUp}');
    expect(poll).toHaveValue('2,5');
    await user.click(within(hot).getByRole('button', { name: 'Speichern: Hotfolder' }));
    await waitFor(() => expect(patch.sent()).toEqual({ changes: { 'hotfolder.poll_s': 2.5 } }));
  }, SLOW_UI_MS);

  it('Telegram: Eingabe über der Obergrenze wird beim Verlassen geklemmt', async () => {
    const patch = capturePatch();
    const { user } = renderPage(patch.routes);
    await screen.findByRole('heading', { name: 'Telegram' });
    const tg = card('telegram');
    const offline = within(tg).getByRole('spinbutton', { name: 'Offline-Meldung nach' });
    await user.clear(offline);
    await user.type(offline, '99999');
    await user.tab();
    expect(offline).toHaveValue('1440');
    await user.click(within(tg).getByRole('button', { name: 'Speichern: Telegram' }));
    await waitFor(() => expect(patch.sent()).toEqual({ changes: { 'telegram.offline_min': 1440 } }));
  }, SLOW_UI_MS);

  it('Hotfolder: leeres Ordnerfeld zeigt den Standardordner als Platzhalter', async () => {
    renderPage();
    await screen.findByRole('heading', { name: 'Hotfolder' });
    expect(within(card('hotfolder')).getByRole('textbox', { name: 'Ordner' })).toHaveAttribute('placeholder', 'Standard: C:/App/hotfolder');
  });
});

describe('MCP: Kopieren', () => {
  it('„Befehl kopieren“ legt den vollständigen Befehl für Claude Code in die Zwischenablage', async () => {
    const { user } = renderPage();
    await screen.findByRole('heading', { name: 'MCP für Claude' });
    await user.click(within(card('mcp')).getByRole('button', { name: 'Befehl kopieren' }));
    // user-event legt eine eigene Zwischenablage an: dort nachlesen.
    await waitFor(async () => expect(await navigator.clipboard.readText()).toBe('claude mcp add p12 -- C:/App/python.exe -m tapesmith.cli mcp'));
    await user.click(within(card('mcp')).getByRole('button', { name: 'Adresse kopieren' }));
    await waitFor(async () => expect(await navigator.clipboard.readText()).toBe('http://127.0.0.1:8712/mcp'));
  });
});

describe('Kartenaktionen im Kopf', () => {
  it('Telegram: „Testnachricht senden“ immer da, nach einer Änderung stehen Speichern und Verwerfen davor', async () => {
    const { user } = renderPage();
    await screen.findByRole('heading', { name: 'Telegram' });
    const tg = card('telegram');
    const head = within(tg).getByRole('heading', { name: 'Telegram' }).parentElement?.parentElement as HTMLElement;
    expect(within(head).getAllByRole('button').map((b) => b.textContent)).toEqual(['Testnachricht senden']);

    await user.click(within(tg).getByRole('switch', { name: 'Meldungen senden' }));
    expect(within(head).getAllByRole('button').map((b) => b.textContent)).toEqual(['Speichern', 'Verwerfen', 'Testnachricht senden']);
  });

  it('mehrere Karten mit Änderungen: jeder Speichern-Knopf hat einen eigenen Namen', async () => {
    const { user } = renderPage();
    await screen.findByRole('heading', { name: 'Telegram' });
    await user.click(within(card('mqtt')).getByRole('switch', { name: 'MQTT verbinden' }));
    await user.click(within(card('hotfolder')).getByRole('switch', { name: 'Hotfolder überwachen' }));
    for (const title of ['Home Assistant (MQTT)', 'Hotfolder']) {
      expect(screen.getAllByRole('button', { name: `Speichern: ${title}` })).toHaveLength(1);
      expect(screen.getAllByRole('button', { name: `Verwerfen: ${title}` })).toHaveLength(1);
    }
  });

  it('Ruhezeiten ausschalten blendet den Zeitraum aus und sendet null', async () => {
    const patch = capturePatch();
    const { user } = renderPage(patch.routes);
    await screen.findByRole('heading', { name: 'Telegram' });
    const tg = card('telegram');
    expect(within(tg).getByLabelText('Ruhezeit Beginn')).toHaveValue('22:00');
    await user.click(within(tg).getByRole('switch', { name: 'Ruhezeiten' }));
    expect(within(tg).queryByLabelText('Ruhezeit Beginn')).toBeNull();
    await user.click(within(tg).getByRole('button', { name: 'Speichern: Telegram' }));
    await waitFor(() => expect(patch.sent()).toEqual({ changes: { 'telegram.quiet_hours': null } }));
  }, SLOW_UI_MS);
});

describe.each(['de', 'en'] as Language[])('Karten: axe (%s)', (language) => {
  it('mit ungespeicherten Änderungen und gefilterter Vorlagenliste ohne Befund', async () => {
    const { user, container } = renderPage(baseAccessRoutes(), language);
    await screen.findByRole('heading', { level: 2, name: language === 'de' ? 'Familienseite' : 'Family page' });
    const family = card('familie');
    await user.type(within(family).getAllByRole('searchbox')[0] as HTMLElement, 'ge');
    await user.click(within(family).getAllByRole('checkbox')[0] as HTMLElement);
    await user.click(within(card('telegram')).getAllByRole('switch')[0] as HTMLElement);
    await expectNoA11yViolations(container);
  }, SLOW_UI_MS);
});

describe('Karten: Englisch', () => {
  it('Vorlagenauswahl, Einheiten und Kartenaktionen sind englisch', async () => {
    const { user } = renderPage(baseAccessRoutes(), 'en');
    await screen.findByRole('heading', { name: 'Family page' });
    const family = card('familie');
    expect(within(family).getByText('3 of 5 selected')).toBeInTheDocument();
    expect(within(family).getByRole('button', { name: 'Clear all: Shared templates' })).toBeEnabled();
    expect(within(card('mqtt')).getByText('None selected, all allowed')).toBeInTheDocument();
    expect(within(card('hotfolder')).getByRole('spinbutton', { name: 'Poll interval' })).toHaveValue('2');
    await user.click(within(family).getAllByRole('checkbox')[0] as HTMLElement);
    expect(within(family).getByRole('button', { name: 'Save: Family page' })).toBeInTheDocument();
    expect(within(family).getByRole('button', { name: 'Discard: Family page' })).toBeInTheDocument();
    expect(within(card('telegram')).getByRole('button', { name: 'Send test message' })).toBeInTheDocument();
  });
});

describe('Leere und fehlende Angaben', () => {
  it('ohne Zusatzdienste steht ein Hinweis statt einer leeren Karte', async () => {
    renderPage(baseAccessRoutes({ 'GET /api/v1/access': () => makeAccess({ addons: [] }) }));
    await screen.findByRole('heading', { name: 'Zusatzdienste' });
    expect(within(card('dienste')).getByText('Noch keine Zusatzdienste gestartet.')).toBeInTheDocument();
  });

  it('Telegram ohne Token-Quelle: Plakette „Fehlt“ und Hinweis auf die Einstellung, kein Knopf', async () => {
    renderPage(
      baseAccessRoutes({
        'GET /api/v1/access': () =>
          makeAccess({ telegram: { ...makeAccess().telegram, token_ref: null, token_set: false, token_describe: 'nicht gesetzt' } }),
      }),
    );
    await screen.findByRole('heading', { name: 'Telegram' });
    const tg = card('telegram');
    expect(within(tg).getByText('Fehlt')).toBeInTheDocument();
    expect(within(tg).getByText('Keine Quelle festgelegt (Einstellung telegram.token_ref).')).toBeInTheDocument();
    expect(within(tg).queryByRole('button', { name: 'Token setzen' })).toBeNull();
  });
});
