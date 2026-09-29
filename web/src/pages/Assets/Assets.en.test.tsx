/** Englischer Wortlaut der Seite Assets: Überschrift und Hauptaktion. */
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { mockApi, renderWithProviders } from '../../test/utils';
import type { AssetsListResponse } from './types';
import AssetsPage from '.';

function listResponse(): AssetsListResponse {
  return { assets: [], range: { prefix: 'HL-', width: 4, next: 'HL-0002', check_digit: false }, shortlink: true };
}

describe('Seite Assets: Englisch', () => {
  it('Überschrift und Hauptaktion sind englisch', async () => {
    mockApi({ 'GET /api/v1/homelab/assets': () => listResponse() });
    renderWithProviders(<AssetsPage />, { language: 'en' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Assets' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'New assets' })).toBeInTheDocument();
  });
});
