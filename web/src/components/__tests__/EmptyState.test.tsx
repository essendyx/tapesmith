import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { Button } from '@fluentui/react-components';
import { EmptyState } from '../EmptyState';
import { renderWithProviders } from '../../test/utils';
import { expectNoA11yViolations } from '../../test/a11y';

describe('EmptyState', () => {
  it('hat role=status, Titel, Text und Aktion', () => {
    renderWithProviders(<EmptyState title="Noch keine Box" body="Legen Sie die erste Box an." action={<Button>Box anlegen</Button>} />);
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent('Noch keine Box');
    expect(screen.getByRole('heading', { level: 2, name: 'Noch keine Box' })).toBeInTheDocument();
    expect(screen.getByText('Legen Sie die erste Box an.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Box anlegen' })).toBeInTheDocument();
  });

  it('compact nutzt h3', () => {
    renderWithProviders(<EmptyState compact title="Keine Treffer" />);
    expect(screen.getByRole('heading', { level: 3, name: 'Keine Treffer' })).toBeInTheDocument();
  });

  for (const language of ['de', 'en'] as const) {
    it(`ohne axe-Verletzungen (${language})`, async () => {
      const { container } = renderWithProviders(
        <main>
          <h1>Seite</h1>
          <EmptyState title="Leer" body="Nichts da." action={<Button>Anlegen</Button>} />
        </main>,
        { language },
      );
      await expectNoA11yViolations(container);
    });
  }
});
