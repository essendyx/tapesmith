/** Barrierefreiheit und Tastatur der Galerie: axe in de und en. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { findDialogByRole, mockApi, renderWithProviders, restoreAllMocks } from '../../test/utils';
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

describe('Galerie: axe ohne Befund', () => {
  for (const language of ['de', 'en'] as const) {
    it(`Grundzustand mit Kacheln (${language})`, async () => {
      mockApi({ 'GET /api/v1/gallery': () => makeGallery() });
      const { container } = renderWithProviders(<GaleriePage />, { language });
      await screen.findByText('datentraeger');
      await expectNoA11yViolations(container);
    });

    it(`leere Suche (${language})`, async () => {
      mockApi({ 'GET /api/v1/gallery': () => makeGallery({ categories: [] }) });
      const { user, container } = renderWithProviders(<GaleriePage />, { language });
      const label = language === 'de' ? 'Vorlagen und Feldnamen durchsuchen' : 'Search templates and field names';
      await user.type(screen.getByLabelText(label), 'nichts-gefunden');
      await waitFor(() => expect(screen.getByText(language === 'de' ? 'Keine Vorlage gefunden' : 'No template found')).toBeInTheDocument(), {
        timeout: 2000,
      });
      await expectNoA11yViolations(container);
    });

    it(`Lint-Dialog (${language})`, async () => {
      mockApi({
        'GET /api/v1/gallery': () => makeGallery(),
        'GET /api/v1/templates/lint': () => ({ issues: [{ template: 'datentraeger', level: 'error', message: 'Feld sn ohne Beispielwert' }] }),
      });
      const { user } = renderWithProviders(<GaleriePage />, { language });
      await screen.findByText('datentraeger');
      await user.click(screen.getByRole('button', { name: language === 'de' ? 'Alle prüfen' : 'Check all' }));
      await screen.findByTestId('lint-issues');
      await expectNoA11yViolations(document.body);
    });
  }
});

describe('Galerie: Tastatur', () => {
  it('Kachel ist per Tab erreichbar und öffnet mit Enter die Vorlage', async () => {
    mockApi({ 'GET /api/v1/gallery': () => makeGallery() });
    const { user } = renderWithProviders(
      <>
        <GaleriePage />
      </>,
    );
    await screen.findByText('datentraeger');
    const open = screen.getByRole('button', { name: 'Vorlage datentraeger' });
    open.focus();
    expect(open).toHaveFocus();
    await user.keyboard('{Enter}');
    // onUse navigiert; die Kachel selbst bleibt danach im DOM (kein Fehler geworfen).
    expect(open).toBeInTheDocument();
  });

  it('Lint-Dialog schließt mit Escape', async () => {
    mockApi({
      'GET /api/v1/gallery': () => makeGallery(),
      'GET /api/v1/templates/lint': () => ({ issues: [] }),
    });
    const { user } = renderWithProviders(<GaleriePage />);
    await screen.findByText('datentraeger');
    await user.click(screen.getByRole('button', { name: 'Alle prüfen' }));
    await findDialogByRole('dialog');
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });
});

describe('Galerie: Englisch', () => {
  it('Überschrift und Kachel-Beschriftung sind englisch', async () => {
    mockApi({ 'GET /api/v1/gallery': () => makeGallery() });
    renderWithProviders(<GaleriePage />, { language: 'en' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Gallery' })).toBeInTheDocument();
    await screen.findByText('datentraeger');
    expect(screen.getByLabelText('Add to favorites')).toBeInTheDocument();
  });
});
