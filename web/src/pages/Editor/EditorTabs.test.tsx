import { describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { screen, waitFor, within } from '@testing-library/react';
import { findDialog, fixtures, mockApi, renderWithProviders, SLOW_UI_MS, type MockApi } from '../../test/utils';
import type { Draft, DraftInfo, EditResult, LabelDocumentJson, LabelObjectJson } from '../../api/types';
import EditorPage from './index';

vi.mock('react-konva', () => {
  const Box = (props: { children?: ReactNode }) => <div>{props.children}</div>;
  const Leaf = () => null;
  return { Stage: Box, Layer: Box, Group: Box, Rect: Leaf, Line: Leaf, Image: Leaf, Text: Leaf };
});

const TEXT: LabelObjectJson = { kind: 'text', id: 'text1', x: 8, y: 8, w: 80, h: 40, text: 'Hallo' };
const DOC_A: LabelDocumentJson = { version: 1, objects: [TEXT] };

function draftInfo(id: string, title: string, docName: string | null, extra?: Partial<DraftInfo>): DraftInfo {
  return { id, title, doc_name: docName, dirty: false, updated: '2026-09-28T10:00:00', objects: 1, order: 0, session: 'andere', ...extra };
}

function setup(opts?: { route?: string; own?: Draft[] }): { api: MockApi; user: ReturnType<typeof renderWithProviders>['user'] } {
  const own = opts?.own ?? [];
  const api = mockApi({
    'GET /api/v1/drafts': () => ({ drafts: own, own, orphaned: [] }),
    'GET /api/v1/drafts/:id': ({ params }) => own.find((d) => d.id === params.id),
    'PUT /api/v1/drafts/:id': ({ params }) => ({ id: params.id }),
    'DELETE /api/v1/drafts/:id': () => ({}),
    'GET /api/v1/documents/:name': ({ params }) => ({ name: params.name, document: DOC_A }),
    'PUT /api/v1/documents/:name': ({ params }) => ({ name: params.name, modified: '2026-09-28T10:00:00', objects: 1 }),
    'GET /api/v1/documents': () => ({ documents: [] }),
    'GET /api/v1/labels/fonts': () => ({ fonts: [] }),
    'GET /api/v1/targets': () => ({ targets: [] }),
    'POST /api/v1/labels/render': () => fixtures.renderJson(),
    'POST /api/v1/editor/new-object': ({ body }) => {
      const b = body as { document: LabelDocumentJson };
      return { document: { ...b.document, objects: [...b.document.objects, TEXT] }, selected: ['text1'], step_label: 'Text hinzugefügt', guides: [] } satisfies EditResult;
    },
  });
  const { user } = renderWithProviders(<EditorPage />, { route: opts?.route ?? '/editor' });
  return { api, user };
}

function tabs(): HTMLElement[] {
  // hidden: true wegen möglicher Tabster-Reste eines eben geschlossenen Dialogs unter Volllast.
  return within(screen.getByRole('tablist', { name: 'Geöffnete Etiketten', hidden: true })).getAllByRole('tab', { hidden: true });
}

function selectedTab(): HTMLElement | undefined {
  return tabs().find((t) => t.getAttribute('aria-selected') === 'true');
}

async function ready(api: MockApi) {
  await screen.findByRole('application', {}, { timeout: SLOW_UI_MS });
  await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/render')).toBe(true));
}

async function addText(user: ReturnType<typeof renderWithProviders>['user']) {
  await user.click(screen.getByRole('button', { name: 'Text' }));
  await waitFor(() => expect(selectedTab()).toHaveAccessibleName(/ungespeichert/));
}

describe('Editor-Tabs', () => {
  it('Strg+Alt+T öffnet einen Tab, Strg+Bild ab und Strg+Bild auf wechseln zyklisch', async () => {
    const { api, user } = setup();
    await ready(api);
    expect(tabs()).toHaveLength(1);
    await user.keyboard('{Control>}{Alt>}t{/Alt}{/Control}');
    await waitFor(() => expect(tabs()).toHaveLength(2));
    expect(selectedTab()).toHaveAccessibleName('Unbenannt 2');
    await user.keyboard('{Control>}{PageDown}{/Control}');
    await waitFor(() => expect(selectedTab()).toHaveAccessibleName('Unbenannt'));
    await user.keyboard('{Control>}{PageUp}{/Control}');
    await waitFor(() => expect(selectedTab()).toHaveAccessibleName('Unbenannt 2'));
  });

  it('Knopf „Neuer Tab“ und Klick auf einen Tab wechseln das Etikett', async () => {
    const { api, user } = setup();
    await ready(api);
    await addText(user);
    await user.click(screen.getByRole('button', { name: 'Neuer Tab' }));
    await waitFor(() => expect(tabs()).toHaveLength(2));
    expect(screen.getByText('Leeres Etikett')).toBeInTheDocument();
    await user.click(tabs()[0]!);
    await waitFor(() => expect(screen.queryByText('Leeres Etikett')).not.toBeInTheDocument());
  });

  it('Strg+Alt+W auf ungespeichertem Tab fragt nach; „Abbrechen“ lässt ihn offen', async () => {
    const { api, user } = setup();
    await ready(api);
    await addText(user);
    await user.keyboard('{Control>}{Alt>}w{/Alt}{/Control}');
    const dialog = await findDialog('Änderungen an „Unbenannt“ speichern?');
    await user.click(within(dialog).getByRole('button', { name: 'Abbrechen', hidden: true }));
    await waitFor(() => expect(screen.queryByText('Änderungen an „Unbenannt“ speichern?')).not.toBeInTheDocument(), { timeout: SLOW_UI_MS });
    expect(selectedTab()).toHaveAccessibleName('Unbenannt, ungespeichert');
    expect(api.calls.some((c) => c.method === 'DELETE')).toBe(false);
  });

  it('„Nicht speichern“ schließt den Tab und löscht seinen Entwurf', async () => {
    const { api, user } = setup();
    await ready(api);
    await addText(user);
    await user.keyboard('{Control>}{Alt>}w{/Alt}{/Control}');
    const dialog = await findDialog('Änderungen an „Unbenannt“ speichern?');
    await user.click(within(dialog).getByRole('button', { name: 'Nicht speichern', hidden: true }));
    await waitFor(() => expect(api.calls.filter((c) => c.method === 'DELETE' && c.path.startsWith('/api/v1/drafts/'))).toHaveLength(1));
    await waitFor(() => expect(selectedTab()).toHaveAccessibleName('Unbenannt'));
    expect(tabs()).toHaveLength(1);
    expect(screen.getByText('Leeres Etikett')).toBeInTheDocument();
  });

  it('„Speichern“ bei unbenanntem Tab öffnet „Speichern unter“ und schließt den Tab danach', async () => {
    const { api, user } = setup();
    await ready(api);
    await addText(user);
    await user.keyboard('{Control>}{Alt>}w{/Alt}{/Control}');
    const ask = await findDialog('Änderungen an „Unbenannt“ speichern?');
    await user.click(within(ask).getByRole('button', { name: 'Speichern', hidden: true }));
    const dialog = await findDialog('Speichern unter');
    const name = await within(dialog).findByRole('textbox', { name: 'Name', hidden: true }, { timeout: SLOW_UI_MS });
    await user.type(name, 'Neu1');
    await user.click(within(dialog).getByRole('button', { name: 'Speichern', hidden: true }));
    await waitFor(() => expect(api.calls.some((c) => c.method === 'PUT' && c.path === '/api/v1/documents/Neu1')).toBe(true));
    await waitFor(() => expect(api.calls.filter((c) => c.method === 'DELETE' && c.path.startsWith('/api/v1/drafts/'))).toHaveLength(1));
    await waitFor(() => expect(selectedTab()).toHaveAccessibleName('Unbenannt'));
    expect(tabs()).toHaveLength(1);
  });

  it('?dokument=A bei offenem Tab A aktiviert ihn statt einen neuen zu öffnen', async () => {
    const draftA: Draft = { ...draftInfo('draft-aaaa-0001', 'A', 'A'), document: DOC_A };
    const draftB: Draft = { ...draftInfo('draft-bbbb-0002', 'B', 'B', { order: 1 }), document: DOC_A };
    const { api } = setup({ route: '/editor?dokument=A', own: [draftB, draftA] });
    await ready(api);
    await waitFor(() => expect(selectedTab()).toHaveAccessibleName('A'));
    expect(tabs()).toHaveLength(2);
    expect(api.calls.some((c) => c.path === '/api/v1/documents/A')).toBe(false);
  });

  it('Ungespeichert-Register: ein ungespeicherter Tab zählt 1, nach dem Speichern 0', async () => {
    const { api, user } = setup({ route: '/editor?dokument=Zwei' });
    await ready(api);
    await waitFor(() => expect(selectedTab()).toHaveAccessibleName('Zwei'));
    expect(window.p12UnsavedCount?.()).toBe(0);
    await addText(user);
    expect(window.p12UnsavedCount?.()).toBe(1);
    await user.keyboard('{Control>}s{/Control}');
    await waitFor(() => expect(api.calls.some((c) => c.method === 'PUT' && c.path === '/api/v1/documents/Zwei')).toBe(true));
    await waitFor(() => expect(window.p12UnsavedCount?.()).toBe(0));
    expect(selectedTab()).toHaveAccessibleName('Zwei');
  });
});
