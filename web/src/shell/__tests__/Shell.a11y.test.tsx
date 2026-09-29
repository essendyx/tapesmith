/** Barrierefreiheit der Hülle: axe in de und en, ausgeklappt, eingeklappt und schmal; Sprungmarke. */
import { afterEach, describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { findDialogByRole, fixtures, LocationProbe, mockApi, mockNarrowScreen, renderWithProviders } from '../../test/utils';
import type { Language } from '../../i18n';
import { NAV_COLLAPSED_KEY } from '../AppShell';

function statistikApi() {
  return mockApi(
    {
      'GET /api/v1/status': () => fixtures.statusJson,
      'GET /api/v1/stats': () => ({
        by: 'monat',
        rows: [{ key: '2026-09', jobs: 3, labels: 5, tape_mm: 150 }],
        totals: { key: 'gesamt', jobs: 3, labels: 5, tape_mm: 150 },
      }),
      'GET /api/v1/stats/rolls': () => ({ rolls: [] }),
      'GET /api/v1/drafts': () => ({ drafts: [], own: [], orphaned: [] }),
      'POST /api/v1/drafts/heartbeat': () => ({ alive_s: 90 }),
    },
    { quiet: true },
  );
}

const NAV = { de: 'Seiten', en: 'Pages' } as const;

async function renderShell(language: Language) {
  statistikApi();
  const result = renderWithProviders(<LocationProbe />, { withShell: true, route: '/statistik', language });
  await screen.findByText('2026-09');
  await screen.findByRole('navigation', { name: NAV[language] });
  return result;
}

/** Erstes Element der Tab-Reihenfolge (ohne Tabsters Wächter-Elemente, ohne tabindex=-1). */
function firstTabbable(): Element | null {
  const selector = 'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]';
  return (
    [...document.querySelectorAll(selector)].find(
      (el) => !el.hasAttribute('data-tabster-dummy') && el.getAttribute('tabindex') !== '-1' && !el.closest('[hidden]'),
    ) ?? null
  );
}

let restoreScreen: (() => void) | null = null;

afterEach(() => {
  restoreScreen?.();
  restoreScreen = null;
});

describe('Hülle: axe ohne Befund', () => {
  for (const language of ['de', 'en'] as const) {
    it(`ausgeklappt (${language})`, async () => {
      const { container } = await renderShell(language);
      expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
      await expectNoA11yViolations(container);
    });

    it(`eingeklappt (${language})`, async () => {
      localStorage.setItem(NAV_COLLAPSED_KEY, '1');
      const { container } = await renderShell(language);
      expect(screen.getByRole('button', { name: language === 'de' ? 'Seitenleiste ausklappen' : 'Expand sidebar' })).toBeInTheDocument();
      await expectNoA11yViolations(container);
    });

    it(`schmal mit offener Schublade (${language})`, async () => {
      restoreScreen = mockNarrowScreen(true);
      statistikApi();
      const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/statistik', language });
      await screen.findByText('2026-09');
      await user.click(screen.getByRole('button', { name: language === 'de' ? 'Menü' : 'Menu' }));
      await findDialogByRole('dialog', NAV[language]);
      await expectNoA11yViolations(document.body);
    });
  }

  it('Englisch: Seitenleiste, Pfad und Kopfzeile sind englisch', async () => {
    await renderShell('en');
    expect(screen.getByTestId('page-title')).toHaveTextContent('Statistics');
    expect(screen.getByRole('button', { name: 'Quick print' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Keyboard shortcuts' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Commands (Ctrl+K)' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Skip to content' })).toBeInTheDocument();
  });
});

describe('Sprungmarke', () => {
  it('erste Tab-Taste fokussiert „Zum Inhalt springen“, Enter springt nach #inhalt', async () => {
    const { user } = await renderShell('de');
    const link = screen.getByRole('link', { name: 'Zum Inhalt springen' });
    // Tabsters Wächter-Elemente leiten den Fokus in jsdom nicht weiter (keine Layout-Sichtbarkeit),
    // deshalb wird die Tab-Reihenfolge hier aus dem DOM bestimmt: erstes fokussierbares Element.
    expect(firstTabbable()).toBe(link);
    link.focus();
    expect(link).toHaveFocus();
    expect(link).toHaveAttribute('href', '#inhalt');
    await user.keyboard('{Enter}');
    const main = screen.getByRole('main');
    expect(main).toHaveAttribute('id', 'inhalt');
    await waitFor(() => expect(main).toHaveFocus());
  });
});
