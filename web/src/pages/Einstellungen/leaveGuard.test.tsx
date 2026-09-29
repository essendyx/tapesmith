/** Rückfrage beim Verlassen der Seite mit ungespeicherten Änderungen (Router-Navigation und Fenster schließen). */
import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { useNavigate } from 'react-router-dom';
import { findDialogByRole, LocationProbe, mockApi, renderWithProviders } from '../../test/utils';
import { baseSettingsRoutes } from './testFixtures';
import EinstellungenPage from './index';

function NavButton(): JSX.Element {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate('/schnelldruck')}>
      Weg
    </button>
  );
}

function renderPage() {
  mockApi(baseSettingsRoutes());
  return renderWithProviders(
    <>
      <EinstellungenPage />
      <NavButton />
      <LocationProbe />
    </>,
    { route: '/einstellungen' },
  );
}

function fireBeforeUnload(): Event {
  const ev = new Event('beforeunload', { cancelable: true });
  window.dispatchEvent(ev);
  return ev;
}

describe('/einstellungen: ungespeicherte Änderungen beim Verlassen', () => {
  it('ohne Änderungen navigiert die Seite ohne Rückfrage', async () => {
    const { user } = renderPage();
    await screen.findByRole('switch', { name: 'Nur mit Strg+Enter drucken' });
    expect(fireBeforeUnload().defaultPrevented).toBe(false);

    await user.click(screen.getByRole('button', { name: 'Weg' }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/schnelldruck'));
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
  });

  it('mit Änderungen fragt nach: Abbrechen bleibt, Verlassen navigiert', async () => {
    const { user } = renderPage();
    await user.click(await screen.findByRole('switch', { name: 'Nur mit Strg+Enter drucken' }));

    await user.click(screen.getByRole('button', { name: 'Weg' }));
    let dialog = await findDialogByRole('alertdialog');
    expect(within(dialog).getByText('Ungespeicherte Änderungen verwerfen?')).toBeInTheDocument();
    await user.click(within(dialog).getByRole('button', { name: 'Abbrechen', hidden: true }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(screen.getByTestId('location')).toHaveTextContent('/einstellungen');

    // Nach dem Schließen gibt der Dialog die Seite erst mit der Ausblend-Animation wieder frei.
    await user.click(await screen.findByRole('button', { name: 'Weg' }));
    dialog = await findDialogByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Verlassen', hidden: true }));
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/schnelldruck'));
  });

  it('mit Änderungen setzt das Fenster-Schließen (beforeunload) die Browser-Rückfrage', async () => {
    const { user } = renderPage();
    await user.click(await screen.findByRole('switch', { name: 'Nur mit Strg+Enter drucken' }));
    await waitFor(() => expect(fireBeforeUnload().defaultPrevented).toBe(true));
  });
});
