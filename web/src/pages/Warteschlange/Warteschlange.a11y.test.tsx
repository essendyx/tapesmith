import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expectNoA11yViolations } from '../../test/a11y';
import { chooseRowAction, findDialogByRole, mockApi, renderWithProviders, restoreAllMocks } from '../../test/utils';
import type { Language } from '../../i18n';
import type { QueueJson, QueuedJobJson } from '../../api/types';
import WarteschlangePage from './index';

afterEach(() => {
  restoreAllMocks();
  vi.useRealTimers();
});

function job(o: Partial<QueuedJobJson> = {}): QueuedJobJson {
  return {
    id: 1,
    created: '2026-09-27T12:00:00',
    source: 'gui',
    title: 'Server 274913',
    state: 'wartet',
    position: 0,
    attempts: 1,
    next_try: null,
    last_error: '',
    sensitive: false,
    history_id: null,
    ...o,
  };
}

function queue(o: Partial<QueueJson> = {}): QueueJson {
  return { jobs: [], paused: false, auto_retry: true, next_try: null, probe: 'auto', waiting_reason: '', ...o };
}

const CANCEL_LABEL: Record<Language, string> = { de: 'Auftrag abbrechen', en: 'Cancel job' };

describe('Warteschlange: Barrierefreiheit', () => {
  for (const language of ['de', 'en'] as const) {
    it(`gefüllte Warteschlange ohne axe-Befund (${language})`, async () => {
      mockApi({ 'GET /api/v1/queue': () => queue({ jobs: [job()] }) });
      const { container } = renderWithProviders(<WarteschlangePage />, { language });
      await screen.findByText('Server 274913');
      await expectNoA11yViolations(container);
    });

    it(`leere Warteschlange ohne axe-Befund (${language})`, async () => {
      mockApi({ 'GET /api/v1/queue': () => queue({ jobs: [] }) });
      const { container } = renderWithProviders(<WarteschlangePage />, { language });
      await screen.findByRole('status');
      await expectNoA11yViolations(container);
    });

    it(`Rückfrage „Auftrag abbrechen" ohne axe-Befund (${language})`, async () => {
      mockApi({ 'GET /api/v1/queue': () => queue({ jobs: [job()] }) });
      const { user } = renderWithProviders(<WarteschlangePage />, { language });
      await screen.findByText('Server 274913');
      await chooseRowAction(user, 'Server 274913', CANCEL_LABEL[language]);
      await findDialogByRole('alertdialog');
      await expectNoA11yViolations(document.body);
    });
  }

  it('Tastatur: „Alle jetzt versuchen" per Tab erreichbar und per Enter auslösbar', async () => {
    const api = mockApi({ 'GET /api/v1/queue': () => queue({ jobs: [job()] }), 'POST /api/v1/queue/retry-all': () => ({}) });
    renderWithProviders(<WarteschlangePage />);
    await screen.findByText('Server 274913');
    const button = screen.getByRole('button', { name: 'Alle jetzt versuchen' });
    button.focus();
    expect(button).toHaveFocus();
    await userEvent.setup().keyboard('{Enter}');
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/queue/retry-all')).toBe(true));
  });

  it('Rückfrage schließt mit Escape (ohne Bestätigung wird nichts gesendet)', async () => {
    const api = mockApi({ 'GET /api/v1/queue': () => queue({ jobs: [job()] }) });
    const { user } = renderWithProviders(<WarteschlangePage />);
    await screen.findByText('Server 274913');
    await chooseRowAction(user, 'Server 274913', 'Auftrag abbrechen');
    await findDialogByRole('alertdialog');
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(api.calls.some((c) => c.path === '/api/v1/queue/1/cancel')).toBe(false);
  });
});
