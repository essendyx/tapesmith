import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { findDialog, mockApi, MockResponse, restoreAllMocks, setTestLanguage } from '../../test/utils';
import { FakeEventSource } from '../../test/fakeEventSource';
import { FAMILY_TOKEN_KEY } from './familyClient';
import FamilyApp from './FamilyApp';
import { isFamilyPath } from './index';
import type { FamilyTemplate, FamilyTemplatesResponse } from './types';

/** Gültiges 1x1-PNG (Base64 ohne data:-Präfix), wie in src/test/fixtures.ts. */
const PNG_B64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';

function field(o: Partial<FamilyTemplate['fields'][number]> = {}): FamilyTemplate['fields'][number] {
  return { id: 'inhalt', label: 'Inhalt', type: 'text', default: null, required: true, choices: [], max_len: 60, multiline: false, ...o };
}

function template(o: Partial<FamilyTemplate> = {}): FamilyTemplate {
  return { name: 'gefriergut', title: 'Gefriergut', description: 'Für die Gefriertruhe', category: 'küche', fields: [field()], sample: { inhalt: 'Suppe' }, ...o };
}

const FIVE_TEMPLATES: FamilyTemplate[] = [
  template(),
  template({ name: 'geoeffnet-am', title: 'Geöffnet am', fields: [field({ id: 'datum', label: 'Geöffnet am', type: 'date', required: false })] }),
  template({ name: 'vorratsdose', title: 'Vorratsdose' }),
  template({ name: 'schule', title: 'Schule' }),
  template({ name: 'eigentum', title: 'Eigentum', fields: [field({ id: 'name', label: 'Name' })] }),
];

function templatesResponse(templates: FamilyTemplate[] = FIVE_TEMPLATES, maxCopies = 5): FamilyTemplatesResponse {
  return { templates, max_copies: maxCopies };
}

function withToken(token = 'p12_test'): void {
  localStorage.setItem(FAMILY_TOKEN_KEY, token);
}

async function renderFamily(): Promise<ReturnType<typeof render> & { user: ReturnType<typeof userEvent.setup> }> {
  const user = vi.isFakeTimers() ? userEvent.setup({ advanceTimers: vi.advanceTimersByTime.bind(vi) }) : userEvent.setup();
  const result = render(<FamilyApp />);
  return Object.assign(result, { user });
}

afterEach(() => {
  restoreAllMocks();
  vi.useRealTimers();
  window.history.replaceState(null, '', '/familie');
});

describe('isFamilyPath', () => {
  it('erkennt /familie, /familie/ und /familie?x', () => {
    expect(isFamilyPath('/familie')).toBe(true);
    expect(isFamilyPath('/familie/')).toBe(true);
    expect(isFamilyPath('/familie?x')).toBe(true);
    expect(isFamilyPath('/familie#t=abc')).toBe(true);
  });

  it('erkennt /familienfoto nicht', () => {
    expect(isFamilyPath('/familienfoto')).toBe(false);
    expect(isFamilyPath('/')).toBe(false);
    expect(isFamilyPath('/einstellungen')).toBe(false);
  });
});

