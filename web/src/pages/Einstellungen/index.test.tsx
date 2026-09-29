import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { LocationProbe, MockResponse, mockApi, renderWithProviders } from '../../test/utils';
import { baseSettingsRoutes, makeSettings } from './testFixtures';
import EinstellungenPage from './index';

describe('/einstellungen: generische Felder', () => {
  it('rendert Abschnitte und Felder, Schalter umlegen aktiviert Speichern, PATCH sendet nur den geänderten Schlüssel', async () => {
    let sentChanges: Record<string, unknown> | null = null;
    mockApi(
      baseSettingsRoutes({
        'PATCH /api/v1/settings': ({ body }) => {
          sentChanges = (body as { changes: Record<string, unknown> }).changes;
          return makeSettings();
        },
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });

    const toggle = await screen.findByRole('switch', { name: 'Nur mit Strg+Enter drucken' });
    expect(screen.queryByRole('button', { name: 'Speichern' })).not.toBeInTheDocument();
    await user.click(toggle);

    const saveButtons = screen.getAllByRole('button', { name: 'Speichern' });
    expect(saveButtons.length).toBeGreaterThan(0);
    await user.click(saveButtons[0] as HTMLElement);

    await waitFor(() => expect(sentChanges).toEqual({ 'app.ctrl_enter_only': true }));
  });

  it('zeigt eine 422-Fehlermeldung an der betroffenen Karte', async () => {
    mockApi(
      baseSettingsRoutes({
        'PATCH /api/v1/settings': () =>
          new MockResponse(422, { error: { kind: 'Validierung', message: 'Web-Port außerhalb des Bereichs', hint: '', exit_code: 1, details: null } }),
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });

    const toggle = await screen.findByRole('switch', { name: 'Nur mit Strg+Enter drucken' });
    await user.click(toggle);
    const saveButtons = screen.getAllByRole('button', { name: 'Speichern' });
    await user.click(saveButtons[0] as HTMLElement);

    expect(await screen.findByText('Web-Port außerhalb des Bereichs')).toBeInTheDocument();
  });

  it('restart-Feld zeigt den Neustart-Hinweis genau einmal als Hilfezeile, experimental-Feld zeigt Plakette', async () => {
    mockApi(baseSettingsRoutes());
    renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });

    await waitFor(() => expect(document.getElementById('allgemein')).not.toBeNull());
    const card = document.getElementById('allgemein') as HTMLElement;
    const portRow = within(card).getByText('Web-Port').closest('.p12-field-row') as HTMLElement;
    // Die Feldübersetzung (web_port.help) nennt den Neustart schon: keine zweite Zeile, keine Plakette.
    expect(within(portRow).getAllByText('wirkt nach Neustart des Druckdienstes')).toHaveLength(1);
    expect(portRow.querySelector('.fui-Badge')).toBeNull();

    const bleRow = within(card).getByText('BLE-Suche').closest('.p12-field-row') as HTMLElement;
    expect(within(bleRow).getByText('experimentell')).toBeInTheDocument();
  });

  it('leere Textfelder zeigen „Standard: …“ bzw. „Nicht gesetzt“ als Platzhalter', async () => {
    const settings = makeSettings();
    const fields = settings.sections.flatMap((s) => s.fields);
    const dir = fields.find((f) => f.key === 'templates.dir');
    if (dir) dir.value = null;
    const source = fields.find((f) => f.key === 'update.source');
    if (source) {
      source.value = '';
      source.default = 'github:essendyx/tapesmith';
    }
    mockApi(baseSettingsRoutes({ 'GET /api/v1/settings': () => settings }));
    renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });

    expect(await screen.findByRole('textbox', { name: 'Vorlagenordner' })).toHaveAttribute('placeholder', 'Nicht gesetzt');
    const sourceBox = await screen.findByRole('textbox', { name: 'Update-Quelle' });
    expect(sourceBox).toHaveAttribute('placeholder', 'Standard: github:essendyx/tapesmith');
  });

  it('Suche „port“ blendet nicht passende Felder aus', async () => {
    mockApi(baseSettingsRoutes());
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });

    await waitFor(() => expect(document.getElementById('allgemein')).not.toBeNull());
    const card = document.getElementById('allgemein') as HTMLElement;
    expect(within(card).getByText('Web-Port')).toBeInTheDocument();
    expect(within(card).getByText('Design')).toBeInTheDocument();

    const search = screen.getByRole('textbox', { name: 'Einstellung suchen' });
    await user.type(search, 'port');

    expect(within(card).getByText('Web-Port')).toBeInTheDocument();
    expect(within(card).queryByText('Design')).not.toBeInTheDocument();
  });

  it('Route /einstellungen#modul-datentraeger springt zur Einstellungskarte des Moduls', async () => {
    mockApi(baseSettingsRoutes());
    const spy = vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(() => {});
    renderWithProviders(<EinstellungenPage />, { route: '/einstellungen#modul-datentraeger' });

    await waitFor(() => expect(document.getElementById('modul-datentraeger')).not.toBeNull());
    await waitFor(() => expect(spy).toHaveBeenCalled());
    spy.mockRestore();
  });

  it('Hotkey-Feld zeichnet Strg+Alt+K als „Ctrl+Alt+K“ auf', async () => {
    mockApi(baseSettingsRoutes());
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });

    const field = await screen.findByLabelText('Schnelldruck-Kürzel');
    await user.click(field);
    await user.keyboard('{Control>}{Alt>}k{/Alt}{/Control}');
    expect(field).toHaveValue('Ctrl+Alt+K');
  });

  it('ssh.hosts-Editor: Zeile hinzufügen und speichern sendet eine Liste von Objekten', async () => {
    let sentChanges: Record<string, unknown> | null = null;
    mockApi(
      baseSettingsRoutes({
        'PATCH /api/v1/settings': ({ body }) => {
          sentChanges = (body as { changes: Record<string, unknown> }).changes;
          return makeSettings();
        },
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });

    await waitFor(() => expect(document.getElementById('modul-datentraeger')).not.toBeNull());
    const sshCard = document.getElementById('modul-datentraeger') as HTMLElement;
    await user.click(within(sshCard).getByRole('button', { name: 'Zeile hinzufügen' }));
    await user.type(within(sshCard).getByRole('textbox', { name: 'Name' }), 'nas');
    await user.type(within(sshCard).getByRole('textbox', { name: 'Host' }), '192.0.2.10');

    await user.click(within(sshCard).getByRole('button', { name: 'Speichern' }));

    await waitFor(() => expect(sentChanges).not.toBeNull());
    const hosts = sentChanges?.['ssh.hosts'] as unknown as Array<Record<string, unknown>>;
    expect(Array.isArray(hosts)).toBe(true);
    expect(hosts[0]).toMatchObject({ name: 'nas', host: '192.0.2.10' });
  });

  it('unbeteiligte Karte mit 404 stört die restliche Seite nicht (GET /backups)', async () => {
    const routes = baseSettingsRoutes();
    delete routes['GET /api/v1/backups'];
    mockApi(routes, { quiet: true });
    renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });

    await waitFor(() => expect(document.getElementById('allgemein')).not.toBeNull());
    expect(within(document.getElementById('allgemein') as HTMLElement).getByText('Web-Port')).toBeInTheDocument();
    expect(await screen.findByRole('switch', { name: 'Nur mit Strg+Enter drucken' })).toBeInTheDocument();
  });
});

