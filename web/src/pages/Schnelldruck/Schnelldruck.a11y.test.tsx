/** Barrierefreiheit und Tastatur der Schnelldruck-Seite: axe in de und en. */
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { findDialogByRole, fixtures, mockApi, renderWithProviders } from '../../test/utils';
import type { Language } from '../../i18n';
import SchnelldruckPage from './index';

function baseRoutes(overrides: Record<string, (req: { body: unknown }) => unknown> = {}) {
  return {
    'GET /api/v1/labels/fonts': () => ({ fonts: [{ id: 'default', name: 'Standard' }] }),
    'GET /api/v1/labels/recent-texts': () => ({ items: [] }),
    'POST /api/v1/connection/preconnect': () => ({}),
    'POST /api/v1/labels/render': () => fixtures.renderJson(),
    ...overrides,
  };
}

async function waitForPreview() {
  await waitFor(() => expect(screen.getByRole('img')).toBeInTheDocument());
}

const FIELD_LABEL: Record<Language, string> = { de: 'Labeltext', en: 'Label text' };

describe('Schnelldruck: axe ohne Befund', () => {
  for (const language of ['de', 'en'] as const) {
    it(`Grundzustand mit Vorschau und letzten Texten (${language})`, async () => {
      mockApi(baseRoutes({ 'GET /api/v1/labels/recent-texts': () => ({ items: [['Letzter Text']] }) }));
      const { user, container } = renderWithProviders(<SchnelldruckPage />, { language });
      const textarea = screen.getByRole('textbox', { name: FIELD_LABEL[language] });
      await user.type(textarea, 'X');
      await waitForPreview();
      await expectNoA11yViolations(container);
    });

    it(`leerer Zustand ohne Text und ohne letzte Texte (${language})`, async () => {
      const { container } = renderWithProviders(<SchnelldruckPage />, { language });
      await screen.findByRole('textbox', { name: FIELD_LABEL[language] });
      await expectNoA11yViolations(container);
    });

    it(`Bestätigungsdialog (${language})`, async () => {
      mockApi(
        baseRoutes({
          'POST /api/v1/labels/print': () => fixtures.outcomeJson({ status: 'bestätigung_nötig', reasons: ['Band fast leer'] }),
        }),
      );
      const { user } = renderWithProviders(<SchnelldruckPage />, { language });
      const textarea = screen.getByRole('textbox', { name: FIELD_LABEL[language] });
      await user.type(textarea, 'X');
      await waitForPreview();
      await user.keyboard('{Enter}');
      await findDialogByRole('alertdialog');
      await expectNoA11yViolations(document.body);
    });
  }
});

describe('Schnelldruck: Tastatur', () => {
  it('Hauptaktion ist per Tab erreichbar und druckt mit Enter', async () => {
    const api = mockApi(baseRoutes({ 'POST /api/v1/labels/print': () => fixtures.outcomeJson({ status: 'ok', title: 'X' }) }));
    const { user } = renderWithProviders(<SchnelldruckPage />);
    const textarea = screen.getByRole('textbox', { name: 'Labeltext' });
    await user.type(textarea, 'X');
    await waitForPreview();
    const button = screen.getByRole('button', { name: /^Drucken/ });
    button.focus();
    expect(button).toHaveFocus();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
  });

  it('Bestätigungsdialog schließt mit Escape und gibt den Fokus an den Auslöser zurück', async () => {
    mockApi(
      baseRoutes({
        'POST /api/v1/labels/print': () => fixtures.outcomeJson({ status: 'bestätigung_nötig', reasons: ['Band fast leer'] }),
      }),
    );
    const { user } = renderWithProviders(<SchnelldruckPage />);
    const textarea = screen.getByRole('textbox', { name: 'Labeltext' });
    await user.type(textarea, 'X');
    await waitForPreview();
    const button = screen.getByRole('button', { name: /^Drucken/ });
    await user.click(button);
    await findDialogByRole('alertdialog');
    await user.keyboard('{Escape}');
    // Der gemeinsame ConfirmProvider gibt den Fokus beim Schließen an den Auslöser zurück.
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    await waitFor(() => expect(button).toHaveFocus());
  });
});

describe('Schnelldruck: Englisch', () => {
  it('Überschrift und Hauptaktion sind englisch', async () => {
    mockApi(baseRoutes());
    const language: Language = 'en';
    renderWithProviders(<SchnelldruckPage />, { language });
    expect(screen.getByRole('heading', { level: 1, name: 'Quick print' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Print (1 label)' })).toBeInTheDocument();
  });
});
