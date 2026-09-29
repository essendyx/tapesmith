import { afterEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expectNoA11yViolations } from '../../test/a11y';
import { mockApi, renderWithProviders, restoreAllMocks } from '../../test/utils';
import type { RollUsageJson, StatsJson } from '../../api/types';
import StatistikPage from './index';

afterEach(() => restoreAllMocks());

function stats(o: Partial<StatsJson> = {}): StatsJson {
  return {
    by: 'monat',
    rows: [
      { key: '2026-09', jobs: 3, labels: 5, tape_mm: 150 },
      { key: '2026-08', jobs: 1, labels: 1, tape_mm: 30 },
    ],
    totals: { key: 'gesamt', jobs: 4, labels: 6, tape_mm: 180 },
    ...o,
  };
}

const emptyRolls: { rolls: RollUsageJson[] } = { rolls: [] };

describe('Statistik: Barrierefreiheit', () => {
  for (const language of ['de', 'en'] as const) {
    it(`gefüllte Statistik ohne axe-Befund (${language})`, async () => {
      mockApi({ 'GET /api/v1/stats': () => stats(), 'GET /api/v1/stats/rolls': () => emptyRolls });
      const { container } = renderWithProviders(<StatistikPage />, { language });
      await screen.findByText('2026-09');
      await expectNoA11yViolations(container);
    });

    it(`leere Statistik ohne axe-Befund (${language})`, async () => {
      mockApi({
        'GET /api/v1/stats': () => stats({ rows: [], totals: { key: '', jobs: 0, labels: 0, tape_mm: 0 } }),
        'GET /api/v1/stats/rolls': () => emptyRolls,
      });
      const { container } = renderWithProviders(<StatistikPage />, { language });
      await screen.findAllByRole('status');
      await expectNoA11yViolations(container);
    });
  }

  it('Tastatur: Gruppierung „Vorlage" per Tab erreichbar und per Enter auslösbar', async () => {
    const api = mockApi({
      'GET /api/v1/stats': ({ query }) => stats({ by: query.get('by') ?? 'monat' }),
      'GET /api/v1/stats/rolls': () => emptyRolls,
    });
    renderWithProviders(<StatistikPage />);
    await screen.findByText('2026-09');
    const button = screen.getByRole('button', { name: 'Vorlage' });
    button.focus();
    expect(button).toHaveFocus();
    await userEvent.setup().keyboard('{Enter}');
    await waitFor(() => expect(api.calls.some((c) => c.path.includes('by=vorlage'))).toBe(true));
  });
});
