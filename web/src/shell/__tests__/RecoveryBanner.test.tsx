/** Hinweis auf verwaiste Entwürfe und Lebenszeichen der Hülle. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, screen, waitFor } from '@testing-library/react';
import { useNavigate } from 'react-router-dom';
import type { DraftInfo } from '../../api/types';
import { fixtures, LocationProbe, mockApi, renderWithProviders } from '../../test/utils';
import { expectNoA11yViolations } from '../../test/a11y';
import { HEARTBEAT_MS, RecoveryBanner } from '../RecoveryBanner';

const ORPHAN: DraftInfo = {
  id: 'entwurf-0001',
  title: 'Regal A',
  doc_name: null,
  dirty: true,
  updated: '2026-09-28T10:00:00',
  objects: 2,
  order: 0,
  session: 'alte-sitzung-1',
};

function draftsApi(orphaned: DraftInfo[] = [ORPHAN]) {
  return mockApi(
    {
      'GET /api/v1/status': () => fixtures.statusJson,
      'GET /api/v1/drafts': () => ({ drafts: orphaned, own: [], orphaned }),
      'POST /api/v1/drafts/heartbeat': () => ({ alive_s: 90 }),
    },
    { quiet: true },
  );
}

function location(): string {
  return screen.getByTestId('location').textContent ?? '';
}

afterEach(() => {
  vi.useRealTimers();
});

describe('RecoveryBanner', () => {
  it('zeigt den Hinweis auf /statistik und navigiert mit „Im Editor wiederherstellen“', async () => {
    const api = draftsApi();
    const { user, container } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/statistik' });
    expect(await screen.findByText('1 nicht gespeicherter Entwurf gefunden')).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === 'GET' && c.path.startsWith('/api/v1/drafts?session='))).toBe(true);
    await expectNoA11yViolations(container);
    await user.click(screen.getByRole('button', { name: 'Im Editor wiederherstellen' }));
    await waitFor(() => expect(location()).toBe('/editor?wiederherstellen=1'));
    expect(screen.queryByTestId('recovery-banner')).toBeNull();
  });

  it('mehrere Entwürfe im Plural, „Später“ blendet für die Sitzung aus', async () => {
    draftsApi([ORPHAN, { ...ORPHAN, id: 'entwurf-0002' }]);
    const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/statistik' });
    expect(await screen.findByText('2 nicht gespeicherte Entwürfe gefunden')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Später' }));
    expect(screen.queryByTestId('recovery-banner')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Galerie' }));
    expect(screen.queryByTestId('recovery-banner')).toBeNull();
  });

  it('auf /editor kein Hinweis (der Editor bietet die Wiederherstellung selbst an)', async () => {
    const api = draftsApi();
    // Nur der Hinweis selbst (ohne Hülle): so lädt der Test die Editor-Seite nicht.
    renderWithProviders(<RecoveryBanner />, { route: '/editor' });
    // Lebenszeichen ja, Abfrage der Entwürfe übernimmt dort der Editor selbst.
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/drafts/heartbeat')).toBe(true));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.queryByTestId('recovery-banner')).toBeNull();
  });

  it('ohne verwaiste Entwürfe kein Hinweis; Englisch übersetzt', async () => {
    draftsApi();
    renderWithProviders(<LocationProbe />, { withShell: true, route: '/statistik', language: 'en' });
    expect(await screen.findByText('Found 1 unsaved draft')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Restore in editor' })).toBeInTheDocument();
  });

  it('Lebenszeichen sofort und nach 30 s', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const api = draftsApi([]);
    renderWithProviders(<LocationProbe />, { withShell: true, route: '/statistik' });
    const beats = () => api.calls.filter((c) => c.method === 'POST' && c.path === '/api/v1/drafts/heartbeat');
    await waitFor(() => expect(beats()).toHaveLength(1));
    expect((beats()[0]?.body as { session?: string }).session).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(HEARTBEAT_MS);
    });
    await waitFor(() => expect(beats()).toHaveLength(2));
    expect(screen.queryByTestId('recovery-banner')).toBeNull();
  });

  it('Entwürfe eines eben beendeten Fensters: Hinweis erscheint, sobald sie verwaist sind', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let orphaned: DraftInfo[] = [];
    mockApi(
      {
        'GET /api/v1/status': () => fixtures.statusJson,
        'GET /api/v1/drafts': () => ({ drafts: orphaned, own: [], orphaned }),
        'POST /api/v1/drafts/heartbeat': () => ({ alive_s: 90 }),
      },
      { quiet: true },
    );
    renderWithProviders(<LocationProbe />, { withShell: true, route: '/statistik' });
    await screen.findByRole('navigation', { name: 'Seiten' });
    expect(screen.queryByTestId('recovery-banner')).toBeNull();
    // Das alte Fenster hat noch ein Lebenszeichen: erst nach 90 s gelten seine Entwürfe als verwaist.
    orphaned = [ORPHAN];
    await act(async () => {
      await vi.advanceTimersByTimeAsync(HEARTBEAT_MS);
    });
    expect(await screen.findByText('1 nicht gespeicherter Entwurf gefunden')).toBeInTheDocument();
  });

  it('nach der Wiederherstellung im Editor kommt der Hinweis nicht veraltet zurück', async () => {
    let orphaned: DraftInfo[] = [ORPHAN];
    mockApi(
      {
        'GET /api/v1/drafts': () => ({ drafts: orphaned, own: [], orphaned }),
        'POST /api/v1/drafts/heartbeat': () => ({ alive_s: 90 }),
      },
      { quiet: true },
    );
    function Jump(): JSX.Element {
      const navigate = useNavigate();
      return (
        <>
          <button type="button" onClick={() => navigate('/editor')}>
            zum Editor
          </button>
          <button type="button" onClick={() => navigate('/statistik')}>
            zur Statistik
          </button>
        </>
      );
    }
    const { user } = renderWithProviders(
      <>
        <RecoveryBanner />
        <Jump />
      </>,
      { route: '/statistik' },
    );
    expect(await screen.findByTestId('recovery-banner')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'zum Editor' }));
    expect(screen.queryByTestId('recovery-banner')).toBeNull();
    // Im Editor wiederhergestellt: nichts mehr verwaist.
    orphaned = [];
    await user.click(screen.getByRole('button', { name: 'zur Statistik' }));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(screen.queryByTestId('recovery-banner')).toBeNull();
  });

  it('Fehler beim Abfragen bleiben still', async () => {
    const errors = vi.spyOn(console, 'error');
    mockApi({ 'GET /api/v1/status': () => fixtures.statusJson }, { quiet: true });
    renderWithProviders(<LocationProbe />, { withShell: true, route: '/statistik' });
    await screen.findByRole('navigation', { name: 'Seiten' });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.queryByTestId('recovery-banner')).toBeNull();
    expect(errors).not.toHaveBeenCalled();
  });
});
