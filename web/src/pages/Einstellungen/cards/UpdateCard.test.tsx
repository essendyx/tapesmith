import { afterEach, describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { UpdateCard } from './UpdateCard';
import type { UpdateStatus } from '../../../api/update';
import { findDialogByRole, mockApi, MockResponse, renderWithProviders, restoreAllMocks } from '../../../test/utils';
import { expectNoA11yViolations } from '../../../test/a11y';

const BASE: UpdateStatus = {
  installed: true,
  current: '0.2.0',
  previous: '0.1.0',
  root: 'C:\\Users\\x\\AppData\\Local\\Programs\\Tapesmith',
  enabled: true,
  source: 'github:essendyx/tapesmith',
  channel: 'stable',
  auto_install: false,
  last_check: null,
  available: null,
  state: 'idle',
  error: null,
  can_rollback: false,
  idle_ok: false,
  consent_needed: false,
};

const AVAILABLE: UpdateStatus = {
  ...BASE,
  last_check: new Date(Date.now() - 5 * 60_000).toISOString(),
  available: { version: '0.2.1', notes: 'Neue Vorlagen', published: '2026-10-01T12:00:00Z', size: 123456 },
  state: 'ready',
  can_rollback: true,
};

function mockStatus(status: UpdateStatus, extra: Parameters<typeof mockApi>[0] = {}) {
  return mockApi({ 'GET /api/v1/update/status': () => status, ...extra });
}

afterEach(() => restoreAllMocks());

describe('UpdateCard', () => {
  it('nicht installiert: Hinweis und Prüfen-Knopf, kein Installieren', async () => {
    mockStatus({ ...BASE, installed: false, previous: null, root: null });
    renderWithProviders(<UpdateCard />);
    expect(await screen.findByText(/Entwicklung oder nicht installiert: Updates nur in der installierten App/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Updates' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Jetzt prüfen' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Jetzt installieren' })).toBeNull();
    expect(screen.getByText('Laufende Version: 0.2.0')).toBeInTheDocument();
  });

  it('aktuell: nach dem Prüfen „Die installierte Version ist aktuell.“', async () => {
    const api = mockStatus(BASE, {
      'POST /api/v1/update/check': () => ({ ...BASE, last_check: new Date().toISOString() }),
    });
    const { user } = renderWithProviders(<UpdateCard />);
    expect(await screen.findByText('Installierte Version: 0.2.0')).toBeInTheDocument();
    expect(screen.getByText('Noch nicht nach Updates gesucht')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Jetzt prüfen' }));
    expect(await screen.findByText('Die installierte Version ist aktuell.')).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === 'POST' && c.path === '/api/v1/update/check')).toBe(true);
    expect(screen.getByRole('status')).toHaveTextContent('Bereit');
  });

  it('Update verfügbar: Installieren fragt und sendet Version und Route', async () => {
    const api = mockStatus(AVAILABLE, {
      'POST /api/v1/update/install': () => new MockResponse(202, { started: true }),
    });
    const { user } = renderWithProviders(<UpdateCard />, { route: '/einstellungen?abschnitt=updates' });
    expect(await screen.findByRole('heading', { name: 'Version 0.2.1 verfügbar' })).toBeInTheDocument();
    expect(screen.getByText('Neue Vorlagen')).toBeInTheDocument();
    expect(screen.getByText(/Letzte Prüfung: vor \d+ Minuten/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Auf vorige Version zurück' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Jetzt installieren' }));
    const dialog = await findDialogByRole('alertdialog');
    expect(within(dialog).getByText('Version 0.2.1 installieren?')).toBeInTheDocument();
    expect(
      within(dialog).getByText('Tapesmith startet kurz neu und öffnet sich danach mit der neuen Version in einem neuen Browser-Tab.'),
    ).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === '/api/v1/update/install')).toBe(false);
    await user.click(within(dialog).getByRole('button', { name: 'Installieren', hidden: true }));
    await waitFor(() => {
      const call = api.calls.find((c) => c.method === 'POST' && c.path === '/api/v1/update/install');
      expect(call?.body).toEqual({ version: '0.2.1', reopen_route: '/einstellungen?abschnitt=updates' });
    });
  });

  it('nach dem Start der Installation fragt die Karte weiter nach und zeigt einen späteren Fehler', async () => {
    // Der Dienst bereitet das Update im Hintergrund vor: direkt nach 202 meldet er noch „idle“.
    let status: UpdateStatus = { ...AVAILABLE, state: 'idle' };
    let statusCallsAfterInstall = 0;
    let installed = false;
    mockApi({
      'GET /api/v1/update/status': () => {
        if (installed) {
          statusCallsAfterInstall += 1;
          if (statusCallsAfterInstall >= 2) {
            status = { ...status, state: 'failed', error: { code: 'update.checksum_mismatch', message: 'Prüfsumme passt nicht' } };
          }
        }
        return status;
      },
      'POST /api/v1/update/install': () => {
        installed = true;
        return new MockResponse(202, { started: true });
      },
    });
    const { user } = renderWithProviders(<UpdateCard />);
    await user.click(await screen.findByRole('button', { name: 'Jetzt installieren' }));
    const dialog = await findDialogByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Installieren', hidden: true }));
    await waitFor(() => expect(installed).toBe(true));
    // Solange der Dienst noch nichts gemeldet hat, bleibt Installieren gesperrt (kein zweiter Start).
    await waitFor(() => expect(screen.getByRole('button', { name: 'Jetzt installieren' })).toBeDisabled());
    expect(await screen.findByText('Prüfsumme falsch', {}, { timeout: 8000 })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Jetzt installieren' })).toBeEnabled());
  }, 15000);

  it('ein alter Fehlerzustand beendet das Nachfragen nach dem Start nicht', async () => {
    let status: UpdateStatus = {
      ...AVAILABLE,
      state: 'failed',
      error: { code: 'update.download_failed', message: 'Quelle war weg' },
    };
    let installed = false;
    let callsAfter = 0;
    mockApi({
      'GET /api/v1/update/status': () => {
        if (installed) {
          callsAfter += 1;
          if (callsAfter >= 3) status = { ...status, state: 'installing', error: null };
        }
        return status;
      },
      'POST /api/v1/update/install': () => {
        installed = true;
        return new MockResponse(202, { started: true });
      },
    });
    const { user } = renderWithProviders(<UpdateCard />);
    await user.click(await screen.findByRole('button', { name: 'Jetzt installieren' }));
    const dialog = await findDialogByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Installieren', hidden: true }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Update wird installiert'), { timeout: 8000 });
  }, 15000);

  it('Abbrechen im Dialog installiert nicht', async () => {
    const api = mockStatus(AVAILABLE);
    const { user } = renderWithProviders(<UpdateCard />);
    await user.click(await screen.findByRole('button', { name: 'Jetzt installieren' }));
    const dialog = await findDialogByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Abbrechen', hidden: true }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(api.calls.some((c) => c.path === '/api/v1/update/install')).toBe(false);
  });

  it('Rückstellung fragt und ruft rollback', async () => {
    const api = mockStatus({ ...BASE, can_rollback: true }, {
      'POST /api/v1/update/rollback': () => new MockResponse(202, { started: true }),
    });
    const { user } = renderWithProviders(<UpdateCard />);
    await user.click(await screen.findByRole('button', { name: 'Auf vorige Version zurück' }));
    const dialog = await findDialogByRole('alertdialog');
    expect(within(dialog).getByText('Auf Version 0.1.0 zurückstellen?')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Zurückstellen', hidden: true }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/update/rollback')).toBe(true));
  });

  it('Fehler update.signature_invalid zeigt den übersetzten Titel (de)', async () => {
    mockStatus({
      ...BASE,
      state: 'failed',
      error: { code: 'update.signature_invalid', message: 'Signatur passt zu keinem Schlüssel' },
    });
    renderWithProviders(<UpdateCard />);
    expect(await screen.findByText('Signatur ungültig')).toBeInTheDocument();
    expect(screen.getByText('Signatur passt zu keinem Schlüssel')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Letzter Versuch fehlgeschlagen');
  });

  it('Fehler update.signature_invalid zeigt den übersetzten Titel (en)', async () => {
    mockStatus({
      ...BASE,
      state: 'failed',
      error: { code: 'update.signature_invalid', message: 'Signatur passt zu keinem Schlüssel' },
    });
    renderWithProviders(<UpdateCard />, { language: 'en' });
    expect(await screen.findByText('Invalid signature')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Updates' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Check now' })).toBeInTheDocument();
    expect(screen.getByText('Last attempt failed')).toBeInTheDocument();
  });

  it('Fehler beim Prüfen zeigt den Code-Titel', async () => {
    mockStatus(BASE, {
      'POST /api/v1/update/check': () =>
        new MockResponse(409, {
          error: { kind: 'UpdateError', code: 'update.no_trusted_key', message: 'Kein Schlüssel', hint: '', exit_code: 1, details: null },
        }),
    });
    const { user } = renderWithProviders(<UpdateCard />);
    await user.click(await screen.findByRole('button', { name: 'Jetzt prüfen' }));
    expect(await screen.findByText('Kein Update-Schlüssel')).toBeInTheDocument();
  });

  it('englisch: Update verfügbar mit englischen Knöpfen', async () => {
    mockStatus(AVAILABLE);
    renderWithProviders(<UpdateCard />, { language: 'en' });
    expect(await screen.findByRole('heading', { name: 'Version 0.2.1 available' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Install now' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Roll back to previous version' })).toBeInTheDocument();
    expect(screen.getByText('Installed version: 0.2.0')).toBeInTheDocument();
  });

  it('Tastatur: Knöpfe in Tab-Reihenfolge erreichbar, Enter öffnet die Rückfrage', async () => {
    mockStatus(AVAILABLE);
    const { user, container } = renderWithProviders(<UpdateCard />);
    const install = await screen.findByRole('button', { name: 'Jetzt installieren' });
    // Tab-Reihenfolge im DOM (ohne die Hilfselemente von Tabster, die in jsdom den Fokus verlieren)
    const tabbable = Array.from(
      container.querySelectorAll<HTMLElement>('button, a[href], input, [tabindex]'),
    ).filter((el) => !el.hasAttribute('data-tabster-dummy') && el.tabIndex >= 0 && !(el as HTMLButtonElement).disabled);
    expect(tabbable.map((el) => el.textContent)).toEqual(['Jetzt prüfen', 'Jetzt installieren', 'Auf vorige Version zurück']);
    install.focus();
    expect(install).toHaveFocus();
    await user.keyboard('{Enter}');
    const dialog = await findDialogByRole('alertdialog');
    expect(within(dialog).getByText('Version 0.2.1 installieren?')).toBeInTheDocument();
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    const rollback = screen.getByRole('button', { name: 'Auf vorige Version zurück' });
    rollback.focus();
    await user.keyboard(' ');
    expect(await findDialogByRole('alertdialog')).toBeInTheDocument();
  });

  for (const language of ['de', 'en'] as const) {
    for (const [name, status] of [
      ['nicht installiert', { ...BASE, installed: false, previous: null, root: null }],
      ['verfügbar', AVAILABLE],
      ['Fehler', { ...BASE, state: 'failed', error: { code: 'update.checksum_mismatch', message: 'x' } }],
    ] as const) {
      it(`ohne axe-Verletzungen: ${name} (${language})`, async () => {
        mockStatus(status as UpdateStatus);
        const { container } = renderWithProviders(<UpdateCard />, { language });
        await screen.findByRole('status');
        await expectNoA11yViolations(container);
      });
    }
  }
});