describe('/familie ohne Token', () => {
  it('zeigt den Einladungshinweis und lädt nach Eingabe die Vorlagen', async () => {
    const api = mockApi({ 'GET /api/v1/familie/vorlagen': () => templatesResponse(), 'GET /api/v1/familie/status': () => ({ online: true, text: 'Drucker bereit', waiting: 0 }) });
    const { user } = await renderFamily();
    expect(await screen.findByText('Bitte den Link aus der Einladung öffnen.')).toBeInTheDocument();
    const input = screen.getByLabelText('Token');
    await user.type(input, 'p12_neu');
    await user.click(screen.getByRole('button', { name: 'Speichern' }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/familie/vorlagen')).toBe(true));
    expect(await screen.findByText('Gefriergut')).toBeInTheDocument();
  });
});

describe('/familie mit Token', () => {
  it('zeigt Kacheln für alle Vorlagen und den Druckerstatus', async () => {
    withToken();
    mockApi({ 'GET /api/v1/familie/vorlagen': () => templatesResponse(), 'GET /api/v1/familie/status': () => ({ online: true, text: 'Drucker bereit', waiting: 2 }) });
    await renderFamily();
    for (const t of FIVE_TEMPLATES) {
      expect(await screen.findByText(t.title)).toBeInTheDocument();
    }
    expect(await screen.findByText(/Drucker bereit/)).toBeInTheDocument();
    expect(screen.getByText(/2 warten/)).toBeInTheDocument();
  });

  it('Kachel antippen öffnet das Formular, Eingabe löst nach Entprellung genau eine Vorschau aus', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    withToken();
    const api = mockApi({
      'GET /api/v1/familie/vorlagen': () => templatesResponse(),
      'GET /api/v1/familie/status': () => ({ online: true, text: 'Drucker bereit', waiting: 0 }),
      'POST /api/v1/familie/vorschau': () => ({ ok: true, errors: [], warnings: [], design_png: PNG_B64, width: 200, height: 80, length_mm: 25 }),
    });
    const { user } = await renderFamily();
    await user.click(await screen.findByText('Gefriergut'));
    const inputField = await screen.findByLabelText('Inhalt *');
    api.calls.length = 0;
    await user.type(inputField, 'Suppe');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    const previewCalls = api.calls.filter((c) => c.path === '/api/v1/familie/vorschau');
    expect(previewCalls).toHaveLength(1);
    expect(previewCalls[0]?.body).toMatchObject({ template: 'gefriergut', values: { inhalt: 'Suppe' } });
    expect(await screen.findByAltText('Vorschau des Etiketts')).toBeInTheDocument();
  });

  it('Drucken-Knopf ist deaktiviert, solange das Pflichtfeld leer ist', async () => {
    withToken();
    mockApi({
      'GET /api/v1/familie/vorlagen': () => templatesResponse(),
      'GET /api/v1/familie/status': () => ({ online: true, text: 'Drucker bereit', waiting: 0 }),
    });
    const { user } = await renderFamily();
    await user.click(await screen.findByText('Gefriergut'));
    expect(screen.getByRole('button', { name: 'Drucken' })).toBeDisabled();
  });

  it('Kopien: + bis max_copies, danach deaktiviert', async () => {
    withToken();
    mockApi({
      'GET /api/v1/familie/vorlagen': () => templatesResponse(FIVE_TEMPLATES, 3),
      'GET /api/v1/familie/status': () => ({ online: true, text: 'Drucker bereit', waiting: 0 }),
    });
    const { user } = await renderFamily();
    await user.click(await screen.findByText('Gefriergut'));
    const plus = screen.getByRole('button', { name: 'Mehr Kopien' });
    await user.click(plus);
    await user.click(plus);
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(plus).toBeDisabled();
  });

  it('Drucken mit Antwort ok zeigt „Gedruckt.“', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    withToken();
    mockApi({
      'GET /api/v1/familie/vorlagen': () => templatesResponse(),
      'GET /api/v1/familie/status': () => ({ online: true, text: 'Drucker bereit', waiting: 0 }),
      'POST /api/v1/familie/vorschau': () => ({ ok: true, errors: [], warnings: [], design_png: PNG_B64, width: 200, height: 80, length_mm: 25 }),
      'POST /api/v1/familie/drucken': () => ({ status: 'ok', message: '', reasons: [], queue_id: 3 }),
    });
    const { user } = await renderFamily();
    await user.click(await screen.findByText('Gefriergut'));
    await user.type(await screen.findByLabelText('Inhalt *'), 'Suppe');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Drucken' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    expect(await screen.findByText('Gedruckt.')).toBeInTheDocument();
  });

  it('nach „Gedruckt.“ erscheint bei erneuter Eingabe wieder der Drucken-Knopf, „Fertig“ bleibt zusätzlich sichtbar', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    withToken();
    mockApi({
      'GET /api/v1/familie/vorlagen': () => templatesResponse(),
      'GET /api/v1/familie/status': () => ({ online: true, text: 'Drucker bereit', waiting: 0 }),
      'POST /api/v1/familie/vorschau': () => ({ ok: true, errors: [], warnings: [], design_png: PNG_B64, width: 200, height: 80, length_mm: 25 }),
      'POST /api/v1/familie/drucken': () => ({ status: 'ok', message: '', reasons: [], queue_id: 3 }),
    });
    const { user } = await renderFamily();
    await user.click(await screen.findByText('Gefriergut'));
    const inputField = await screen.findByLabelText('Inhalt *');
    await user.type(inputField, 'Suppe');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Drucken' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    expect(await screen.findByText('Gedruckt.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Fertig' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Drucken' })).not.toBeInTheDocument();

    // Weiteres Etikett aus demselben Formular: Feld ändern setzt das alte Ergebnis zurück.
    await user.type(inputField, ' zwei');
    expect(screen.queryByText('Gedruckt.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Fertig' })).toBeInTheDocument();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Drucken' })).toBeEnabled());

    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    expect(await screen.findByText('Gedruckt.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Fertig' })).toBeInTheDocument();
  });

  it('bestätigung_nötig zeigt einen Dialog; „Trotzdem drucken“ sendet confirmed: true', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    withToken();
    let printCalls = 0;
    const CONFIRM_MSG = 'Das eingelegte Band passt nicht zu dieser Vorlage. Trotzdem drucken?';
    const api = mockApi({
      'GET /api/v1/familie/vorlagen': () => templatesResponse(),
      'GET /api/v1/familie/status': () => ({ online: true, text: 'Drucker bereit', waiting: 0 }),
      'POST /api/v1/familie/vorschau': () => ({ ok: true, errors: [], warnings: [], design_png: PNG_B64, width: 200, height: 80, length_mm: 25 }),
      'POST /api/v1/familie/drucken': ({ body }) => {
        printCalls += 1;
        const confirmed = (body as { confirmed?: boolean }).confirmed === true;
        if (!confirmed) return { status: 'bestätigung_nötig', message: CONFIRM_MSG, reasons: ['Band passt nicht'], queue_id: null };
        return { status: 'ok', message: '', reasons: [], queue_id: 4 };
      },
    });
    const { user } = await renderFamily();
    await user.click(await screen.findByText('Gefriergut'));
    await user.type(await screen.findByLabelText('Inhalt *'), 'Suppe');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Drucken' })).toBeEnabled());
    vi.useRealTimers();
    const realUser = userEvent.setup();
    await realUser.click(screen.getByRole('button', { name: 'Drucken' }));
    const dialog = await findDialog('Bitte bestätigen');
    expect(within(dialog).getByText(CONFIRM_MSG)).toBeInTheDocument();
    await realUser.click(within(dialog).getByRole('button', { name: 'Trotzdem drucken' }));
    expect(await screen.findByText('Gedruckt.')).toBeInTheDocument();
    expect(printCalls).toBe(2);
    const secondCall = api.calls.filter((c) => c.path === '/api/v1/familie/drucken')[1];
    expect(secondCall?.body).toMatchObject({ confirmed: true });
  });

  it('abgelehnt zeigt eine rote Meldung, keinen Dialog und keinen zweiten Aufruf', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    withToken();
    const REJECT_MSG = 'Das Etikett ist zu lang für den Druck vom Handy.';
    const api = mockApi({
      'GET /api/v1/familie/vorlagen': () => templatesResponse(),
      'GET /api/v1/familie/status': () => ({ online: true, text: 'Drucker bereit', waiting: 0 }),
      'POST /api/v1/familie/vorschau': () => ({ ok: true, errors: [], warnings: [], design_png: PNG_B64, width: 200, height: 80, length_mm: 25 }),
      'POST /api/v1/familie/drucken': () => ({ status: 'abgelehnt', message: REJECT_MSG, reasons: ['zu lang'], queue_id: null }),
    });
    const { user } = await renderFamily();
    await user.click(await screen.findByText('Gefriergut'));
    await user.type(await screen.findByLabelText('Inhalt *'), 'Suppe');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Drucken' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    expect(await screen.findByText(REJECT_MSG)).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(api.calls.filter((c) => c.path === '/api/v1/familie/drucken')).toHaveLength(1);
  });

  it('Englisch: ohne Verbindung zum Drucker-PC eine englische Meldung beim Drucken', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    withToken();
    setTestLanguage('en');
    mockApi({
      'GET /api/v1/familie/vorlagen': () => templatesResponse(),
      'GET /api/v1/familie/status': () => ({ online: true, text: 'Drucker bereit', waiting: 0 }),
      'POST /api/v1/familie/vorschau': () => ({ ok: true, errors: [], warnings: [], design_png: PNG_B64, width: 200, height: 80, length_mm: 25 }),
    });
    const mocked = globalThis.fetch;
    globalThis.fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) =>
      String(input).includes('/familie/drucken') ? Promise.reject(new TypeError('Failed to fetch')) : mocked(input, init),
    ) as unknown as typeof fetch;
    const { user } = await renderFamily();
    await user.click(await screen.findByText('Gefriergut'));
    await user.type(await screen.findByLabelText('Inhalt *'), 'Suppe');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Print' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Print' }));
    expect(await screen.findByText('No connection to the printer PC')).toBeInTheDocument();
    expect(screen.queryByText(/Keine Verbindung/)).toBeNull();
  });

  it('wartet zeigt die Meldung vom Server', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    withToken();
    const WAIT_MSG = 'Auftrag eingereiht, Drucker ist gerade beschäftigt.';
    mockApi({
      'GET /api/v1/familie/vorlagen': () => templatesResponse(),
      'GET /api/v1/familie/status': () => ({ online: true, text: 'Drucker bereit', waiting: 0 }),
      'POST /api/v1/familie/vorschau': () => ({ ok: true, errors: [], warnings: [], design_png: PNG_B64, width: 200, height: 80, length_mm: 25 }),
      'POST /api/v1/familie/drucken': () => ({ status: 'wartet', message: WAIT_MSG, reasons: [], queue_id: 5 }),
    });
    const { user } = await renderFamily();
    await user.click(await screen.findByText('Gefriergut'));
    await user.type(await screen.findByLabelText('Inhalt *'), 'Suppe');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Drucken' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    expect(await screen.findByText(WAIT_MSG)).toBeInTheDocument();
  });

  it('401 beim Laden löscht das Token und zeigt „Zugang ungültig“', async () => {
    withToken();
    mockApi(
      {
        'GET /api/v1/familie/vorlagen': () => new MockResponse(401, { error: { kind: 'Auth', message: 'Nicht angemeldet', hint: '', exit_code: 1, details: null } }),
        'GET /api/v1/familie/status': () => new MockResponse(401, { error: { kind: 'Auth', message: 'Nicht angemeldet', hint: '', exit_code: 1, details: null } }),
      },
      { quiet: true },
    );
    await renderFamily();
    expect(await screen.findByText('Zugang ungültig oder widerrufen. Bitte neuen Link anfordern.')).toBeInTheDocument();
    expect(localStorage.getItem(FAMILY_TOKEN_KEY)).toBeNull();
  });

  it('ruft nie eine Route außerhalb /api/v1/familie/ auf und öffnet nie EventSource', async () => {
    withToken();
    const api = mockApi(
      { 'GET /api/v1/familie/vorlagen': () => templatesResponse(), 'GET /api/v1/familie/status': () => ({ online: true, text: 'Drucker bereit', waiting: 0 }) },
      { quiet: true },
    );
    await renderFamily();
    await screen.findByText('Gefriergut');
    expect(api.unmatched).toHaveLength(0);
    expect(FakeEventSource.instances).toHaveLength(0);
  });
});
