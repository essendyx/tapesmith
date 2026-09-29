import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { a11yViolations, expectNoA11yViolations, formatViolations } from './a11y';
import { fixtures, mockApi, renderWithProviders } from './utils';

describe('a11y-Hilfen', () => {
  it('Knopf ohne Namen ergibt button-name', async () => {
    const { container } = render(
      <button type="button">
        <svg />
      </button>,
    );
    const violations = await a11yViolations(container);
    expect(violations.map((v) => v.id)).toContain('button-name');
  });

  it('beschrifteter Knopf ist in Ordnung', async () => {
    const { container } = render(<button type="button">Drucken</button>);
    expect(await a11yViolations(container)).toEqual([]);
    await expectNoA11yViolations(container);
  });

  it('Fehlermeldung nennt Regel, Selektor und Hilfe-URL', async () => {
    const { container } = render(
      <button type="button" id="ohne-name">
        <svg />
      </button>,
    );
    const error = await expectNoA11yViolations(container).then(
      () => null,
      (e: unknown) => e as Error,
    );
    expect(error).toBeInstanceOf(Error);
    expect(error?.message).toContain('button-name');
    expect(error?.message).toContain('#ohne-name');
    expect(error?.message).toMatch(/https:\/\/dequeuniversity\.com\/rules\/axe\//);
  });

  it('disableRules schaltet einzelne Regeln ab, Läufe laufen nacheinander', async () => {
    const { container } = render(
      <button type="button">
        <svg />
      </button>,
    );
    const [a, b] = await Promise.all([
      a11yViolations(container, { disableRules: ['button-name'] }),
      a11yViolations(container),
    ]);
    expect(a).toEqual([]);
    expect(formatViolations(b ?? [])).toContain('button-name');
  });

  it('Hülle mit Statistik-Seite ohne axe-Verletzungen', async () => {
    mockApi(
      {
        'GET /api/v1/status': () => fixtures.statusJson,
        'GET /api/v1/stats': () => ({
          by: 'monat',
          rows: [{ key: '2026-09', jobs: 3, labels: 5, tape_mm: 150 }],
          totals: { key: 'gesamt', jobs: 3, labels: 5, tape_mm: 150 },
        }),
        'GET /api/v1/stats/rolls': () => ({ rolls: [] }),
      },
      { quiet: true },
    );
    const { container } = renderWithProviders(<></>, { withShell: true, route: '/statistik' });
    await screen.findByText('2026-09');
    expect(screen.getByRole('navigation', { name: 'Seiten' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    await expectNoA11yViolations(container);
  });
});
