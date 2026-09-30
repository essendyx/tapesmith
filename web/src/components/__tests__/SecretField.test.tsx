import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { SecretField } from '../SecretField';
import { findDialogByRole, mockApi, renderWithProviders } from '../../test/utils';
import { makeSecrets } from '../../test/secretFixtures';

const VALUE = 'geheim-4711';

function renderField(routes: Parameters<typeof mockApi>[0]) {
  const api = mockApi({ 'GET /api/v1/secrets': () => makeSecrets(), ...routes });
  const result = renderWithProviders(<SecretField slotId="paperless" label="Token" help="Hilfe" />);
  return { api, ...result };
}

describe('SecretField', () => {
  it('Nicht gesetzt: Kennwortfeld, Speichern sendet PUT, Feld wird danach geleert, Wert nirgends im DOM', async () => {
    let state = makeSecrets();
    const { api, user } = renderField({
      'GET /api/v1/secrets': () => state,
      'PUT /api/v1/secrets/:id': () => {
        state = makeSecrets([{ id: 'paperless', source: 'tapesmith', set: true }]);
        return { id: 'paperless', label: 'Paperless', source: 'tapesmith', set: true };
      },
    });
    expect(await screen.findByText('Nicht gesetzt')).toBeInTheDocument();
    const input = screen.getByLabelText('Token');
    expect(input).toHaveAttribute('type', 'password');
    const save = screen.getByRole('button', { name: 'Wert für Paperless speichern' });
    expect(save).toBeDisabled();
    await user.type(input, VALUE);
    await user.click(save);
    await waitFor(() => expect(api.calls.some((c) => c.method === 'PUT' && c.path === '/api/v1/secrets/paperless')).toBe(true));
    expect(api.calls.find((c) => c.method === 'PUT')?.body).toEqual({ value: VALUE });
    expect(await screen.findByText('Gespeichert')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByDisplayValue(VALUE)).toBeNull());
    expect(screen.getByRole('button', { name: 'Wert für Paperless ersetzen' })).toBeInTheDocument();
  });

  it('Entfernen fragt nach und sendet DELETE', async () => {
    const { api, user } = renderField({
      'GET /api/v1/secrets': () => makeSecrets([{ id: 'paperless', source: 'tapesmith', set: true }]),
      'DELETE /api/v1/secrets/:id': () => ({ id: 'paperless', label: 'Paperless', source: 'none', set: false }),
    });
    await user.click(await screen.findByRole('button', { name: 'Wert für Paperless entfernen' }));
    const dialog = await findDialogByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Entfernen', hidden: true }));
    await waitFor(() => expect(api.calls.some((c) => c.method === 'DELETE' && c.path === '/api/v1/secrets/paperless')).toBe(true));
  });

  it('externe Quelle: Hinweis und „In Tapesmith übernehmen“ (POST adopt)', async () => {
    let state = makeSecrets([{ id: 'paperless', source: 'extern', set: true }]);
    const { api, user } = renderField({
      'GET /api/v1/secrets': () => state,
      'POST /api/v1/secrets/:id/adopt': () => {
        state = makeSecrets([{ id: 'paperless', source: 'tapesmith', set: true }]);
        return { id: 'paperless', label: 'Paperless', source: 'tapesmith', set: true };
      },
    });
    expect(await screen.findByText('Aus externer Quelle')).toBeInTheDocument();
    expect(screen.getByText(/kommt aus einer externen Quelle/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Wert für Paperless in Tapesmith übernehmen' }));
    await waitFor(() => expect(api.calls.some((c) => c.method === 'POST' && c.path === '/api/v1/secrets/paperless/adopt')).toBe(true));
    expect(await screen.findByText('Gespeichert')).toBeInTheDocument();
  });

  it('Fehler des Dienstes erscheint als Meldung, Eingabe bleibt stehen', async () => {
    const { user } = renderField({
      'PUT /api/v1/secrets/:id': () => {
        throw new Error('Windows-Anmeldeinformationen nicht erreichbar');
      },
    });
    const input = await screen.findByLabelText('Token');
    await user.type(input, VALUE);
    await user.click(screen.getByRole('button', { name: 'Wert für Paperless speichern' }));
    expect(await screen.findByText(/Aktion fehlgeschlagen/)).toBeInTheDocument();
    expect(input).toHaveValue(VALUE);
  });
});
