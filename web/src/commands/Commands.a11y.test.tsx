/** Kommandopalette: axe ohne Befund in de und en, Treffer mit Kürzel, übersetzte Texte. */
import { describe, expect, it } from 'vitest';
import { screen, within } from '@testing-library/react';
import { expectNoA11yViolations } from '../test/a11y';
import { fixtures, LocationProbe, mockApi, renderWithProviders } from '../test/utils';

const TEXT = {
  de: { nav: 'Seiten', search: 'Befehl suchen', list: 'Befehle', goto: 'Gehe zu Editor', key: 'Strg+2', empty: 'Keine Treffer' },
  en: { nav: 'Pages', search: 'Search commands', list: 'Commands', goto: 'Go to Editor', key: 'Ctrl+2', empty: 'No matches' },
} as const;

describe('Kommandopalette a11y', () => {
  for (const language of ['de', 'en'] as const) {
    it(`offen ohne axe-Befund, aria-activedescendant und Kürzel (${language})`, async () => {
      const text = TEXT[language];
      mockApi({ 'GET /api/v1/status': () => fixtures.statusJson }, { quiet: true });
      const { user } = renderWithProviders(<LocationProbe />, { withShell: true, route: '/schnelldruck', language });
      await screen.findByRole('navigation', { name: text.nav });
      await user.keyboard('{Control>}k{/Control}');
      const input = await screen.findByRole('combobox', { name: text.search });
      await user.type(input, language === 'de' ? 'gehe zu' : 'go to');
      const list = screen.getByRole('listbox', { name: text.list });
      const option = within(list).getByText(text.goto).closest('[role="option"]');
      expect(option).toHaveTextContent(text.key);
      const active = input.getAttribute('aria-activedescendant');
      expect(active && document.getElementById(active)).toHaveAttribute('aria-selected', 'true');
      await expectNoA11yViolations(document.body);
      await user.clear(input);
      await user.type(input, 'zzzzqqq');
      expect(screen.getByText(text.empty)).toBeInTheDocument();
      await expectNoA11yViolations(document.body);
    });
  }
});
