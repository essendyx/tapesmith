import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import ProtokollPage from './index';
import { mockApi, renderWithProviders, SLOW_UI_MS } from '../../test/utils';
import type { LogContentJson } from './api';

const FILES = {
  files: [
    { name: 'install.log', size: 120, mtime: 1790000000 },
    { name: 'daemon.log', size: 2048, mtime: 1790000100 },
  ],
  daemon_log: 'daemon.log',
};

function content(name: string, lines: LogContentJson['lines'], truncated = false): LogContentJson {
  return { name, size: 2048, mtime: 1790000100, lines, truncated };
}

const DAEMON_LINES: LogContentJson['lines'] = [
  { text: '2026-09-30 10:00:00,001 INFO tapesmith.daemon: Dienst gestartet', level: 'INFO' },
  { text: '2026-09-30 10:00:02,003 ERROR tapesmith.print: Druck fehlgeschlagen', level: 'ERROR' },
];

function renderPage(routes: Parameters<typeof mockApi>[0] = {}) {
  const api = mockApi({
    'GET /api/v1/logs': () => FILES,
    'GET /api/v1/logs/:name': ({ params }) => content(params.name ?? '', params.name === 'daemon.log' ? DAEMON_LINES : []),
    ...routes,
  });
  return { api, ...renderWithProviders(<ProtokollPage />, { route: '/protokoll' }) };
}

describe('/protokoll', () => {
  it('zeigt standardmäßig das Protokoll des Druckdienstes mit eingefärbten Zeilen', async () => {
    renderPage();
    expect(await screen.findByRole('heading', { level: 1, name: 'Protokoll' })).toBeInTheDocument();
    const view = await screen.findByLabelText('Inhalt von daemon.log');
    expect(within(view).getByText(/Dienst gestartet/)).toBeInTheDocument();
    const error = within(view).getByText(/Druck fehlgeschlagen/);
    expect(error.className).not.toBe(within(view).getByText(/Dienst gestartet/).className);
    expect(screen.getByRole('combobox', { name: 'Datei' })).toHaveValue('daemon.log');
  });

  it('Stufe, Zeilen und Suche gehen als Parameter an den Dienst, Dateiwechsel lädt die andere Datei', async () => {
    const { api, user } = renderPage();
    await screen.findByLabelText('Inhalt von daemon.log');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Stufe' }), 'ERROR');
    await waitFor(() => expect(api.calls.some((c) => c.path.startsWith('/api/v1/logs/daemon.log?') && c.path.includes('level=ERROR'))).toBe(true));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Zeilen' }), '1000');
    await waitFor(() => expect(api.calls.some((c) => c.path.includes('lines=1000'))).toBe(true));
    await user.type(screen.getByRole('searchbox', { name: 'Suche' }), 'Druck');
    await waitFor(() => expect(api.calls.some((c) => c.path.includes('search=Druck'))).toBe(true));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Datei' }), 'install.log');
    await waitFor(() => expect(api.calls.some((c) => c.path.startsWith('/api/v1/logs/install.log?'))).toBe(true));
  }, SLOW_UI_MS);

  it('Herunterladen holt die Datei über den Dienst', async () => {
    const { api, user } = renderPage({ 'GET /api/v1/logs/:name/download': () => ({}) });
    await screen.findByLabelText('Inhalt von daemon.log');
    await user.click(screen.getByRole('button', { name: 'Herunterladen' }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/logs/daemon.log/download')).toBe(true));
  });

  it('abgeschnittener Anfang wird angezeigt, leere Filtertreffer mit Hinweis', async () => {
    renderPage({ 'GET /api/v1/logs/:name': () => content('daemon.log', [], true) });
    expect(await screen.findByText('Letzte 0 Zeilen')).toBeInTheDocument();
    expect(screen.getByText('Die Datei ist leer.')).toBeInTheDocument();
  });

  it('ohne Protokolle: Leerzustand', async () => {
    renderPage({ 'GET /api/v1/logs': () => ({ files: [], daemon_log: 'daemon.log' }) });
    expect(await screen.findByText('Noch keine Protokolle')).toBeInTheDocument();
  });
});
