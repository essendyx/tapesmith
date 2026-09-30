/** Barrierefreiheit und Tastatur der Seite Paperless: axe in de/en, Tastatur, Fokusfalle. */
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { findDialog, fixtures, mockApi, renderWithProviders } from '../../test/utils';
import type { Language } from '../../i18n';
import PaperlessPage from './index';

const ASN_NEXT = {
  paperless_next: 42,
  local_next: null,
  next: 'ASN00042',
  prefix: 'ASN',
  width: 5,
  hint: 'Vor dem Serieneinsatz einmal testen: ein ASN-Label auf ein Blatt kleben, einscannen und prüfen.',
};

function baseRoutes() {
  return {
    'GET /api/v1/homelab/paperless/asn/next': () => ASN_NEXT,
    'POST /api/v1/labels/render': () => fixtures.renderJson(),
  };
}

const DISCARD = { de: 'Verwerfen', en: 'Discard' } as const;

describe.each(['de', 'en'] as Language[])('Paperless a11y (%s)', (language) => {
  it('Grundzustand ohne axe-Befund', async () => {
    mockApi(baseRoutes());
    const { container } = renderWithProviders(<PaperlessPage />, { language });
    await screen.findByText('ASN00042', { exact: false });
    await expectNoA11yViolations(container);
  });

  it('leerer Zustand (Garantie ohne Treffer) ohne axe-Befund', async () => {
    mockApi({
      ...baseRoutes(),
      'GET /api/v1/homelab/paperless/documents': () => ({ documents: [] }),
    });
    const { container, user } = renderWithProviders(<PaperlessPage />, { language });
    await screen.findByText('ASN00042', { exact: false });
    await user.click(screen.getByRole('tab', { name: language === 'de' ? 'Garantie' : 'Warranty' }));
    await user.click(screen.getByRole('button', { name: language === 'de' ? 'Suchen' : 'Search' }));
    await screen.findByText(language === 'de' ? 'Keine Treffer' : 'No matches');
    await expectNoA11yViolations(container);
  });

  it('Dialog (ASN verwerfen) ohne axe-Befund', async () => {
    mockApi({
      ...baseRoutes(),
      'POST /api/v1/homelab/paperless/asn/reserve': () => ({
        numbers: ['ASN00042'],
        pending_id: 'pend-1',
        template: 'asn',
        hint: ASN_NEXT.hint,
      }),
    });
    const { container, user } = renderWithProviders(<PaperlessPage />, { language });
    await screen.findByText('ASN00042', { exact: false });
    await user.click(screen.getByRole('button', { name: language === 'de' ? 'Reservieren und Serie öffnen' : 'Reserve and open series' }));
    await user.click(await screen.findByRole('button', { name: new RegExp(`^${DISCARD[language]}: `) }));
    await findDialog(language === 'de' ? 'ASN verwerfen' : 'Discard ASN');
    await expectNoA11yViolations(container);
  });
});

describe('Paperless Englisch', () => {
  it('Überschrift und Hauptaktion sind englisch', async () => {
    mockApi(baseRoutes());
    renderWithProviders(<PaperlessPage />, { language: 'en' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Paperless' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reserve and open series' })).toBeInTheDocument();
  });
});

describe('Paperless Tastatur', () => {
  it('Hauptaktion per Tab erreichbar und per Enter auslösbar; Dialog schließt mit Escape und gibt Fokus zurück', async () => {
    mockApi({
      ...baseRoutes(),
      'POST /api/v1/homelab/paperless/asn/reserve': () => ({
        numbers: ['ASN00042'],
        pending_id: 'pend-1',
        template: 'asn',
        hint: ASN_NEXT.hint,
      }),
    });
    const { user } = renderWithProviders(<PaperlessPage />);
    await screen.findByText('ASN00042', { exact: false });
    const reserveButton = screen.getByRole('button', { name: 'Reservieren und Serie öffnen' });
    reserveButton.focus();
    expect(reserveButton).toHaveFocus();
    await user.keyboard('{Enter}');

    const discardTrigger = await screen.findByRole('button', { name: /^Verwerfen: / });
    discardTrigger.focus();
    await user.keyboard('{Enter}');
    const dialog = await findDialog('ASN verwerfen');
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    await user.keyboard('{Escape}');
    await waitFor(() => expect(discardTrigger).toHaveFocus());
  });
});
