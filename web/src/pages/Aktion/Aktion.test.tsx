import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { LocationProbe, MockResponse, mockApi, renderWithProviders } from '../../test/utils';
import AktionPage from './index';

describe('/aktion', () => {
  it('ruft resolve mit der URI und navigiert zur gelieferten Route', async () => {
    const api = mockApi({
      'POST /api/v1/integration/resolve': () => ({ kind: 'print', route: '/vorlagen?vorlage=datentraeger', note: 'Vorlage geöffnet' }),
    });
    renderWithProviders(
      <>
        <AktionPage />
        <LocationProbe />
      </>,
      { route: '/aktion?uri=tapesmith%3A%2F%2Fprint%3Ftemplate%3Ddatentraeger' },
    );
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/vorlagen?vorlage=datentraeger'));
    const call = api.calls.find((c) => c.path === '/api/v1/integration/resolve');
    expect(call?.body).toEqual({ uri: 'tapesmith://print?template=datentraeger' });
    expect(await screen.findByText('Vorlage geöffnet')).toBeInTheDocument();
  });

  it('open und path werden übergeben', async () => {
    const api = mockApi({ 'POST /api/v1/integration/resolve': () => ({ kind: 'open', route: '/editor?import=abc', note: '' }) });
    renderWithProviders(
      <>
        <AktionPage />
        <LocationProbe />
      </>,
      { route: '/aktion?open=bild&path=C%3A%5Cx.png' },
    );
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/editor?import=abc'));
    expect(api.calls.find((c) => c.path === '/api/v1/integration/resolve')?.body).toEqual({ open: 'bild', path: 'C:\\x.png' });
  });

  it('Fehler zeigt Karte mit Hinweis und „Zum Schnelldruck“', async () => {
    mockApi({
      'POST /api/v1/integration/resolve': () =>
        new MockResponse(422, { error: { kind: 'ValueError', message: 'Unbekannte Aktion', hint: 'URI prüfen', exit_code: 1, details: null } }),
    });
    const { user } = renderWithProviders(
      <>
        <AktionPage />
        <LocationProbe />
      </>,
      { route: '/aktion?uri=tapesmith%3A%2F%2Fquatsch' },
    );
    expect(await screen.findByText('Unbekannte Aktion')).toBeInTheDocument();
    expect(screen.getByText('URI prüfen')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Zum Schnelldruck' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/schnelldruck');
  });
});
