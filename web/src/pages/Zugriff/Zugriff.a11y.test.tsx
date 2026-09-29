/** Barrierefreiheit und Tastatur der Seite Zugriff: axe in de und en, Dialog, Tastatur. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { anyDialogInDom, findDialog, mockApi, MockResponse, renderWithProviders } from '../../test/utils';
import type { Language } from '../../i18n';
import { baseAccessRoutes, makeAccess } from './testFixtures';
import ZugriffPage from './index';

const FORBIDDEN_BODY = {
  error: { kind: 'Forbidden', message: 'Keine Berechtigung für diese Aktion', hint: '', exit_code: 1, details: null },
};

const NEW_TOKEN_BUTTON = { de: 'Neues Token', en: 'New token' } as const;
const NEW_TOKEN_TITLE = { de: 'Neues Token', en: 'New token' } as const;
const CANCEL_BUTTON = { de: 'Abbrechen', en: 'Cancel' } as const;

beforeEach(() => {
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn(() => Promise.resolve()) },
    configurable: true,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe.each(['de', 'en'] as Language[])('Seite Zugriff: axe (%s)', (language) => {
  it('Grundzustand ohne Befund', async () => {
    mockApi(baseAccessRoutes());
    const { container } = renderWithProviders(<ZugriffPage />, { route: '/zugriff', language });
    await screen.findByRole('heading', { level: 1 });
    await expectNoA11yViolations(container);
  });

  it('leerer Zustand (keine Tokens) ohne Befund', async () => {
    mockApi(baseAccessRoutes({ 'GET /api/v1/access': () => makeAccess({ tokens: [] }) }));
    const { container } = renderWithProviders(<ZugriffPage />, { route: '/zugriff', language });
    await screen.findByRole('heading', { level: 1 });
    await expectNoA11yViolations(container);
  });

  it('Fehlerzustand (403) ohne Befund', async () => {
    mockApi(baseAccessRoutes({ 'GET /api/v1/access': () => new MockResponse(403, FORBIDDEN_BODY) }));
    const { container } = renderWithProviders(<ZugriffPage />, { route: '/zugriff', language });
    await screen.findByRole('heading', { level: 1 });
    await expectNoA11yViolations(container);
  });

  it('geöffneter Dialog „Neues Token“ ohne Befund', async () => {
    mockApi(baseAccessRoutes());
    const { user } = renderWithProviders(<ZugriffPage />, { route: '/zugriff', language });
    const openButton = await screen.findByRole('button', { name: NEW_TOKEN_BUTTON[language] });
    await user.click(openButton);
    await findDialog(NEW_TOKEN_TITLE[language]);
    await expectNoA11yViolations(document.body);
  });
});

describe('Seite Zugriff: Tastatur', () => {
  it('Hauptaktion per Tab erreichbar, per Enter öffnet sie den Dialog; Escape schließt ihn und gibt den Fokus zurück', async () => {
    mockApi(baseAccessRoutes());
    const { user } = renderWithProviders(<ZugriffPage />, { route: '/zugriff' });
    const openButton = await screen.findByRole('button', { name: NEW_TOKEN_BUTTON.de });

    openButton.focus();
    expect(openButton).toHaveFocus();
    await user.keyboard('{Enter}');

    const dialog = await findDialog(NEW_TOKEN_TITLE.de);
    expect(dialog).toBeInTheDocument();

    await user.keyboard('{Escape}');
    await waitFor(() => expect(anyDialogInDom()).toBe(false));
    await waitFor(() => expect(openButton).toHaveFocus());
  });

  it('Dialog schließt auch über den Knopf „Abbrechen“ und gibt den Fokus zurück', async () => {
    mockApi(baseAccessRoutes());
    const { user } = renderWithProviders(<ZugriffPage />, { route: '/zugriff' });
    const openButton = await screen.findByRole('button', { name: NEW_TOKEN_BUTTON.de });
    await user.click(openButton);
    const dialog = await findDialog(NEW_TOKEN_TITLE.de);
    // Unter Volllast setzt Tabster kurz aria-hidden: den Knopf im Dialog abwarten.
    await user.click(await within(dialog).findByRole('button', { name: CANCEL_BUTTON.de, hidden: true }));
    await waitFor(() => expect(anyDialogInDom()).toBe(false));
  });
});
