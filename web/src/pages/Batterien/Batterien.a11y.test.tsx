/** Barrierefreiheit und Tastatur der Seite Batterien: axe in de und en, Reiter, Fehler. */
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { MockResponse, mockApi, renderWithProviders } from '../../test/utils';
import type { Language } from '../../i18n';
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
  level: 55,
  low: false,
  battery_type: '9V',
  type_source: 'Home Assistant',
  manufacturer: '',
  model: '',
};

const HEADING = { de: 'Home Assistant', en: 'Home Assistant' } as const;
const WARTUNG_TAB = { de: 'Wartung', en: 'Maintenance' } as const;

describe.each(['de', 'en'] as Language[])('Seite Batterien: axe (%s)', (language) => {
  it('Grundzustand (Liste) ohne Befund', async () => {
    mockApi({ 'GET /api/v1/homelab/ha/batteries': () => ({ devices: [deviceLow, deviceOk], todo_entity: null, warnings: [] }) });
    const { container } = renderWithProviders(<BatterienPage />, { route: '/homelab/batterien', language });
    await screen.findByText('Fensterkontakt Bad');
    await expectNoA11yViolations(container);
  });

  it('leerer Zustand ohne Befund', async () => {
    mockApi({ 'GET /api/v1/homelab/ha/batteries': () => ({ devices: [], todo_entity: null, warnings: [] }) });
    const { container } = renderWithProviders(<BatterienPage />, { route: '/homelab/batterien', language });
    await screen.findByRole('heading', { name: HEADING[language] });
    await waitFor(() => expect(screen.queryByText('Lade Geräte …')).toBeNull());
    await expectNoA11yViolations(container);
  });

  it('Fehlerzustand ohne Befund', async () => {
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
    const { container } = renderWithProviders(<BatterienPage />, { route: '/homelab/batterien', language });
    await screen.findByText(/Token fehlt/);
    await expectNoA11yViolations(container);
  });

  it('Reiter „Wartung" ohne Befund', async () => {
    mockApi({ 'GET /api/v1/homelab/ha/batteries': () => ({ devices: [], todo_entity: null, warnings: [] }) });
    const { user, container } = renderWithProviders(<BatterienPage />, { route: '/homelab/batterien', language });
    await user.click(await screen.findByRole('tab', { name: WARTUNG_TAB[language] }));
    await expectNoA11yViolations(container);
  });
});

describe('Seite Batterien: Tastatur', () => {
  it('Reiter „Wartung" per Tab erreichbar, per Enter aktiviert er sich', async () => {
    mockApi({ 'GET /api/v1/homelab/ha/batteries': () => ({ devices: [], todo_entity: null, warnings: [] }) });
    const { user } = renderWithProviders(<BatterienPage />, { route: '/homelab/batterien' });
    const tab = await screen.findByRole('tab', { name: WARTUNG_TAB.de });
    tab.focus();
    expect(tab).toHaveFocus();
    await user.keyboard('{Enter}');
    await screen.findByRole('textbox', { name: 'Was' });
  });
});