describe('/einstellungen: Verweis-Karte Zugriff', () => {
  it('zeigt die Karte „Zugriff und Automatisierung“, „Öffnen“ navigiert nach /zugriff', async () => {
    mockApi(baseSettingsRoutes(), { quiet: true });
    const { user } = renderWithProviders(
      <>
        <LocationProbe />
        <EinstellungenPage />
      </>,
      { route: '/einstellungen' },
    );

    expect(await screen.findByRole('heading', { name: 'Zugriff und Automatisierung' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Öffnen' }));
    expect(screen.getByTestId('location').textContent).toBe('/zugriff');
  });
});

describe('/einstellungen: SpinButton für Zahlenfelder', () => {
  it.each([
    ['80', 1024],
    ['70000', 65535],
  ])('web.port: Eingabe %s wird auf die Grenze %d geklemmt (min/max aus dem Feld)', async (typed, expected) => {
    let sentChanges: Record<string, unknown> | null = null;
    mockApi(
      baseSettingsRoutes({
        'PATCH /api/v1/settings': ({ body }) => {
          sentChanges = (body as { changes: Record<string, unknown> }).changes;
          return makeSettings();
        },
      }),
    );
    const { user } = renderWithProviders(<EinstellungenPage />, { route: '/einstellungen' });

    const spin = await screen.findByRole('spinbutton', { name: 'Web-Port' });
    expect(spin).toHaveValue('8712');
    expect(spin).toHaveAttribute('aria-valuemin', '1024');
    expect(spin).toHaveAttribute('aria-valuemax', '65535');

    await user.clear(spin);
    await user.type(spin, typed);
    await user.tab();

    await waitFor(() => expect(spin).toHaveValue(String(expected)));
    const card = document.getElementById('allgemein') as HTMLElement;
    await user.click(within(card).getByRole('button', { name: 'Speichern' }));
    await waitFor(() => expect(sentChanges).toEqual({ 'web.port': expected }));
  });
});
