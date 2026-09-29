/** Barrierefreiheit und Tastatur der Aktion-Seite: axe in de und en. */
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { LocationProbe, MockResponse, mockApi, renderWithProviders } from '../../test/utils';
import AktionPage from './index';

describe('Aktion: axe ohne Befund', () => {
  for (const language of ['de', 'en'] as const) {
    it(`lädt (${language})`, async () => {
      mockApi({ 'POST /api/v1/integration/resolve': () => new Promise(() => undefined) });
      const { container } = renderWithProviders(<AktionPage />, {
        route: '/aktion?uri=tapesmith%3A%2F%2Fprint',
        language,
      });
      await screen.findByText(language === 'de' ? 'Aktion wird vorbereitet …' : 'Preparing action …');
      await expectNoA11yViolations(container);
    });

    it(`Fehlerzustand (${language})`, async () => {
      mockApi({
        'POST /api/v1/integration/resolve': () =>
          new MockResponse(422, { error: { kind: 'ValueError', message: 'Unbekannte Aktion', hint: 'URI prüfen', exit_code: 1, details: null } }),
      });
      const { container } = renderWithProviders(<AktionPage />, {
        route: '/aktion?uri=tapesmith%3A%2F%2Fquatsch',
        language,
      });
      await screen.findByText('Unbekannte Aktion');
      await expectNoA11yViolations(container);
    });
  }
});

describe('Aktion: Tastatur', () => {
  it('Hauptaktion im Fehlerzustand ist per Tab erreichbar und per Enter auslösbar', async () => {
    mockApi({
      'POST /api/v1/integration/resolve': () =>
        new MockResponse(422, { error: { kind: 'ValueError', message: 'Unbekannte Aktion', hint: 'URI prüfen', exit_code: 1, details: null } }),
    });
    const { user } = renderWithProviders(
      <>
        <AktionPage />
        <LocationProbe />
      </>,
      { route: '/aktion?uri=tapesmith%3A%2F%2Fquatsch' },
    );
    const button = await screen.findByRole('button', { name: 'Zum Schnelldruck' });
    button.focus();
    expect(button).toHaveFocus();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/schnelldruck'));
  });
});

describe('Aktion: Englisch', () => {
  it('Überschrift und Fehlerkarte sind englisch', async () => {
    mockApi({
      'POST /api/v1/integration/resolve': () =>
        new MockResponse(422, { error: { kind: 'ValueError', message: 'Unbekannte Aktion', hint: 'URI prüfen', exit_code: 1, details: null } }),
    });
    renderWithProviders(<AktionPage />, { route: '/aktion?uri=tapesmith%3A%2F%2Fquatsch', language: 'en' });
    expect(await screen.findByRole('heading', { level: 1, name: 'What should be printed?' })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Go to quick print' })).toBeInTheDocument();
  });
});
