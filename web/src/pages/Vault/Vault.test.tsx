import { describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import { LocationProbe, MockResponse, SLOW_UI_MS, fixtures, mockApi, renderWithProviders, type MockHandler } from '../../test/utils';
import type { HistoryEntryJson, TemplateSummary } from '../../api/types';
import VaultPage from './index';
import type { SnippetJson, VaultNoteJson } from './types';

const NOTE: VaultNoteJson = {
  path: 'Hosts/pmx30',
  title: 'pmx30',
  values: { ip: '192.0.2.99', version: 'pve-manager 9.2.x', rolle: 'Testserver', name: 'pmx30', host: 'pmx30', titel: 'pmx30', pfad: 'Hosts/pmx30' },
  tables: [
    { heading: 'Platten', headers: ['Label', 'Seriennummer', 'Rolle'], rows: [['SSD-1', '111111274913', 'rpool Spiegel']] },
  ],
};

function template(name: string, fields: [string, string][]): TemplateSummary {
  return {
    name,
    description: '',
    category: 'Homelab',
    tags: [],
    kind: 'layout',
    builtin: true,
    favorite: false,
    target: null,
    tapes: [],
    default_copies: 1,
    input_fields: fields.map(([id, label]) => ({
      id,
      label,
      type: 'input',
      default: '',
      required: false,
      secret: false,
      choices: [],
      max_len: null,
      multiline: false,
    })),
    sample: {},
  };
}

const TEMPLATES = [
  template('host-ip', [
    ['host', 'Host'],
    ['ip', 'IP-Adresse'],
    ['rolle', 'Rolle'],
  ]),
  template('datentraeger', [
    ['host', 'Host'],
    ['slot', 'Slot'],
    ['sn', 'Seriennummer'],
  ]),
];

function historyEntry(id: number, title: string): HistoryEntryJson {
  return {
    id,
    created: '2026-09-26T10:15:00',
    source: 'api',
    kind: 'template',
    title,
    template: 'datentraeger',
    values: {},
    spec: null,
    length_mm: 20,
    tape_mm: 12,
    copies: 1,
    chained: false,
    status: 'ok',
    error: '',
    sensitive: false,
    has_head: true,
    reprintable: true,
    missing_secrets: [],
  };
}

function snippetJson(o: Partial<SnippetJson> = {}): SnippetJson {
  return {
    history_id: 7,
    file_name: 'label-20260926-101500-7.png',
    png: fixtures.pngB64,
    markdown: '- 2026-09-26 Label gedruckt: pmx30 · SSD-1 · SN 274913 ![[label-20260926-101500-7.png]]',
    changelog_md: '- Label gedruckt: pmx30 · SSD-1 · SN 274913 (Verlauf #7)',
    summary: 'pmx30 · SSD-1 · SN 274913',
    saved_path: null,
    appended: false,
    warnings: [],
    ...o,
  };
}

function routes(extra: Record<string, MockHandler> = {}): Record<string, MockHandler> {
  return {
    'GET /api/v1/homelab/vault/notes': () => ({ folders: ['Hosts', 'Dienste'], notes: ['Hosts/pmx30', 'Dienste/testdienst'] }),
    'GET /api/v1/homelab/vault/note': () => NOTE,
    'GET /api/v1/homelab/settings': () => ({ settings: { obsidian: { append_after_print: true, folders: ['Hosts', 'Dienste'], vault_dir: null } } }),
    'GET /api/v1/templates': () => ({ templates: TEMPLATES }),
    'POST /api/v1/labels/render': () => fixtures.renderJson(),
    'POST /api/v1/labels/print': () => fixtures.outcomeJson({ status: 'ok', history_id: 7 }),
    'POST /api/v1/homelab/vault/printed': () => ({ appended: true, line: '- 2026-09-28 Label gedruckt: pmx30 · 192.0.2.99 · Testserver', saved_path: null, reason: '' }),
    'POST /api/v1/homelab/vault/table': () => ({ pending_id: 'p-1', count: 1, headers: ['label', 'seriennummer', 'rolle'] }),
    'GET /api/v1/history': () => ({ entries: [historyEntry(7, 'Datenträger pmx30')] }),
    'POST /api/v1/homelab/vault/snippet': ({ body }) => {
      const b = body as { save_attachment: boolean };
      return b.save_attachment ? snippetJson({ saved_path: 'D:\\Vault\\Anhänge\\Labels\\label-20260926-101500-7.png' }) : snippetJson();
    },
    ...extra,
  };
}

async function openNote(user: ReturnType<typeof renderWithProviders>['user']) {
  await user.click(await screen.findByRole('button', { name: 'Hosts/pmx30' }));
  await screen.findByText('192.0.2.99');
}

describe('VaultPage Notizen', () => {
  it('lädt Ordner und Notiz und zeigt Werte und Tabellen', async () => {
    const api = mockApi(routes());
    const { user } = renderWithProviders(<VaultPage />, { route: '/homelab/vault' });
    expect(await screen.findByRole('heading', { name: 'Obsidian-Vault' })).toBeInTheDocument();
    expect(await screen.findByRole('option', { name: 'Hosts' })).toBeInTheDocument();
    await openNote(user);
    expect(screen.getByText('pve-manager 9.2.x')).toBeInTheDocument();
    expect(screen.getByText('Tabelle 1: Platten')).toBeInTheDocument();
    expect(api.calls.some((c) => c.path === '/api/v1/homelab/vault/note?path=Hosts%2Fpmx30')).toBe(true);
    await user.type(screen.getByLabelText('Suche im Namen'), 'dienst');
    expect(screen.queryByRole('button', { name: 'Hosts/pmx30' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Dienste/testdienst' })).toBeInTheDocument();
  });

  it('Direktdruck sendet nur Eingabefelder und danach /printed', async () => {
    const api = mockApi(routes());
    const { user } = renderWithProviders(<VaultPage />, { route: '/homelab/vault' });
    await openNote(user);
    await user.selectOptions(await screen.findByLabelText('Vorlage'), 'host-ip');
    await waitFor(() => expect(screen.getByRole('switch', { name: 'Vermerk in die Notiz schreiben' })).toBeChecked());
    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    await screen.findByText('Vermerk angehängt', {}, { timeout: SLOW_UI_MS });
    const print = api.calls.find((c) => c.path === '/api/v1/labels/print');
    const source = (print?.body as { source: { kind: string; template: string; values: Record<string, string> } }).source;
    expect(source).toEqual({ kind: 'template', template: 'host-ip', values: { host: 'pmx30', ip: '192.0.2.99', rolle: 'Testserver' } });
    const printed = api.calls.find((c) => c.path === '/api/v1/homelab/vault/printed');
    expect(printed?.body).toEqual({ path: 'Hosts/pmx30', history_id: 7, force: true });
  });

  it('Druck mit Fehler-Outcome sendet kein /printed', async () => {
    const api = mockApi(
      routes({
        'POST /api/v1/labels/print': () => fixtures.outcomeJson({ status: 'abgelehnt', history_id: null, reasons: ['Band fehlt'] }),
      }),
    );
    const { user } = renderWithProviders(<VaultPage />, { route: '/homelab/vault' });
    await openNote(user);
    await user.selectOptions(await screen.findByLabelText('Vorlage'), 'host-ip');
    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
    await new Promise((r) => setTimeout(r, 50));
    expect(api.calls.some((c) => c.path === '/api/v1/homelab/vault/printed')).toBe(false);
  });

  it('In Vorlage übernehmen navigiert mit zugeordneten Werten', async () => {
    mockApi(routes());
    const { user } = renderWithProviders(
      <>
        <VaultPage />
        <LocationProbe />
      </>,
      { route: '/homelab/vault' },
    );
    await openNote(user);
    await user.selectOptions(await screen.findByLabelText('Vorlage'), 'host-ip');
    await user.selectOptions(screen.getByLabelText('Notizschlüssel für Rolle'), 'version');
    await user.click(screen.getByRole('button', { name: 'In Vorlage übernehmen' }));
    const location = screen.getByTestId('location').textContent ?? '';
    const params = new URLSearchParams(location.split('?')[1]);
    expect(location.startsWith('/vorlagen?')).toBe(true);
    expect(params.get('vorlage')).toBe('host-ip');
    expect(JSON.parse(params.get('werte') ?? '{}')).toEqual({ host: 'pmx30', ip: '192.0.2.99', rolle: 'pve-manager 9.2.x' });
  });

  it('Tabelle als Serie sendet /table und navigiert zum Import', async () => {
    const api = mockApi(routes());
    const { user } = renderWithProviders(
      <>
        <VaultPage />
        <LocationProbe />
      </>,
      { route: '/homelab/vault' },
    );
    await openNote(user);
    await user.click(screen.getByRole('button', { name: 'Als Serie' }));
    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/vorlagen?import=p-1'));
    const call = api.calls.find((c) => c.path === '/api/v1/homelab/vault/table');
    expect(call?.body).toEqual({ path: 'Hosts/pmx30', table: 0, columns: null, template: null });
  });

  it('zeigt Fehler 503 mit Hinweis', async () => {
    mockApi(
      routes({
        'GET /api/v1/homelab/vault/notes': () =>
          new MockResponse(503, {
            error: { kind: 'NotReachable', message: 'Obsidian: nicht erreichbar (http://192.0.2.12:8092/mcp)', hint: 'Adresse und Netz prüfen', exit_code: 5, details: null },
          }),
      }),
    );
    renderWithProviders(<VaultPage />, { route: '/homelab/vault' });
    expect(await screen.findByText('Obsidian: nicht erreichbar (http://192.0.2.12:8092/mcp)')).toBeInTheDocument();
    // Die gemeinsame ErrorMessage-Komponente zeigt den Hinweis ohne "Hinweis:"-Vorsatz an.
    expect(screen.getByText('Adresse und Netz prüfen')).toBeInTheDocument();
  });
});

describe('VaultPage Snippet', () => {
  it('Auswahl zeigt Markdown, Im Vault ablegen sendet save_attachment', async () => {
    const api = mockApi(routes());
    const { user } = renderWithProviders(<VaultPage />, { route: '/homelab/vault' });
    await user.click(await screen.findByRole('tab', { name: 'Snippet' }));
    await user.click(await screen.findByRole('button', { name: '#7 Datenträger pmx30' }));
    const md = await screen.findByLabelText('Markdown-Zeile');
    expect(md.textContent).toContain('![[label-20260926-101500-7.png]]');
    expect(api.calls.find((c) => c.path === '/api/v1/history?limit=20')).toBeTruthy();
    const first = api.calls.find((c) => c.path === '/api/v1/homelab/vault/snippet');
    expect(first?.body).toEqual({ history_id: 7, save_attachment: false, append_to: null });
    await user.click(screen.getByRole('button', { name: 'Im Vault ablegen' }));
    await screen.findByText(/Im Vault abgelegt:/);
    const calls = api.calls.filter((c) => c.path === '/api/v1/homelab/vault/snippet');
    expect(calls[1]?.body).toEqual({ history_id: 7, save_attachment: true, append_to: null });
  });

  it('Fehler beim Snippet zeigt Meldung', async () => {
    mockApi(
      routes({
        'POST /api/v1/homelab/vault/snippet': () =>
          new MockResponse(422, { error: { kind: 'ValueError', message: 'Kein gedrucktes Label mit Bild im Verlauf', hint: '', exit_code: 1, details: null } }),
      }),
    );
    const { user } = renderWithProviders(<VaultPage />, { route: '/homelab/vault' });
    await user.click(await screen.findByRole('tab', { name: 'Snippet' }));
    await user.click(await screen.findByRole('button', { name: '#7 Datenträger pmx30' }));
    const bar = await screen.findByText('Kein gedrucktes Label mit Bild im Verlauf');
    expect(within(bar.closest('.fui-MessageBar') as HTMLElement).getByText('Kein gedrucktes Label mit Bild im Verlauf')).toBeInTheDocument();
  });
});
