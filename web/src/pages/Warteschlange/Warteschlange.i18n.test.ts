import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { findGermanLiterals, findHardcodedColors } from '../../test/untranslated';
import { mockApi, renderWithProviders } from '../../test/utils';
import WarteschlangePage from './index';

const tsx = import.meta.glob('./**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const ts = import.meta.glob('./**/*.ts', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const sources = { ...tsx, ...ts };

describe('Warteschlange: Übersetzung', () => {
  it('keine deutschen Literale in pages/Warteschlange (außer Tests)', () => {
    expect(findGermanLiterals(sources)).toEqual([]);
  });

  it('keine fest verdrahteten Farben', () => {
    expect(findHardcodedColors(sources)).toEqual([]);
  });

  it('Englisch: Überschrift und Hauptaktion', async () => {
    mockApi({ 'GET /api/v1/queue': () => ({ jobs: [], paused: false, auto_retry: true, next_try: null, probe: 'auto', waiting_reason: '' }) });
    renderWithProviders(createElement(WarteschlangePage), { language: 'en' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Queue' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry all now' })).toBeInTheDocument();
  });
});
