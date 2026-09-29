import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { LoadingState } from '../LoadingState';
import { renderWithProviders } from '../../test/utils';
import { expectNoA11yViolations } from '../../test/a11y';

const VARIANTS = ['page', 'section', 'list', 'inline'] as const;

describe('LoadingState', () => {
  for (const variant of VARIANTS) {
    it(`${variant}: aria-busy und Screenreader-Text`, () => {
      const { container } = renderWithProviders(<LoadingState variant={variant} rows={3} />);
      const busy = container.querySelector('[aria-busy="true"]');
      expect(busy).not.toBeNull();
      const hidden = busy?.querySelector('.p12-visually-hidden');
      expect(hidden).toHaveTextContent('Wird geladen …');
    });
  }

  it('eigene Beschriftung und Zeilenzahl', () => {
    const { container } = renderWithProviders(<LoadingState variant="list" rows={4} label="Vorlagen werden geladen" />);
    expect(screen.getByText('Vorlagen werden geladen')).toHaveClass('p12-visually-hidden');
    expect(container.querySelectorAll('.fui-SkeletonItem')).toHaveLength(4);
  });

  it('Standardtext auf Englisch', () => {
    const { container } = renderWithProviders(<LoadingState />, { language: 'en' });
    expect(container.querySelector('.p12-visually-hidden')).toHaveTextContent('Loading …');
  });

  for (const language of ['de', 'en'] as const) {
    it(`ohne axe-Verletzungen (${language})`, async () => {
      const { container } = renderWithProviders(
        <main>
          {VARIANTS.map((v) => (
            <LoadingState key={v} variant={v} />
          ))}
        </main>,
        { language },
      );
      await expectNoA11yViolations(container);
    });
  }
});
