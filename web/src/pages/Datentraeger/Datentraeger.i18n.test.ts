import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { findGermanLiterals, findHardcodedColors } from '../../test/untranslated';
import { mockApi, renderWithProviders } from '../../test/utils';
import DatentraegerPage from './index';

const tsx = import.meta.glob('./**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const ts = import.meta.glob('./**/*.ts', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const sources = { ...tsx, ...ts };

describe('Datentraeger: Übersetzung', () => {
  it('keine deutschen Literale in pages/Datentraeger (außer Tests)', () => {
    expect(findGermanLiterals(sources)).toEqual([]);
  });

  it('keine fest verdrahteten Farben', () => {
    expect(findHardcodedColors(sources)).toEqual([]);
  });

  it('Englisch: Überschrift und Reiter', async () => {
    mockApi({ 'GET /api/v1/drives': () => ({ drives: [] }) });
    renderWithProviders(createElement(DatentraegerPage), { route: '/datentraeger', language: 'en' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Drives' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Drives' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'SSH' })).toBeInTheDocument();
  });
});
