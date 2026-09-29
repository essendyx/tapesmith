/** Englischer Wortlaut der Seite Homelab: Überschrift und eine Kachel. */
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { mockApi, renderWithProviders } from '../../test/utils';
import HomelabPage from '.';

function Mounted(): JSX.Element {
  return (
    <Routes>
      <Route path="/homelab/*" element={<HomelabPage />} />
    </Routes>
  );
}

describe('Seite Homelab: Englisch', () => {
  it('Überschrift und eine Kachel sind englisch', async () => {
    mockApi({ 'GET /api/v1/homelab/check': () => ({ services: [] }) });
    renderWithProviders(<Mounted />, { route: '/homelab', language: 'en' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Homelab' })).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Cables' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Home Assistant' })).toBeInTheDocument();
    expect(screen.getByText('Reads VMs and containers from Proxmox VE and prints labels for them.')).toBeInTheDocument();
  });
});
