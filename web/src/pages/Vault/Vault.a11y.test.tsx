/** Barrierefreiheit und Tastatur der Seite Vault: axe in de/en, Tastatur, Fokusfalle. */
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { findDialog, fixtures, mockApi, renderWithProviders, type MockHandler } from '../../test/utils';
import type { Language } from '../../i18n';
import type { HistoryEntryJson, TemplateSummary } from '../../api/types';
import VaultPage from './index';
import type { SnippetJson, VaultNoteJson } from './types';

const NOTE: VaultNoteJson = {
  path: 'Hosts/pmx30',
  title: 'pmx30',
  values: { ip: '192.0.2.99' },
  tables: [],
};

function template(name: string): TemplateSummary {
  return {
    name, description: '', category: 'Homelab', tags: [], kind: 'layout', builtin: true, favorite: false,
    target: null, tapes: [], default_copies: 1, input_fields: [], sample: {},
  };
}

function historyEntry(id: number, title: string): HistoryEntryJson {
  return {
    id, created: '2026-09-26T10:15:00', source: 'api', kind: 'template', title, template: 'datentraeger', values: {},
    spec: null, length_mm: 20, tape_mm: 12, copies: 1, chained: false, status: 'ok', error: '', sensitive: false,
    has_head: true, reprintable: true, missing_secrets: [],
  };
}

function snippetJson(o: Partial<SnippetJson> = {}): SnippetJson {
  return {
    history_id: 7, file_name: 'label.png', png: fixtures.pngB64,
    markdown: '- 2026-09-26 Label gedruckt: pmx30 ![[label.png]]',
    changelog_md: '- Label gedruckt: pmx30 (Verlauf #7)', summary: 'pmx30',
    saved_path: null, appended: false, warnings: [], ...o,
  };
}

function routes(extra: Record<string, MockHandler> = {}): Record<string, MockHandler> {
  return {
    'GET /api/v1/homelab/vault/notes': () => ({ folders: ['Hosts'], notes: ['Hosts/pmx30'] }),
    'GET /api/v1/homelab/vault/note': () => NOTE,
    'GET /api/v1/homelab/settings': () => ({ settings: { obsidian: { append_after_print: true, folders: ['Hosts'], vault_dir: null } } }),
    'GET /api/v1/templates': () => ({ templates: [template('host-ip')] }),
    'POST /api/v1/labels/render': () => fixtures.renderJson(),
    'GET /api/v1/history': () => ({ entries: [historyEntry(7, 'Datenträger pmx30')] }),
    'POST /api/v1/homelab/vault/snippet': () => snippetJson(),
    ...extra,
  };
}

const SNIPPET_TAB = { de: 'Snippet', en: 'Snippet' } as const;
const CHANGELOG_BUTTON = { de: 'Changelog-Eintrag', en: 'Changelog entry' } as const;
const CHANGELOG_DIALOG_TITLE = { de: 'Changelog-Eintrag', en: 'Changelog entry' } as const;

describe.each(['de', 'en'] as Language[])('Vault a11y (%s)', (language) => {
  it('Grundzustand ohne axe-Befund', async () => {
    mockApi(routes());
    const { container, user } = renderWithProviders(<VaultPage />, { language, route: '/homelab/vault' });
    await user.click(await screen.findByRole('button', { name: 'Hosts/pmx30' }));
    await screen.findByText('192.0.2.99');
    await expectNoA11yViolations(container);
  });

  it('leerer Zustand ohne axe-Befund', async () => {
    mockApi(routes({ 'GET /api/v1/homelab/vault/notes': () => ({ folders: [], notes: [] }) }));
    const { container } = renderWithProviders(<VaultPage />, { language, route: '/homelab/vault' });
    await screen.findByRole('heading', { level: 2, name: language === 'de' ? 'Keine Notiz gewählt' : 'No note selected' });
    await expectNoA11yViolations(container);
  });

  it('Dialog (Changelog-Eintrag) ohne axe-Befund', async () => {
    mockApi(routes());
    const { container, user } = renderWithProviders(<VaultPage />, { language, route: '/homelab/vault' });
    await user.click(await screen.findByRole('tab', { name: SNIPPET_TAB[language] }));
    await user.click(await screen.findByRole('button', { name: /#7/ }));
    await user.click(await screen.findByRole('button', { name: CHANGELOG_BUTTON[language] }));
    await findDialog(CHANGELOG_DIALOG_TITLE[language]);
    await expectNoA11yViolations(container);
  });
});

describe('Vault Englisch', () => {
  it('Überschrift und Hauptaktion sind englisch', async () => {
    mockApi(routes());
    renderWithProviders(<VaultPage />, { language: 'en', route: '/homelab/vault' });
    expect(await screen.findByRole('heading', { level: 1, name: 'Obsidian vault' })).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Hosts/pmx30' })).toBeInTheDocument();
  });
});

describe('Vault Tastatur', () => {
  it('Changelog-Dialog: Auslöser per Tastatur erreichbar, Escape schließt und gibt Fokus zurück', async () => {
    mockApi(routes());
    const { user } = renderWithProviders(<VaultPage />, { route: '/homelab/vault' });
    await user.click(await screen.findByRole('tab', { name: 'Snippet' }));
    await user.click(await screen.findByRole('button', { name: /#7/ }));
    const trigger = await screen.findByRole('button', { name: 'Changelog-Eintrag' });
    trigger.focus();
    expect(trigger).toHaveFocus();
    await user.keyboard('{Enter}');
    const dialog = await findDialog('Changelog-Eintrag');
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    await user.keyboard('{Escape}');
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
