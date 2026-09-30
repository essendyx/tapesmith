import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { SecretsCard } from './SecretsCard';
import { mockApi, renderWithProviders } from '../../../test/utils';
import { makeSecrets } from '../../../test/secretFixtures';

function card() {
  return screen.getByRole('region', { name: 'Tokens und Passwörter' });
}

describe('SecretsCard', () => {
  it('listet alle Slots, auch die ausgeschalteter Module, mit Weg zur Einrichtung', async () => {
    mockApi({
      'GET /api/v1/secrets': () =>
        makeSecrets([
          {
            id: 'paperless',
            source: 'extern',
            set: true,
            module_enabled: false,
          },
          {
            id: 'proxmox:pve1',
            label: 'Proxmox pve1',
            module: 'proxmox',
            module_enabled: true,
            target: '/einstellungen?abschnitt=modul-proxmox',
          },
        ]),
    });
    renderWithProviders(<SecretsCard />);
    expect(await within(card()).findByText('Paperless')).toBeInTheDocument();
    for (const label of ['MQTT-Passwort', 'Telegram-Bot-Token', 'Home Assistant', 'Kurz-Link-Dienst', 'Proxmox pve1']) {
      expect(within(card()).getByText(label)).toBeInTheDocument();
    }
    expect(within(card()).getByText('Modul aus')).toBeInTheDocument();
    expect(within(card()).getByRole('button', { name: 'Modul einschalten' })).toBeInTheDocument();
    expect(within(card()).getAllByRole('button', { name: 'Zugriff öffnen' })).toHaveLength(2);
    expect(
      within(card()).getByRole('button', {
        name: 'Wert für Paperless in Tapesmith übernehmen',
      }),
    ).toBeEnabled();
  });

  it('„Alle aus externen Quellen übernehmen“ sendet einen Aufruf und meldet übernommen und übersprungen', async () => {
    let state = makeSecrets([
      { id: 'homeassistant', source: 'extern', set: true },
      { id: 'paperless', source: 'extern', set: false },
    ]);
    const api = mockApi({
      'GET /api/v1/secrets': () => state,
      'POST /api/v1/secrets/adopt-all': () => {
        state = makeSecrets([
          { id: 'homeassistant', source: 'tapesmith', set: true },
          { id: 'paperless', source: 'extern', set: false },
        ]);
        return {
          adopted: ['homeassistant'],
          skipped: [
            {
              id: 'paperless',
              label: 'Paperless',
              reason: 'Die externe Quelle liefert keinen Wert',
            },
          ],
          slots: state.slots,
        };
      },
    });
    const { user } = renderWithProviders(<SecretsCard />);
    const button = await screen.findByRole('button', {
      name: 'Alle aus externen Quellen übernehmen',
    });
    await waitFor(() => expect(button).toBeEnabled());
    await user.click(button);
    await waitFor(() =>
      expect(api.calls.filter((c) => c.method === 'POST' && c.path === '/api/v1/secrets/adopt-all')).toHaveLength(1),
    );
    expect((await screen.findAllByText('1 Wert in Tapesmith übernommen')).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/1 übersprungen: Paperless: Die externe Quelle liefert keinen Wert/).length).toBeGreaterThan(0);
    await waitFor(() =>
      expect(
        screen.getByRole('button', {
          name: 'Alle aus externen Quellen übernehmen',
        }),
      ).toBeDisabled(),
    );
  });

  it('ohne übernehmbare externe Quelle ist „Alle übernehmen“ aus; leere Quelle zeigt klaren Hinweis', async () => {
    mockApi({
      'GET /api/v1/secrets': () => makeSecrets([{ id: 'mqtt', source: 'extern', set: false }]),
    });
    renderWithProviders(<SecretsCard />);
    expect(await within(card()).findByText('Externe Quelle leer: Wert direkt eingeben')).toBeInTheDocument();
    expect(
      within(card()).queryByRole('button', {
        name: /MQTT-Passwort in Tapesmith übernehmen/,
      }),
    ).toBeNull();
    expect(
      screen.getByRole('button', {
        name: 'Alle aus externen Quellen übernehmen',
      }),
    ).toBeDisabled();
  });
});
