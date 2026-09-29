import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { findGermanLiterals, findHardcodedColors } from '../../test/untranslated';
import { mockApi, renderWithProviders } from '../../test/utils';
import InventarPage from './index';

const tsx = import.meta.glob('./**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const ts = import.meta.glob('./**/*.ts', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const sources = { ...tsx, ...ts };

describe('Inventar: Übersetzung', () => {
  it('keine deutschen Literale in pages/Inventar (außer Tests)', () => {
    expect(findGermanLiterals(sources)).toEqual([]);
  });

  it('keine fest verdrahteten Farben', () => {
    expect(findHardcodedColors(sources)).toEqual([]);
  });

  it('Englisch: Überschrift und Hauptaktion', async () => {
    mockApi({ 'GET /api/v1/inventory/boxes': () => ({ boxes: [] }) });
    renderWithProviders(createElement(InventarPage), { route: '/inventar', language: 'en' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Inventory' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'New box' })).toBeInTheDocument();
  });
});
