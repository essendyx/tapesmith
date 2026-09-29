import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { LocationProbe, mockApi, renderWithProviders, restoreAllMocks } from '../../test/utils';
import type { GalleryJson, TemplateSummary } from '../../api/types';
import GaleriePage from './index';

afterEach(() => {
  restoreAllMocks();
  vi.useRealTimers();
});

function makeTemplate(o: Partial<TemplateSummary> = {}): TemplateSummary {
  return {
    name: 'datentraeger',
    description: 'SSD- und HDD-Etiketten',
    category: 'Datenträger',
    tags: ['ssd', 'hdd'],
    kind: 'layout',
    builtin: true,
    favorite: false,
    target: null,
    tapes: [],
    default_copies: 1,
    input_fields: [],
    sample: { sn: '274913' },
    ...o,
  };
}

function makeGallery(o: Partial<GalleryJson> = {}): GalleryJson {
  return {
    categories: [{ name: 'Datenträger', templates: [makeTemplate()] }],
    favorites: [],
    recent: [],
    templates_dir: 'C:\\Vorlagen',
    ...o,
  };
}

describe('Galerie', () => {
  it('rendert Abschnitte und Kacheln mit Bandvorschau (t= und tape=)', async () => {
    mockApi({
      'GET /api/v1/gallery': () =>
        makeGallery({
          favorites: ['datentraeger'],
          recent: ['datentraeger'],
          categories: [{ name: 'Datenträger', templates: [makeTemplate({ favorite: true })] }],
        }),
    });
    renderWithProviders(<GaleriePage />);

    expect(await screen.findByText('Favoriten')).toBeInTheDocument();
    expect(screen.getByText('Zuletzt verwendet')).toBeInTheDocument();
    expect(screen.getAllByText('Datenträger').length).toBeGreaterThan(0);

    const imgs = screen.getAllByRole('img', { name: /datentraeger/i });
    expect(imgs.length).toBeGreaterThan(0);
    const src = imgs[0]?.getAttribute('src') ?? '';
    expect(src).toContain('/api/v1/gallery/thumb/datentraeger.png');
    expect(src).toContain('t=test-token');
    expect(src).toContain('tape=w12');
  });

  it('Suche entprellt und sucht auch Feldnamen', async () => {
    const api = mockApi({ 'GET /api/v1/gallery': () => makeGallery() });
    const { user } = renderWithProviders(<GaleriePage />);
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/gallery')).toBe(true));
    api.calls.length = 0;

    await user.type(screen.getByLabelText('Vorlagen und Feldnamen durchsuchen'), 'sn');
    expect(api.calls.some((c) => c.path === '/api/v1/gallery?query=sn')).toBe(false);
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/gallery?query=sn')).toBe(true), { timeout: 2000 });
  });

  it('Stern klickt: POST favorites mit favorite:true, sofort optisch gefüllt', async () => {
    const api = mockApi({
      'GET /api/v1/gallery': () => makeGallery(),
      'POST /api/v1/gallery/favorites/:name': () => ({ favorites: ['datentraeger'] }),
    });
    const { user } = renderWithProviders(<GaleriePage />);
    await screen.findByText('datentraeger');
    const star = screen.getByLabelText('Als Favorit merken');
    expect(star).toHaveAttribute('aria-pressed', 'false');
    await user.click(star);
    expect(screen.getByLabelText('Favorit entfernen')).toHaveAttribute('aria-pressed', 'true');
    await waitFor(() =>
      expect(api.calls.find((c) => c.path === '/api/v1/gallery/favorites/datentraeger')?.body).toEqual({ favorite: true }),
    );
  });

  it('„Verwenden“ navigiert nach /vorlagen?vorlage=<name>', async () => {
    mockApi({ 'GET /api/v1/gallery': () => makeGallery() });
    const { user } = renderWithProviders(
      <>
        <GaleriePage />
        <LocationProbe />
      </>,
    );
    await screen.findByText('datentraeger');
    await user.click(screen.getByLabelText('Weitere Aktionen für datentraeger'));
    await user.click(await screen.findByRole('menuitem', { name: 'Verwenden' }));
    expect(screen.getByTestId('location')).toHaveTextContent('/vorlagen?vorlage=datentraeger');
  });

  it('Lint-Dialog zeigt Einträge aus /templates/lint', async () => {
    mockApi({
      'GET /api/v1/gallery': () => makeGallery(),
      'GET /api/v1/templates/lint': () => ({
        issues: [{ template: 'datentraeger', level: 'error', message: 'Feld sn ohne Beispielwert' }],
      }),
    });
    const { user } = renderWithProviders(<GaleriePage />);
    await screen.findByText('datentraeger');
    await user.click(screen.getByRole('button', { name: 'Alle prüfen' }));
    const list = await screen.findByTestId('lint-issues');
    expect(within(list).getByText(/Feld sn ohne Beispielwert/)).toBeInTheDocument();
  });

  it('Paket importieren sendet package_b64', async () => {
    const api = mockApi({
      'GET /api/v1/gallery': () => makeGallery(),
      'POST /api/v1/templates/import': () => ({ imported: ['datentraeger'] }),
    });
    const { user, container } = renderWithProviders(<GaleriePage />);
    await screen.findByText('datentraeger');
    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['zip-inhalt'], 'paket.zip', { type: 'application/zip' });
    await user.upload(fileInput, file);
    await user.click(await screen.findByRole('button', { name: 'Überschreiben' }));
    await waitFor(() => {
      const call = api.calls.find((c) => c.path === '/api/v1/templates/import');
      expect(call).toBeDefined();
      expect((call?.body as { package_b64: string }).package_b64.length).toBeGreaterThan(0);
    });
  });
});
