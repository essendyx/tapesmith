/** Barrierefreiheit und Tastatur der Familienseite: axe in de/en, Tastatur, Fokusfalle. */
import { afterEach, describe, expect, it } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expectNoA11yViolations } from '../../test/a11y';
import { findDialog, mockApi, restoreAllMocks, setTestLanguage } from '../../test/utils';
import type { Language } from '../../i18n';
import { FAMILY_TOKEN_KEY } from './familyClient';
import FamilyApp from './FamilyApp';
import type { FamilyTemplate, FamilyTemplatesResponse } from './types';

const PNG_B64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';

function field(o: Partial<FamilyTemplate['fields'][number]> = {}): FamilyTemplate['fields'][number] {
  return { id: 'inhalt', label: 'Inhalt', type: 'text', default: null, required: true, choices: [], max_len: 60, multiline: false, ...o };
}

function template(o: Partial<FamilyTemplate> = {}): FamilyTemplate {
  return { name: 'gefriergut', title: 'Gefriergut', description: 'Für die Gefriertruhe', category: 'küche', fields: [field()], sample: { inhalt: 'Suppe' }, ...o };
}

function templatesResponse(templates: FamilyTemplate[] = [template()], maxCopies = 5): FamilyTemplatesResponse {
  return { templates, max_copies: maxCopies };
}

function withToken(token = 'p12_test'): void {
  localStorage.setItem(FAMILY_TOKEN_KEY, token);
}

async function renderFamily(): Promise<ReturnType<typeof render> & { user: ReturnType<typeof userEvent.setup> }> {
  const user = userEvent.setup();
  const result = render(<FamilyApp />);
  return Object.assign(result, { user });
}

afterEach(() => {
  restoreAllMocks();
  window.history.replaceState(null, '', '/familie');
  setTestLanguage('de');
});

describe.each(['de', 'en'] as Language[])('Familie a11y (%s)', (language) => {
  it('Grundzustand (Kachel-Raster) ohne axe-Befund', async () => {
    setTestLanguage(language);
    withToken();
    mockApi({ 'GET /api/v1/familie/vorlagen': () => templatesResponse(), 'GET /api/v1/familie/status': () => ({ online: true, text: 'Drucker bereit', waiting: 0 }) });
    const { container } = await renderFamily();
    await screen.findByText('Gefriergut');
    await expectNoA11yViolations(container);
  });

  it('leerer Zustand (Einladungshinweis ohne Token) ohne axe-Befund', async () => {
    setTestLanguage(language);
    const { container } = await renderFamily();
    await screen.findByLabelText('Token');
    await expectNoA11yViolations(container);
  });

  it('Fehler-/Rückfrage-Dialog ohne axe-Befund', async () => {
    setTestLanguage(language);
    withToken();
    const api = mockApi({
      'GET /api/v1/familie/vorlagen': () => templatesResponse(),
      'GET /api/v1/familie/status': () => ({ online: true, text: 'Drucker bereit', waiting: 0 }),
      'POST /api/v1/familie/vorschau': () => ({ ok: true, errors: [], warnings: [], design_png: PNG_B64, width: 200, height: 80, length_mm: 25 }),
      'POST /api/v1/familie/drucken': ({ body }) => {
        const confirmed = (body as { confirmed?: boolean }).confirmed === true;
        if (!confirmed) return { status: 'bestätigung_nötig', message: 'Bitte bestätigen?', reasons: ['Band passt nicht'], queue_id: null };
        return { status: 'ok', message: '', reasons: [], queue_id: 4 };
      },
    });
    const { container, user } = await renderFamily();
    await user.click(await screen.findByText('Gefriergut'));
    await user.type(await screen.findByLabelText('Inhalt *'), 'Suppe');
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/familie/vorschau')).toBe(true), { timeout: 3000 });
    await waitFor(() => expect(screen.getByRole('button', { name: language === 'de' ? 'Drucken' : 'Print' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: language === 'de' ? 'Drucken' : 'Print' }));
    await findDialog(language === 'de' ? 'Bitte bestätigen' : 'Please confirm');
    await expectNoA11yViolations(container);
  });
});

describe('Familie Englisch', () => {
  it('Überschrift und Hauptaktion sind englisch', async () => {
    setTestLanguage('en');
    withToken();
    mockApi({ 'GET /api/v1/familie/vorlagen': () => templatesResponse(), 'GET /api/v1/familie/status': () => ({ online: true, text: 'Drucker bereit', waiting: 0 }) });
    await renderFamily();
    expect(await screen.findByRole('heading', { level: 1, name: 'Print labels' })).toBeInTheDocument();
    await screen.findByText('Gefriergut');
    expect(document.documentElement.lang).toBe('en');
  });
});

describe('Familie Tastatur', () => {
  it('Vorlagen-Kachel per Tastatur erreichbar und per Enter auslösbar', async () => {
    withToken();
    mockApi({ 'GET /api/v1/familie/vorlagen': () => templatesResponse(), 'GET /api/v1/familie/status': () => ({ online: true, text: 'Drucker bereit', waiting: 0 }) });
    const { user } = await renderFamily();
    const tile = await screen.findByText('Gefriergut');
    const button = tile.closest('button');
    expect(button).not.toBeNull();
    (button as HTMLButtonElement).focus();
    expect(button).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(await screen.findByRole('heading', { level: 2, name: 'Gefriergut' })).toBeInTheDocument();
  });

  it('Rückfrage-Dialog schließt mit Escape und gibt den Fokus an den Auslöser zurück', async () => {
    withToken();
    const api = mockApi({
      'GET /api/v1/familie/vorlagen': () => templatesResponse(),
      'GET /api/v1/familie/status': () => ({ online: true, text: 'Drucker bereit', waiting: 0 }),
      'POST /api/v1/familie/vorschau': () => ({ ok: true, errors: [], warnings: [], design_png: PNG_B64, width: 200, height: 80, length_mm: 25 }),
      'POST /api/v1/familie/drucken': () => ({ status: 'bestätigung_nötig', message: 'Bitte bestätigen?', reasons: ['Band passt nicht'], queue_id: null }),
    });
    const { user } = await renderFamily();
    await user.click(await screen.findByText('Gefriergut'));
    await user.type(await screen.findByLabelText('Inhalt *'), 'Suppe');
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/familie/vorschau')).toBe(true), { timeout: 3000 });
    const printTrigger = await screen.findByRole('button', { name: 'Drucken' });
    await waitFor(() => expect(printTrigger).toBeEnabled());
    printTrigger.focus();
    await user.keyboard('{Enter}');
    const dialog = await findDialog('Bitte bestätigen');
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    await user.keyboard('{Escape}');
    await waitFor(() => expect(printTrigger).toHaveFocus());
  });
});
