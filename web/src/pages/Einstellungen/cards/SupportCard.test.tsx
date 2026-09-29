import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { SupportCard } from './SupportCard';
import { MockResponse, mockApi, renderWithProviders, restoreAllMocks } from '../../../test/utils';
import { expectNoA11yViolations } from '../../../test/a11y';

let originalCreate: typeof URL.createObjectURL;
let originalRevoke: typeof URL.revokeObjectURL;

beforeEach(() => {
  originalCreate = URL.createObjectURL;
  originalRevoke = URL.revokeObjectURL;
  URL.createObjectURL = vi.fn(() => 'blob:mock');
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  URL.createObjectURL = originalCreate;
  URL.revokeObjectURL = originalRevoke;
  restoreAllMocks();
});

describe('SupportCard', () => {
  it('zeigt Titel und Text, „Problem melden“ lädt POST /support/report und meldet Erfolg', async () => {
    const api = mockApi({
      'POST /api/v1/support/report': () => new MockResponse(200, 'PK...', { 'Content-Type': 'application/zip' }),
    });
    const { user } = renderWithProviders(<SupportCard />);
    expect(screen.getByRole('heading', { name: 'Hilfe und Diagnose' })).toBeInTheDocument();
    expect(
      screen.getByText(
        'Erstellt ein Zip mit Version, Status und Logs zum Weitergeben. Tokens und Passwörter werden entfernt, es wird nichts verschickt.',
      ),
    ).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Problem melden' }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/support/report' && c.method === 'POST')).toBe(true));
    expect(await screen.findByText('Bericht heruntergeladen')).toBeInTheDocument();
  });

  it('Fehler beim Herunterladen zeigt eine Meldung', async () => {
    mockApi({
      'POST /api/v1/support/report': () =>
        new MockResponse(500, { error: { kind: 'ValueError', message: 'Bericht fehlgeschlagen', hint: '', exit_code: 1, details: null } }),
    });
    const { user } = renderWithProviders(<SupportCard />);
    await user.click(screen.getByRole('button', { name: 'Problem melden' }));
    expect(await screen.findByText('Bericht fehlgeschlagen')).toBeInTheDocument();
  });

  it('ohne axe-Befund', async () => {
    mockApi({ 'POST /api/v1/support/report': () => new MockResponse(200, 'PK...', { 'Content-Type': 'application/zip' }) });
    const { container } = renderWithProviders(<SupportCard />);
    await expectNoA11yViolations(container);
  });

  it('Englisch: Titel und Knopf', async () => {
    mockApi({ 'POST /api/v1/support/report': () => new MockResponse(200, 'PK...', { 'Content-Type': 'application/zip' }) });
    renderWithProviders(<SupportCard />, { language: 'en' });
    expect(screen.getByRole('heading', { name: 'Help and diagnostics' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Report a problem' })).toBeInTheDocument();
  });
});
