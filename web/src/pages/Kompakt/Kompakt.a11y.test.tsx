/** Barrierefreiheit und Tastatur des Kompakt-Fensters: axe in de und en. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { fixtures, mockApi, renderWithProviders } from '../../test/utils';
import * as platform from '../../platform';
import type { Language } from '../../i18n';
import KompaktPage from './index';

vi.mock('../../platform', () => ({
  closeWindow: vi.fn(),
  setWindowTitle: vi.fn(),
}));

function baseRoutes(overrides: Record<string, (req: { body: unknown }) => unknown> = {}) {
  return {
    'GET /api/v1/status': () => fixtures.statusJson,
    'POST /api/v1/labels/render': () => fixtures.renderJson(),
    ...overrides,
  };
}

const FIELD_LABEL: Record<Language, string> = { de: 'Labeltext', en: 'Label text' };

afterEach(() => {
  vi.mocked(platform.closeWindow).mockClear();
  vi.mocked(platform.setWindowTitle).mockClear();
});

describe('Kompakt: axe ohne Befund', () => {
  for (const language of ['de', 'en'] as const) {
    it(`leerer Zustand (${language})`, async () => {
      mockApi(baseRoutes());
      const { container } = renderWithProviders(<KompaktPage />, { language });
      await screen.findByRole('textbox', { name: FIELD_LABEL[language] });
      await expectNoA11yViolations(container);
    });

    it(`mit Vorschau (${language})`, async () => {
      mockApi(baseRoutes());
      const { user, container } = renderWithProviders(<KompaktPage />, { language });
      const textarea = screen.getByRole('textbox', { name: FIELD_LABEL[language] });
      await user.type(textarea, 'X');
      await waitFor(() => expect(screen.getByRole('img')).toBeInTheDocument());
      await expectNoA11yViolations(container);
    });

    it(`nach abgelehntem Druck mit Meldung (${language})`, async () => {
      mockApi(baseRoutes({ 'POST /api/v1/labels/print': () => fixtures.outcomeJson({ status: 'abgelehnt', reasons: ['Band leer'] }) }));
      const { user, container } = renderWithProviders(<KompaktPage />, { language });
      const textarea = screen.getByRole('textbox', { name: FIELD_LABEL[language] });
      await user.type(textarea, 'X');
      await waitFor(() => expect(screen.getByRole('img')).toBeInTheDocument());
      await user.keyboard('{Enter}');
      await screen.findByText('Band leer');
      await expectNoA11yViolations(container);
    });
  }
});

describe('Kompakt: Tastatur', () => {
  it('Feld hat Autofokus und Esc schließt sofort', async () => {
    mockApi(baseRoutes());
    const { user } = renderWithProviders(<KompaktPage />);
    const textarea = screen.getByRole('textbox', { name: 'Labeltext' });
    expect(textarea).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(platform.closeWindow).toHaveBeenCalledTimes(1);
  });
});

describe('Kompakt: Englisch', () => {
  it('Feld und Meldung sind englisch', async () => {
    mockApi(baseRoutes());
    renderWithProviders(<KompaktPage />, { language: 'en' });
    expect(screen.getByRole('textbox', { name: 'Label text' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'Quick print' })).toBeInTheDocument();
  });
});
