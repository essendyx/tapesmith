import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { fixtures, LocationProbe, MockResponse, mockApi, renderWithProviders } from '../../test/utils';
import type { BatteryDeviceJson } from './types';
import BatterienPage from '.';

const deviceLow: BatteryDeviceJson = {
  entity_id: 'binary_sensor.fenster_bad_battery',
  device: 'Fensterkontakt Bad',
  area: 'Bad',
  level: null,
  low: true,
  battery_type: '',
  type_source: '',
  manufacturer: '',
  model: '',
};

const deviceOk: BatteryDeviceJson = {
  entity_id: 'sensor.flur_rauchmelder_battery',
  device: 'Rauchmelder Flur',
  area: 'Flur',
  level: 100,
  low: false,
  battery_type: '9V',
  type_source: 'Home Assistant',
  manufacturer: '',
  model: '',
};

describe('BatterienPage', () => {
  it('Liste zeigt Geräte, ein schwaches Gerät ist als „schwach“ markiert', async () => {
    mockApi({
      'GET /api/v1/homelab/ha/batteries': () => ({ devices: [deviceLow, deviceOk], todo_entity: null, warnings: [] }),
    });
    renderWithProviders(<BatterienPage />, { route: '/homelab/batterien' });

    await screen.findByText('Fensterkontakt Bad');
    expect(screen.getByText('Rauchmelder Flur')).toBeInTheDocument();
    expect(screen.getByText('schwach')).toBeInTheDocument();
  });

  it('Typ ändern sendet PUT /battery-type', async () => {
    const api = mockApi({
      'GET /api/v1/homelab/ha/batteries': () => ({ devices: [deviceLow, deviceOk], todo_entity: null, warnings: [] }),
      'PUT /api/v1/homelab/ha/battery-type': () => ({ ok: true }),
    });
    const { user } = renderWithProviders(<BatterienPage />, { route: '/homelab/batterien' });
    await screen.findByText('Fensterkontakt Bad');

    const combo = screen.getByRole('combobox', { name: 'Batterietyp Fensterkontakt Bad' });
    await user.click(combo);
    await user.click(await screen.findByRole('option', { name: 'CR2032' }));

    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/homelab/ha/battery-type')).toBe(true));
    const call = api.calls.find((c) => c.path === '/api/v1/homelab/ha/battery-type');
    expect(call?.body).toEqual({ entity_id: 'binary_sensor.fenster_bad_battery', battery_type: 'CR2032' });
  });

  it('Auswahl und „Etiketten als Serie“ navigiert nach /vorlagen?vorlage=batterie&import=…', async () => {
    mockApi({
      'GET /api/v1/homelab/ha/batteries': () => ({ devices: [deviceLow, deviceOk], todo_entity: null, warnings: [] }),
      'POST /api/v1/homelab/ha/table': () => ({ pending_id: 'p1', template: 'batterie', count: 1, warnings: [] }),
    });
    const { user } = renderWithProviders(
      <>
        <BatterienPage />
        <LocationProbe />
      </>,
      { route: '/homelab/batterien' },
    );
    await screen.findByText('Fensterkontakt Bad');

    await user.click(screen.getByLabelText('Fensterkontakt Bad auswählen'));
    await user.click(screen.getByRole('button', { name: 'Etiketten als Serie' }));

    await waitFor(() =>
      expect(screen.getByTestId('location')).toHaveTextContent('/vorlagen?vorlage=batterie&import=p1'),
    );
  });

  it('Wartung druckt mit template „wartung“ und legt danach ein Home-Assistant-To-do an, wenn der Schalter an ist', async () => {
    const api = mockApi({
      'GET /api/v1/homelab/ha/batteries': () => ({ devices: [], todo_entity: 'todo.hausaufgaben', warnings: [] }),
      'POST /api/v1/labels/render': () => fixtures.renderJson(),
      'POST /api/v1/labels/print': () => fixtures.outcomeJson({ status: 'ok', title: 'USV-Akku' }),
      'POST /api/v1/homelab/ha/todo': () => ({ ok: true, entity_id: 'todo.hausaufgaben' }),
    });
    const { user } = renderWithProviders(<BatterienPage />, { route: '/homelab/batterien' });

    await user.click(screen.getByRole('tab', { name: 'Wartung' }));
    await user.type(screen.getByRole('textbox', { name: 'Was' }), 'USV-Akku');
    await user.click(screen.getByLabelText('Erinnerung in Home Assistant anlegen'));

    await user.click(screen.getByRole('button', { name: 'Drucken' }));

    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
    const printCall = api.calls.find((c) => c.path === '/api/v1/labels/print');
    const body = printCall?.body as { source: { kind: string; template: string } };
    expect(body.source.kind).toBe('template');
    expect(body.source.template).toBe('wartung');

    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/homelab/ha/todo')).toBe(true));
  });

  it('Fehler „Token fehlt“ zeigt Meldung und Hinweis', async () => {
    mockApi({
      'GET /api/v1/homelab/ha/batteries': () =>
        new MockResponse(424, {
          error: {
            kind: 'TokenMissing',
            message: 'Home Assistant: Token fehlt: Home Assistant (Datei C:\\Tokens\\.ha_token)',
            hint: 'Token als Datei C:\\Tokens\\.ha_token ablegen',
            exit_code: 1,
            details: null,
          },
        }),
    });
    renderWithProviders(<BatterienPage />, { route: '/homelab/batterien' });

    expect(await screen.findByText(/Token fehlt/)).toBeInTheDocument();
    expect(screen.getByText(/als Datei/)).toBeInTheDocument();
  });
});
