/** Englischer Wortlaut der Seite Zugriff: Überschrift und Hauptaktion. */
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { mockApi, renderWithProviders } from '../../test/utils';
import { baseAccessRoutes } from './testFixtures';
import ZugriffPage from './index';

describe('Seite Zugriff: Englisch', () => {
  it('Überschrift und Hauptaktion sind englisch', async () => {
    mockApi(baseAccessRoutes());
    renderWithProviders(<ZugriffPage />, { route: '/zugriff', language: 'en' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Access' })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'New token' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'API tokens' })).toBeInTheDocument();
  });
});
