import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders, restoreAllMocks } from '../../test/utils';
import type { TemplateSummary } from '../../api/types';
import { GalleryTile } from './GalleryTile';

afterEach(() => restoreAllMocks());

const template: TemplateSummary = {
  name: 'datentraeger',
  description: 'SSD',
  category: 'Datenträger',
  tags: [],
  kind: 'layout',
  builtin: true,
  favorite: false,
  target: null,
  tapes: [],
  default_copies: 1,
  input_fields: [],
  sample: {},
};

function renderTile() {
  const onUse = vi.fn();
  const onToggleFavorite = vi.fn();
  renderWithProviders(
    <GalleryTile
      template={template}
      tape={undefined}
      favorite={false}
      onToggleFavorite={onToggleFavorite}
      onUse={onUse}
      onEdit={vi.fn()}
      onBatch={vi.fn()}
      onExport={vi.fn()}
      onDelete={vi.fn()}
    />,
  );
  return { onUse, onToggleFavorite };
}

describe('GalleryTile Tastatur', () => {
  it('Die Kachel ist ein Knopf: Enter und Leertaste lösen onUse aus, kein verschachteltes Interaktives', async () => {
    const user = userEvent.setup();
    const { onUse } = renderTile();
    const open = screen.getByRole('button', { name: 'Vorlage datentraeger' });
    open.focus();
    await user.keyboard('{Enter}');
    await user.keyboard(' ');
    expect(onUse).toHaveBeenCalledTimes(2);
  });

  it('Enter oder Leertaste auf Stern und Menüknopf lösen onUse nicht aus', () => {
    const { onUse } = renderTile();
    const star = screen.getByRole('button', { name: 'Als Favorit merken' });
    const more = screen.getByRole('button', { name: 'Weitere Aktionen für datentraeger' });
    for (const el of [star, more]) {
      fireEvent.keyDown(el, { key: 'Enter' });
      fireEvent.keyDown(el, { key: ' ' });
    }
    expect(onUse).not.toHaveBeenCalled();
  });

  it('Stern-Knopf schaltet den Favoritenstatus um, ohne die Kachel zu öffnen', async () => {
    const { onUse, onToggleFavorite } = renderTile();
    const star = screen.getByRole('button', { name: 'Als Favorit merken' });
    fireEvent.click(star);
    expect(onToggleFavorite).toHaveBeenCalledTimes(1);
    expect(onUse).not.toHaveBeenCalled();
  });
});

describe('GalleryTile Titel', () => {
  it('zeigt den übersetzten Titel statt der ID, das Vorschaubild behält die ID', () => {
    renderWithProviders(
      <GalleryTile
        template={{ ...template, name: 'gefriergut', title: 'freezer' }}
        tape={undefined}
        favorite={false}
        onToggleFavorite={vi.fn()}
        onUse={vi.fn()}
        onEdit={vi.fn()}
        onBatch={vi.fn()}
        onExport={vi.fn()}
        onDelete={vi.fn()}
      />,
      { language: 'en' },
    );
    expect(screen.getByRole('heading', { name: 'freezer' })).toBeInTheDocument();
    const img = document.querySelector('img');
    expect(img?.getAttribute('src') ?? '').toContain('/api/v1/gallery/thumb/gefriergut.png');
    expect(img?.getAttribute('src') ?? '').toContain('lang=en');
  });
});
