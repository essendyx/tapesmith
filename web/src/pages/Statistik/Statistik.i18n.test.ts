import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { findGermanLiterals, findHardcodedColors } from '../../test/untranslated';
import { mockApi, renderWithProviders } from '../../test/utils';
import type { RollUsageJson, StatsJson } from '../../api/types';
import StatistikPage from './index';

const tsx = import.meta.glob('./**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const ts = import.meta.glob('./**/*.ts', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const sources = { ...tsx, ...ts };

describe('Statistik: Übersetzung', () => {
  it('keine deutschen Literale in pages/Statistik (außer Tests)', () => {
    expect(findGermanLiterals(sources)).toEqual([]);
  });

  it('keine fest verdrahteten Farben', () => {
    expect(findHardcodedColors(sources)).toEqual([]);
  });

  it('Englisch: Überschrift und Gruppierungs-Knöpfe', async () => {
    const stats: StatsJson = {
      by: 'monat',
      rows: [{ key: '2026-09', jobs: 3, labels: 5, tape_mm: 150 }],
      totals: { key: 'gesamt', jobs: 3, labels: 5, tape_mm: 150 },
    };
    const emptyRolls: { rolls: RollUsageJson[] } = { rolls: [] };
    mockApi({ 'GET /api/v1/stats': () => stats, 'GET /api/v1/stats/rolls': () => emptyRolls });
    renderWithProviders(createElement(StatistikPage), { language: 'en' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Statistics' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Template' })).toBeInTheDocument();
  });
});
