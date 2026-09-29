import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { fixtures, mockApi, renderWithProviders } from '../../test/utils';
import * as platform from '../../platform';
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

describe('Kompakt', () => {
  afterEach(() => {
    vi.mocked(platform.closeWindow).mockClear();
    vi.mocked(platform.setWindowTitle).mockClear();
  });

  it('Feld hat Autofokus', () => {
    mockApi(baseRoutes());
    renderWithProviders(<KompaktPage />);
    expect(screen.getByRole('textbox', { name: 'Labeltext' })).toHaveFocus();
  });

  it('Enter druckt, nach ok schliesst das Fenster nach 800 ms', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockApi(baseRoutes({ 'POST /api/v1/labels/print': () => fixtures.outcomeJson({ status: 'ok', title: 'X' }) }));
    const { user } = renderWithProviders(<KompaktPage />);
    const textarea = screen.getByRole('textbox', { name: 'Labeltext' });
    await user.type(textarea, 'X');
    await waitFor(() => expect(screen.getByRole('img')).toBeInTheDocument());
    await user.keyboard('{Enter}');
    await screen.findByText('Gedruckt');
    expect(platform.closeWindow).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(800);
    expect(platform.closeWindow).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it('Esc schliesst das Fenster sofort', async () => {
    mockApi(baseRoutes());
    const { user } = renderWithProviders(<KompaktPage />);
    const textarea = screen.getByRole('textbox', { name: 'Labeltext' });
    await user.click(textarea);
    await user.keyboard('{Escape}');
    expect(platform.closeWindow).toHaveBeenCalledTimes(1);
  });

  it('Fehler laesst das Fenster offen', async () => {
    mockApi(
      baseRoutes({
        'POST /api/v1/labels/print': () => fixtures.outcomeJson({ status: 'abgelehnt', reasons: ['Band leer'] }),
      }),
    );
    const { user } = renderWithProviders(<KompaktPage />);
    const textarea = screen.getByRole('textbox', { name: 'Labeltext' });
    await user.type(textarea, 'X');
    await waitFor(() => expect(screen.getByRole('img')).toBeInTheDocument());
    await user.keyboard('{Enter}');
    await screen.findByText('Band leer');
    expect(platform.closeWindow).not.toHaveBeenCalled();
  });
});
