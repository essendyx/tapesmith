import { describe, expect, it } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithProviders } from '../../test/utils';
import { FieldRow, FieldRows } from './FieldRow';

describe('FieldRow', () => {
  it('Neustart-Hinweis erscheint nur einmal, auch wenn der Hilfetext ihn schon nennt', () => {
    renderWithProviders(
      <FieldRows>
        <FieldRow label="Web-Port" restart help="wirkt nach Neustart des Druckdienstes" control={<input aria-label="x" />} />
      </FieldRows>,
    );
    expect(screen.getAllByText('wirkt nach Neustart des Druckdienstes')).toHaveLength(1);
  });

  it('Neustart-Hinweis ergänzt einen anderen Hilfetext als eigene Zeile', () => {
    renderWithProviders(<FieldRow label="Port" restart help="Port der Oberfläche" control={<input aria-label="x" />} />);
    expect(screen.getByText('Port der Oberfläche')).toBeInTheDocument();
    expect(screen.getByText('wirkt nach Neustart des Druckdienstes')).toBeInTheDocument();
  });

  it('Beschriftung ist mit dem Steuerelement verknüpft, gestapelte Zeile zeigt den Inhalt', () => {
    renderWithProviders(
      <>
        <FieldRow htmlFor="feld" label="Archivordner" control={<input id="feld" />} />
        <FieldRow label="SSH-Hosts" layout="stacked">
          <p>Liste</p>
        </FieldRow>
      </>,
    );
    expect(screen.getByLabelText('Archivordner')).toBeInTheDocument();
    expect(screen.getByText('Liste')).toBeInTheDocument();
  });
});
