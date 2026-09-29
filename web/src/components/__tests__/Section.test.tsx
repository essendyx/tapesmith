import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { Section } from '../Section';
import { renderWithProviders } from '../../test/utils';
import { expectNoA11yViolations } from '../../test/a11y';

describe('Section', () => {
  it('Titel als h2, Region über aria-labelledby benannt, id am section', () => {
    renderWithProviders(
      <Section id="druck" title="Druck" description="Einstellungen für den Druck">
        <p>Inhalt</p>
      </Section>,
    );
    const heading = screen.getByRole('heading', { level: 2, name: 'Druck' });
    const region = screen.getByRole('region', { name: 'Druck' });
    expect(region.tagName).toBe('SECTION');
    expect(region).toHaveAttribute('id', 'druck');
    expect(region.getAttribute('aria-labelledby')).toBe(heading.id);
    expect(screen.getByText('Einstellungen für den Druck')).toBeInTheDocument();
  });

  it('headingLevel 3 ergibt h3', () => {
    renderWithProviders(
      <Section title="Unterpunkt" headingLevel={3}>
        <p>x</p>
      </Section>,
    );
    expect(screen.getByRole('heading', { level: 3, name: 'Unterpunkt' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { level: 2 })).toBeNull();
  });

  it('ohne Titel kein aria-labelledby, flush ohne Fehler', () => {
    const { container } = renderWithProviders(
      <Section flush>
        <table aria-label="Tabelle">
          <tbody>
            <tr>
              <td>1</td>
            </tr>
          </tbody>
        </table>
      </Section>,
    );
    const section = container.querySelector('section');
    expect(section).not.toBeNull();
    expect(section?.hasAttribute('aria-labelledby')).toBe(false);
  });

  for (const language of ['de', 'en'] as const) {
    it(`ohne axe-Verletzungen (${language})`, async () => {
      const { container } = renderWithProviders(
        <main>
          <h1>Seite</h1>
          <Section title="Druck" actions={<button type="button">Aktion</button>}>
            <p>Inhalt</p>
          </Section>
        </main>,
        { language },
      );
      await expectNoA11yViolations(container);
    });
  }
});
