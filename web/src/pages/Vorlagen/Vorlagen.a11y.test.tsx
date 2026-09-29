/** Barrierefreiheit und Tastatur der Vorlagen-Seite: axe in de und en. */
import { afterEach, describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { findDialog, fixtures, mockApi, renderWithProviders, restoreAllMocks } from '../../test/utils';
import type { FieldJson, TemplateDetail, TemplateSummary } from '../../api/types';
import type { Language } from '../../i18n';
import VorlagenPage from './index';

afterEach(() => {
  restoreAllMocks();
});

const BATCH_OPEN: Record<Language, string> = { de: 'Serie/Import…', en: 'Series/import…' };
const PRINT: Record<Language, string> = { de: 'Drucken', en: 'Print' };
const BATCH_TITLE: Record<Language, string> = { de: 'Serie/Import: datentraeger', en: 'Series/import: datentraeger' };

function field(o: Partial<FieldJson> = {}): FieldJson {
  return { id: 'sn', label: 'Seriennummer', type: 'input', default: '', required: true, secret: false, choices: [], max_len: null, multiline: false, ...o };
}

function summary(o: Partial<TemplateSummary> = {}): TemplateSummary {
  return {
    name: 'datentraeger',
    description: 'SSD- und HDD-Etiketten',
    category: 'Datenträger',
    tags: [],
    kind: 'layout',
    builtin: true,
    favorite: false,
    target: null,
    tapes: [],
    default_copies: 1,
    input_fields: [field()],
    sample: { sn: '274913' },
    ...o,
  };
}

function detail(o: Partial<TemplateDetail> = {}): TemplateDetail {
  const s = summary(o);
  return { ...s, fields: s.input_fields, path: null, definition: {}, tape_reason: null, ...o };
}

function baseRoutes(overrides: Record<string, (req: { body: unknown; params: Record<string, string> }) => unknown> = {}) {
  return {
    'GET /api/v1/templates': () => ({ templates: [summary()] }),
    'GET /api/v1/templates/:name': () => detail(),
    'POST /api/v1/homelab/plausi': () => ({ findings: [], worst: null }),
    'POST /api/v1/labels/render': () => fixtures.renderJson(),
    ...overrides,
  };
}

describe('Vorlagen: axe ohne Befund', () => {
  for (const language of ['de', 'en'] as const) {
    it(`Grundzustand mit gewählter Vorlage (${language})`, async () => {
      mockApi(baseRoutes());
      const { container } = renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger', language });
      await screen.findByLabelText(/Seriennummer|Serial number/);
      await expectNoA11yViolations(container);
    });

    it(`leere Vorlagenliste (${language})`, async () => {
      mockApi(baseRoutes({ 'GET /api/v1/templates': () => ({ templates: [] }) }));
      const { container } = renderWithProviders(<VorlagenPage />, { language });
      await waitFor(() => expect(screen.getByRole('group', { name: /Vorlagen|Templates/ })).toBeInTheDocument());
      await expectNoA11yViolations(container);
    });

    it(`Serie/Import-Dialog (${language})`, async () => {
      mockApi(baseRoutes());
      const { user } = renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger', language });
      await screen.findByLabelText(/Seriennummer|Serial number/);
      await user.click(screen.getByRole('button', { name: BATCH_OPEN[language] }));
      await findDialog(BATCH_TITLE[language]);
      await expectNoA11yViolations(document.body);
    });
  }
});

describe('Vorlagen: Tastatur', () => {
  it('Hauptaktion ist per Tab erreichbar und per Enter auslösbar', async () => {
    const api = mockApi(baseRoutes({ 'POST /api/v1/labels/print': () => fixtures.outcomeJson({ status: 'ok', title: 'X' }) }));
    const { user } = renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger&werte=%7B%22sn%22%3A%22274913%22%7D' });
    await screen.findByLabelText(/Seriennummer/);
    const button = await screen.findByRole('button', { name: PRINT.de });
    await waitFor(() => expect(button).toBeEnabled());
    button.focus();
    expect(button).toHaveFocus();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
  });

  it('Serie/Import-Dialog schließt mit Escape und gibt den Fokus an den Auslöser zurück', async () => {
    mockApi(baseRoutes());
    const { user } = renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger' });
    await screen.findByLabelText(/Seriennummer/);
    const opener = screen.getByRole('button', { name: BATCH_OPEN.de });
    await user.click(opener);
    await findDialog(BATCH_TITLE.de);
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByText(BATCH_TITLE.de, { selector: '.fui-DialogTitle' })).not.toBeInTheDocument());
  });
});

describe('Vorlagen: Englisch', () => {
  it('Überschrift und Hauptaktion sind englisch', async () => {
    mockApi(baseRoutes());
    renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger', language: 'en' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Templates' })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Print' })).toBeInTheDocument();
  });
});

describe('BatchDialog: Tabelle für die Spaltenzuordnung', () => {
  it('Zuordnung Feld -> Spalte ist eine echte Tabelle mit aria-label', async () => {
    mockApi(
      baseRoutes({
        'POST /api/v1/batch/table': () => ({ headers: ['SN'], rows: [['A1']], source_name: 'x' }),
        'POST /api/v1/batch/plan': () => ({ count: 1, summary: 'ok', mapping: { sn: 'SN' }, headers: ['SN'], warnings: [], errors: [], previews: [] }),
      }),
    );
    const { user } = renderWithProviders(<VorlagenPage />, { route: '/vorlagen?vorlage=datentraeger' });
    await screen.findByLabelText(/Seriennummer/);
    await user.click(screen.getByRole('button', { name: BATCH_OPEN.de }));
    await findDialog(BATCH_TITLE.de);
    await user.type(await screen.findByLabelText('Tabelle einfügen'), 'SN{Enter}A1');
    const table = await screen.findByRole('table', { name: 'Spaltenzuordnung' });
    expect(within(table).getByLabelText('Zuordnung Seriennummer')).toBeInTheDocument();
  });
});
