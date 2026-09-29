import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { TemplateGrid } from './TemplateGrid';
import type { FamilyTemplate } from './types';

function template(o: Partial<FamilyTemplate> = {}): FamilyTemplate {
  return { name: 'gefriergut', title: 'Gefriergut', description: 'Für die Gefriertruhe', category: 'küche', fields: [], sample: {}, ...o };
}

describe('TemplateGrid', () => {
  it('wiederholt die Beschreibung nicht, wenn sie schon der Titel ist (title = Beschreibung)', () => {
    const long = 'Gefriergut mit Haltbarkeit: Inhalt, Einfrierdatum und errechnetes Verbrauchsdatum je Kategorie.';
    render(<TemplateGrid templates={[template({ title: long, description: long })]} onSelect={() => undefined} />);
    expect(screen.getAllByText(long)).toHaveLength(1);
  });

  it('zeigt eine abweichende Beschreibung unter dem Titel', () => {
    render(<TemplateGrid templates={[template()]} onSelect={() => undefined} />);
    expect(screen.getByText('Gefriergut')).toBeInTheDocument();
    expect(screen.getByText('Für die Gefriertruhe')).toBeInTheDocument();
  });
});
