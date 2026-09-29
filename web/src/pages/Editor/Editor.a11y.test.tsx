import { describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { screen, waitFor, within } from '@testing-library/react';
import { expectNoA11yViolations } from '../../test/a11y';
import { findDialog, fixtures, mockApi, renderWithProviders, SLOW_UI_MS, type MockApi } from '../../test/utils';
import type { Draft, EditResult, LabelDocumentJson, LabelObjectJson } from '../../api/types';
import type { Language } from '../../i18n';
import EditorPage from './index';

vi.mock('react-konva', () => {
  const Box = (props: { children?: ReactNode }) => <div>{props.children}</div>;
  const Leaf = () => null;
  return { Stage: Box, Layer: Box, Group: Box, Rect: Leaf, Line: Leaf, Image: Leaf, Text: Leaf };
});

const TEXT: LabelObjectJson = { kind: 'text', id: 'text1', x: 8, y: 8, w: 80, h: 40, text: 'Hallo' };
const QR: LabelObjectJson = { kind: 'qr', id: 'qr1', x: 100, y: 8, w: 60, h: 60, data: 'https://example.org' };
const FULL: LabelDocumentJson = { version: 1, objects: [TEXT, QR] };

function orphan(id: string, title: string): Draft {
  return { id, title, doc_name: null, dirty: true, updated: new Date().toISOString(), objects: 1, order: 0, session: 'alt', document: FULL };
}

function setup(opts: { language?: Language; route?: string; orphaned?: Draft[] }): { api: MockApi; user: ReturnType<typeof renderWithProviders>['user'] } {
  const orphaned = opts.orphaned ?? [];
  const api = mockApi({
    'GET /api/v1/drafts': () => ({ drafts: orphaned, own: [], orphaned }),
    'PUT /api/v1/drafts/:id': ({ params }) => ({ id: params.id }),
    'DELETE /api/v1/drafts/:id': () => ({}),
    'GET /api/v1/documents/:name': ({ params }) => ({ name: params.name, document: FULL }),
    'GET /api/v1/documents': () => ({ documents: [] }),
    'GET /api/v1/labels/fonts': () => ({ fonts: [{ id: 'sans', name: 'Sans' }] }),
    'GET /api/v1/targets': () => ({ targets: [] }),
    'POST /api/v1/labels/render': ({ body }) => {
      const doc = (body as { source: { document: LabelDocumentJson } }).source.document;
      const boxes: Record<string, [number, number, number, number]> = {};
      for (const o of doc.objects) boxes[o.id] = [o.x, o.y, o.w, o.h];
      return fixtures.renderJson({ editor: { png: fixtures.pngB64, width: 400, height: 96, boxes, font_sizes: {}, codes: {} } });
    },
    'POST /api/v1/labels/print': () => fixtures.outcomeJson(),
    'POST /api/v1/editor/op': ({ body }) => {
      const b = body as { document: LabelDocumentJson; ids: string[] };
      return { document: b.document, selected: b.ids, step_label: 'Geändert', guides: [] } satisfies EditResult;
    },
  });
  const { user } = renderWithProviders(<EditorPage />, { route: opts.route ?? '/editor', language: opts.language ?? 'de' });
  return { api, user };
}

async function ready(api: MockApi) {
  await screen.findByRole('application', {}, { timeout: SLOW_UI_MS });
  await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/render')).toBe(true));
}

const PANELS: Record<Language, { layers: string; props: string; empty: string }> = {
  de: { layers: 'Ebenen', props: 'Eigenschaften', empty: 'Leeres Etikett' },
  en: { layers: 'Layers', props: 'Properties', empty: 'Empty label' },
};

describe('Editor: Barrierefreiheit', () => {
  for (const language of ['de', 'en'] as const) {
    it(`leerer Tab ohne axe-Befund (${language})`, async () => {
      const { api } = setup({ language });
      await ready(api);
      expect(screen.getByText(PANELS[language].empty)).toBeInTheDocument();
      await expectNoA11yViolations(document.body);
    });

    it(`gefülltes Dokument mit Auswahl ohne axe-Befund (${language})`, async () => {
      const { api, user } = setup({ language, route: '/editor?dokument=Voll' });
      await ready(api);
      await user.click(screen.getByRole('tab', { name: PANELS[language].layers }));
      await user.click(await screen.findByRole('option', { name: /text1/ }));
      await user.click(screen.getByRole('tab', { name: PANELS[language].props }));
      await screen.findByRole('heading', { name: /text1/ });
      await expectNoA11yViolations(document.body);
    });

    it(`offener Wiederherstellungsdialog ohne axe-Befund (${language})`, async () => {
      const { api } = setup({ language, orphaned: [orphan('draft-0000-0001', 'Server'), orphan('draft-0000-0002', 'Kabel')] });
      await ready(api);
      await findDialog(language === 'de' ? 'Entwürfe wiederherstellen?' : 'Restore drafts?');
      await expectNoA11yViolations(document.body);
    });
  }

  it('Tastatur: von der Tabliste per Tab zur Werkzeugleiste, „Drucken“ per Enter', async () => {
    const { api, user } = setup({ route: '/editor?dokument=Voll' });
    await ready(api);
    const printButton = screen.getByRole('button', { name: 'Drucken' });
    await waitFor(() => expect(printButton).toBeEnabled());
    const tablist = screen.getByRole('tablist', { name: 'Geöffnete Etiketten' });
    const tab = within(tablist).getByRole('tab', { name: 'Voll' });
    tab.focus();
    expect(document.activeElement).toBe(tab);
    // Tabster übernimmt die Tab-Taste selbst und findet in jsdom (ohne Layout) kein Ziel; die
    // Tab-Reihenfolge wird deshalb über das DOM geprüft: nach der Tabliste kommen „Neuer Tab“ und
    // dann die Werkzeugleiste (Schließen-Knöpfe der Tabs sind nicht per Tab erreichbar).
    const tabbable = Array.from(document.querySelectorAll<HTMLElement>('button, [href], input, select, textarea, [tabindex]')).filter(
      (el) => !el.hasAttribute('disabled') && el.tabIndex >= 0 && !el.closest('[aria-hidden="true"]') && !tablist.contains(el),
    );
    const after = tabbable.filter((el) => tab.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
    expect(after[0]).toHaveAccessibleName('Neuer Tab');
    const toolbar = screen.getByRole('toolbar', { name: 'Editor-Werkzeuge' });
    expect(toolbar.contains(after[1]!)).toBe(true);
    expect(tablist.querySelectorAll('[role="button"]:not([aria-hidden="true"])')).toHaveLength(0);
    printButton.focus();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
  });

  it('Dialog gibt den Fokus an den Auslöser zurück', async () => {
    const { api, user } = setup({});
    await ready(api);
    const trigger = screen.getByRole('button', { name: 'Öffnen' });
    await user.click(trigger);
    const dialog = await findDialog('Dokument öffnen');
    await user.click(within(dialog).getByRole('button', { name: 'Abbrechen', hidden: true }));
    await waitFor(() => expect(screen.queryByText('Dokument öffnen')).not.toBeInTheDocument(), { timeout: SLOW_UI_MS });
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });
});
