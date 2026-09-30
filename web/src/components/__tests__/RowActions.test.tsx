import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { Button } from '@fluentui/react-components';
import { expectNoA11yViolations } from '../../test/a11y';
import { renderWithProviders } from '../../test/utils';
import { DataList, type ListColumn } from '../DataList';
import { RowActions } from '../RowActions';

interface Row {
  id: number;
  title: string;
  mm: number;
}

const rows: Row[] = [
  { id: 1, title: 'pmx10 SSD-1', mm: 43 },
  { id: 2, title: 'nas eth0', mm: 136 },
];

function List(props: { onEdit: (row: Row) => void; onDelete: (row: Row) => void }): JSX.Element {
  const columns: ListColumn<Row>[] = [
    { id: 'title', header: 'Titel', kind: 'title', cell: (r) => r.title },
    { id: 'mm', header: 'Länge', kind: 'number', cell: (r) => `${r.mm} mm` },
    {
      id: 'actions',
      header: 'Aktionen',
      kind: 'actions',
      cell: (r) => (
        <RowActions
          title={r.title}
          primary={<Button aria-label={`Drucken: ${r.title}`}>Drucken</Button>}
          actions={[
            { key: 'edit', label: 'Bearbeiten', onClick: () => props.onEdit(r) },
            { key: 'hidden', label: 'Unsichtbar', hidden: true },
            { key: 'delete', label: 'Löschen', danger: true, onClick: () => props.onDelete(r) },
          ]}
        />
      ),
    },
  ];
  return (
    <main>
      <DataList items={rows} columns={columns} getKey={(r) => r.id} label="Einträge" />
    </main>
  );
}

describe('RowActions und DataList', () => {
  it('ein Hauptknopf je Zeile, Mehr-Menü mit eindeutigem Namen, per Tastatur bedienbar', async () => {
    const onEdit = vi.fn();
    const { user, container } = renderWithProviders(<List onEdit={onEdit} onDelete={vi.fn()} />);
    expect(screen.getByRole('table', { name: 'Einträge' })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /^Drucken: / })).toHaveLength(2);
    const more = screen.getByRole('button', { name: 'Weitere Aktionen für nas eth0' });
    expect(screen.getByRole('button', { name: 'Weitere Aktionen für pmx10 SSD-1' })).not.toBe(more);
    await expectNoA11yViolations(container);

    more.focus();
    await user.keyboard('{Enter}');
    const items = await screen.findAllByRole('menuitem');
    expect(items.map((i) => i.textContent)).toEqual(['Bearbeiten', 'Löschen']);
    (items[0] as HTMLElement).focus();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(onEdit).toHaveBeenCalledWith(rows[1]));
  });

  it('Zahlenspalten rechtsbündig, Aktionsspalte ohne sichtbaren Kopf', () => {
    renderWithProviders(<List onEdit={vi.fn()} onDelete={vi.fn()} />);
    const cell = screen.getByText('136 mm');
    expect(getComputedStyle(cell).textAlign).toBe('right');
    expect(screen.getByText('Aktionen')).toHaveClass('p12-visually-hidden');
  });
});
