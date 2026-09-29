import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { Button } from '@fluentui/react-components';
import { PageHeader } from '../PageHeader';
import { renderWithProviders } from '../../test/utils';
import { expectNoA11yViolations } from '../../test/a11y';

function ui() {
  return (
    <main>
      <PageHeader
        title="Schnelldruck"
        subtitle={<span>Text eingeben und drucken</span>}
        breadcrumb={<a href="/start">Start</a>}
        actions={<Button>Drucken</Button>}
      />
    </main>
  );
}

describe('PageHeader', () => {
  it('rendert genau ein h1, Untertitel, Aktionen und Pfad', () => {
    renderWithProviders(ui());
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Schnelldruck');
    expect(screen.getByText('Text eingeben und drucken')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Drucken' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Pfad' })).toBeInTheDocument();
  });

  it('ohne Pfad keine Navigation', () => {
    renderWithProviders(<PageHeader title="Verlauf" />);
    expect(screen.queryByRole('navigation')).toBeNull();
  });

  it('Pfad-Beschriftung auf Englisch', () => {
    renderWithProviders(ui(), { language: 'en' });
    expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toBeInTheDocument();
  });

  for (const language of ['de', 'en'] as const) {
    it(`ohne axe-Verletzungen (${language})`, async () => {
      const { container } = renderWithProviders(ui(), { language });
      await expectNoA11yViolations(container);
    });
  }
});
