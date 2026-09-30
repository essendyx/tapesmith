/** Englischer Wortlaut der Seite Batterien: Überschrift und Hauptaktion. */
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { mockApi, renderWithProviders } from '../../test/utils';
import type { BatteryDeviceJson } from './types';
import BatterienPage from '.';

const device: BatteryDeviceJson = {
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

describe('Seite Batterien: Englisch', () => {
  it('Überschrift und Hauptaktion sind englisch', async () => {
    mockApi({ 'GET /api/v1/homelab/ha/batteries': () => ({ devices: [device], todo_entity: null, warnings: [] }) });
    renderWithProviders(<BatterienPage />, { route: '/homelab/batterien', language: 'en' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Home Assistant' })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /^Print label: / })).toBeInTheDocument();
  });
});
