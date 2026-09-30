import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { FakeEventSource, chooseRowAction, findDialogByRole, mockApi, renderWithProviders, restoreAllMocks } from '../../test/utils';
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
  return {
    jobs: [],
    paused: false,
    auto_retry: true,
    next_try: null,
    probe: 'auto',
    waiting_reason: '',
    ...o,
  };
}

describe('/warteschlange', () => {
  it('zeigt zwei Aufträge aus GET /queue', async () => {
    mockApi({ 'GET /api/v1/queue': () => queue({ jobs: [job(), job({ id: 2, title: 'Zweiter Auftrag', position: 1 })] }) });
    renderWithProviders(<WarteschlangePage />);
    expect(await screen.findByText('Server 274913')).toBeInTheDocument();
    expect(screen.getByText('Zweiter Auftrag')).toBeInTheDocument();
  });

  it('„Nach unten“ sendet move mit position + 1', async () => {
    const api = mockApi({
      'GET /api/v1/queue': () => queue({ jobs: [job(), job({ id: 2, title: 'Zweiter Auftrag', position: 1 })] }),
      'POST /api/v1/queue/:id/move': () => ({}),
    });
    const { user } = renderWithProviders(<WarteschlangePage />);
    await screen.findByText('Server 274913');
    await chooseRowAction(user, 'Server 274913', 'Nach unten');
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/queue/1/move')).toBe(true));
    const call = api.calls.find((c) => c.path === '/api/v1/queue/1/move');
    expect(call?.body).toEqual({ position: 1 });
  });

  it('Schalter Automatischer Nachdruck sendet PUT queue/auto-retry und zeigt danach aus', async () => {
    const api = mockApi({
      'GET /api/v1/queue': () => queue({ auto_retry: true }),
      'PUT /api/v1/queue/auto-retry': () => queue({ auto_retry: false }),
    });
    const { user } = renderWithProviders(<WarteschlangePage />);
    const toggle = await screen.findByRole('switch', { name: 'Automatischer Nachdruck' });
    expect(toggle).toBeChecked();
    await user.click(toggle);
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/queue/auto-retry')).toBe(true));
    const call = api.calls.find((c) => c.path === '/api/v1/queue/auto-retry');
    expect(call?.body).toEqual({ on: false });
    await waitFor(() => expect(screen.getByRole('switch', { name: 'Automatischer Nachdruck' })).not.toBeChecked());
  });

  it('Countdown zeigt „in 30 s“ bei next_try 30 s in der Zukunft', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true, now: new Date('2026-09-27T12:00:00') });
    mockApi({
      'GET /api/v1/queue': () => queue({ jobs: [job({ next_try: '2026-09-27T12:00:30' })] }),
    });
    renderWithProviders(<WarteschlangePage />);
    expect(await screen.findByText(/in 30 s/)).toBeInTheDocument();
  });

  it('SSE queue lädt die Liste neu', async () => {
    const api = mockApi({ 'GET /api/v1/queue': () => queue({ jobs: [job()] }) });
    renderWithProviders(<WarteschlangePage />);
    await screen.findByText('Server 274913');
    expect(api.calls.filter((c) => c.path.startsWith('/api/v1/queue')).length).toBe(1);
    FakeEventSource.latest()?.emit('queue', {});
    await waitFor(() => expect(api.calls.filter((c) => c.path.startsWith('/api/v1/queue')).length).toBeGreaterThan(1));
  });

  it('„Abbrechen“ fragt nach, „Abbrechen“ im Dialog sendet nichts', async () => {
    const api = mockApi({
      'GET /api/v1/queue': () => queue({ jobs: [job()] }),
      'POST /api/v1/queue/:id/cancel': () => ({ ok: true }),
    });
    const { user } = renderWithProviders(<WarteschlangePage />);
    await screen.findByText('Server 274913');
    await chooseRowAction(user, 'Server 274913', 'Auftrag abbrechen');
    const dialog = await findDialogByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Abbrechen', hidden: true }));
    expect(api.calls.some((c) => c.path === '/api/v1/queue/1/cancel')).toBe(false);
  });

  it('Zustands-Badge zeigt ein Symbol (nicht nur Farbe und Text)', async () => {
    mockApi({ 'GET /api/v1/queue': () => queue({ jobs: [job({ state: 'wartet' })] }) });
    renderWithProviders(<WarteschlangePage />);
    await screen.findByText('Server 274913');
    const badge = screen.getByText('wartet');
    expect(badge.querySelector('svg')).toBeTruthy();
  });

  it('Zeilenaktionen: „Jetzt versuchen“ sichtbar, Umsortieren und Abbrechen im Mehr-Menü mit eindeutigem Namen', async () => {
    const api = mockApi({
      'GET /api/v1/queue': () => queue({ jobs: [job(), job({ id: 2, title: 'Zweiter Auftrag', position: 1 })] }),
      'POST /api/v1/queue/:id/retry': () => ({}),
    });
    const { user } = renderWithProviders(<WarteschlangePage />);
    await screen.findByText('Server 274913');
    expect(screen.queryByRole('button', { name: 'Nach unten' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Weitere Aktionen für Zweiter Auftrag' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Jetzt versuchen: Server 274913' }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/queue/1/retry')).toBe(true));
    // erster Auftrag: „Nach oben“ ist deaktiviert
    await user.click(screen.getByRole('button', { name: 'Weitere Aktionen für Server 274913' }));
    expect(await screen.findByRole('menuitem', { name: 'Nach oben' })).toHaveAttribute('aria-disabled', 'true');
  });

  it('Systemtitel in der Warteschlange erscheinen in der Oberflächensprache', async () => {
    mockApi({ 'GET /api/v1/queue': () => queue({ jobs: [job({ title: 'Kalibrierung Lineal' })] }) });
    renderWithProviders(<WarteschlangePage />, { language: 'en' });
    expect(await screen.findByText('Calibration ruler')).toBeInTheDocument();
  });

  it('leere Warteschlange zeigt EmptyState', async () => {
    mockApi({ 'GET /api/v1/queue': () => queue({ jobs: [] }) });
    renderWithProviders(<WarteschlangePage />);
    expect(await screen.findByText('Keine wartenden Aufträge')).toBeInTheDocument();
  });
});
