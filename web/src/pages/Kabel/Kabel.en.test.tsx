/** Englischer Wortlaut der Seite Kabel: Überschrift und Reiter. */
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { mockApi, renderWithProviders } from '../../test/utils';
import KabelPage from './index';

describe('Seite Kabel: Englisch', () => {
  it('Überschrift und Reiter sind englisch', async () => {
    mockApi({ 'GET /api/v1/homelab/kabel/register': () => ({ entries: [] }) });
    renderWithProviders(<KabelPage />, { route: '/homelab/kabel', language: 'en' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Cables' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'NetBox import' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'ID scheme' })).toBeInTheDocument();
  });
});
