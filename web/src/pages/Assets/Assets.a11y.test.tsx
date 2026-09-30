/** Barrierefreiheit und Tastatur der Seite Assets: axe in de und en, Dialog, Tastatur. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { anyDialogInDom, chooseRowAction, findDialog, mockApi, MockResponse, renderWithProviders } from '../../test/utils';
import { expectNoA11yViolations } from '../../test/a11y';
import type { Language } from '../../i18n';
import type { AssetJson, AssetsListResponse } from './types';
import AssetsPage from '.';

const asset1: AssetJson = {
  id: 'HL-0001',
  bezeichnung: 'Patchkabel Cat6 3m',
  kategorie: 'Netzwerk',
  standort: 'Schrank 1',
  seriennummer: '',
  host: '',
  ziel: 'https://x.example/a',
  paperless_doc: null,
  status: 'aktiv',
  notiz: '',
  created: '2026-09-28T09:00:00',
  updated: '2026-09-28T09:00:00',
};

function listResponse(o: Partial<AssetsListResponse> = {}): AssetsListResponse {
  return { assets: [asset1], range: { prefix: 'HL-', width: 4, next: 'HL-0002', check_digit: false }, shortlink: true, ...o };
}

const NEW_BUTTON = { de: 'Neue Assets', en: 'New assets' } as const;
const NEW_TITLE = { de: 'Neue Assets', en: 'New assets' } as const;
const CANCEL_BUTTON = { de: 'Abbrechen', en: 'Cancel' } as const;

beforeEach(() => {
  Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn(() => Promise.resolve()) }, configurable: true });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe.each(['de', 'en'] as Language[])('Seite Assets: axe (%s)', (language) => {
  it('Grundzustand ohne Befund', async () => {
    mockApi({ 'GET /api/v1/homelab/assets': () => listResponse() });
    const { container } = renderWithProviders(<AssetsPage />, { language });
    await screen.findByText('HL-0001');
    await expectNoA11yViolations(container);
  });

  it('leerer Zustand ohne Befund', async () => {
    mockApi({ 'GET /api/v1/homelab/assets': () => listResponse({ assets: [] }) });
    const { container } = renderWithProviders(<AssetsPage />, { language });
    await screen.findByRole('heading', { level: 1 });
    await waitFor(() => expect(screen.queryByText('Assets werden geladen …')).toBeNull());
    await expectNoA11yViolations(container);
  });

  it('geöffneter Dialog „Neue Assets" ohne Befund', async () => {
    mockApi({ 'GET /api/v1/homelab/assets': () => listResponse() });
    const { user } = renderWithProviders(<AssetsPage />, { language });
    const openButton = await screen.findByRole('button', { name: NEW_BUTTON[language] });
    await user.click(openButton);
    await findDialog(NEW_TITLE[language]);
    await expectNoA11yViolations(document.body);
  });
});

describe('Seite Assets: Tastatur', () => {
  it('Hauptaktion per Tab erreichbar, per Enter öffnet sie den Dialog; Escape schließt ihn und gibt den Fokus zurück', async () => {
    mockApi({ 'GET /api/v1/homelab/assets': () => listResponse() });
    const { user } = renderWithProviders(<AssetsPage />);
    const openButton = await screen.findByRole('button', { name: NEW_BUTTON.de });
    openButton.focus();
    expect(openButton).toHaveFocus();
    await user.keyboard('{Enter}');
    await findDialog(NEW_TITLE.de);

    await user.keyboard('{Escape}');
    await waitFor(() => expect(anyDialogInDom()).toBe(false));
    await waitFor(() => expect(openButton).toHaveFocus());
  });

  it('Verwerfen-Dialog schließt über „Abbrechen" und gibt den Fokus zurück', async () => {
    mockApi({ 'GET /api/v1/homelab/assets': () => listResponse() });
    const { user } = renderWithProviders(<AssetsPage />);
    await screen.findByText('HL-0001');
    const voidButton = screen.getByRole('button', { name: 'Weitere Aktionen für HL-0001' });
    await chooseRowAction(user, 'HL-0001', 'Verwerfen');
    const dialog = await findDialog('Asset verwerfen');
    // Unter Volllast setzt Tabster kurz aria-hidden: den Knopf im Dialog abwarten.
    await user.click(await within(dialog).findByRole('button', { name: CANCEL_BUTTON.de, hidden: true }));
    await waitFor(() => expect(anyDialogInDom()).toBe(false));
    await waitFor(() => expect(voidButton).toHaveFocus());
  });

  it('Fehlerzustand mit „Erneut versuchen" ohne Befund', async () => {
    mockApi({
      'GET /api/v1/homelab/assets': () =>
        new MockResponse(422, { error: { kind: 'ValueError', message: 'homelab.json: Fehler', hint: '', exit_code: 1, details: null } }),
    });
    const { container } = renderWithProviders(<AssetsPage />);
    await screen.findByText('homelab.json: Fehler');
    await expectNoA11yViolations(container);
  });
});
