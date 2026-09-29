import { afterEach, describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { mockApi, renderWithProviders, restoreAllMocks } from '../../test/utils';
import type { RollUsageJson, StatsJson } from '../../api/types';
import StatistikPage from './index';

afterEach(() => {
  restoreAllMocks();
});

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

const meterFormat = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 1 });
function formatMeters(mm: number): string {
  return `${meterFormat.format(mm / 1000)} m`;
}

describe('/statistik', () => {
  it('Rollen-Balken haben einen zugänglichen Namen je Rolle (axe im echten Browser)', async () => {
    const roll: RollUsageJson = {
      tape_id: 'w12', tape_name: 'Weiß 12 mm', started: '2026-09-01T10:00:00', length_mm: 4000,
      used_mm: 1400, jobs: 12, finished: false, factor: 1,
    };
    mockApi({ 'GET /api/v1/stats': () => stats(), 'GET /api/v1/stats/rolls': () => ({ rolls: [roll] }) });
    renderWithProviders(<StatistikPage />);
    expect(await screen.findByRole('progressbar', { name: 'Verbrauch der Rolle Weiß 12 mm' })).toBeInTheDocument();
  });

  it('zeigt Balken, Tabelle und Summenkarten aus GET /stats', async () => {
    mockApi({
      'GET /api/v1/stats': () => stats(),
      'GET /api/v1/stats/rolls': () => emptyRolls,
    });
    renderWithProviders(<StatistikPage />);
    expect(await screen.findByText('2026-09')).toBeInTheDocument();
    expect(screen.getByText('2026-08')).toBeInTheDocument();
    expect(screen.getByText('4')).toBeInTheDocument();
    expect(screen.getByText('6')).toBeInTheDocument();
  });

  it('Umschalten auf „Vorlage“ sendet by=vorlage', async () => {
    const api = mockApi({
      'GET /api/v1/stats': ({ query }) => stats({ by: query.get('by') ?? 'monat' }),
      'GET /api/v1/stats/rolls': () => emptyRolls,
    });
    const { user } = renderWithProviders(<StatistikPage />);
    await screen.findByText('2026-09');
    await user.click(screen.getByRole('button', { name: 'Vorlage' }));
    await waitFor(() => expect(api.calls.some((c) => c.path.includes('by=vorlage'))).toBe(true));
  });

  it('zeigt ein eigenständiges Balkendiagramm mit Achse, Wert am Balken und Tooltip neben der Tabelle', async () => {
    // Grosse, gut unterscheidbare Meterwerte, damit keine zwei Texte im Diagramm zufaellig gleich formatiert werden.
    mockApi({
      'GET /api/v1/stats': () =>
        stats({
          rows: [
            { key: '2026-09', jobs: 3, labels: 5, tape_mm: 150000 },
            { key: '2026-08', jobs: 1, labels: 1, tape_mm: 30000 },
          ],
          totals: { key: 'gesamt', jobs: 4, labels: 6, tape_mm: 180000 },
        }),
      'GET /api/v1/stats/rolls': () => emptyRolls,
    });
    renderWithProviders(<StatistikPage />);
    await screen.findByText('2026-09');
    const chart = screen.getByLabelText('Balkendiagramm: verbrauchtes Band je Gruppe');
    // Achse mit Skalierung (0 und Maximum in Metern; Maximum erscheint zusätzlich am größten Balken)
    expect(within(chart).getByText('0 m')).toBeInTheDocument();
    expect(within(chart).getAllByText(formatMeters(150000)).length).toBeGreaterThanOrEqual(2);
    // Wert am Balken (im Diagramm sichtbar, unabhaengig von der Tabelle)
    expect(within(chart).getByText(formatMeters(30000))).toBeInTheDocument();
    // Tooltip-Inhalt (Gruppe + Wert) ist ohne Hover/Fokus nicht im DOM
    expect(screen.queryByText(`2026-09: ${formatMeters(150000)}`)).not.toBeInTheDocument();
    // je Balken ein fokussierbares Element (Tastatur + Tooltip)
    expect(chart.querySelectorAll('[tabindex]').length).toBe(2);
    // Tabelle bleibt als separate Textalternative erhalten
    const table = screen.getByRole('table');
    expect(within(table).getByText('2026-09')).toBeInTheDocument();
    expect(within(table).getByText(formatMeters(150000))).toBeInTheDocument();
  });

  it('leere Zeilen zeigen EmptyState', async () => {
    mockApi({
      'GET /api/v1/stats': () => stats({ rows: [], totals: { key: '', jobs: 0, labels: 0, tape_mm: 0 } }),
      'GET /api/v1/stats/rolls': () => emptyRolls,
    });
    renderWithProviders(<StatistikPage />);
    expect(await screen.findByText('Noch keine Daten')).toBeInTheDocument();
  });
});
