import { describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { act, renderHook, screen, waitFor, within } from '@testing-library/react';
import { findDialog, fixtures, mockApi, MockResponse, renderWithProviders, SLOW_UI_MS, type MockApi } from '../../test/utils';
import { setTokenForTests } from '../../api/client';
import { push } from './undoStack';
import { takeLeftoverDrafts, useDraftSync } from './tabs/useDraftSync';
import { initialTabs } from './tabs/useEditorTabs';
import type { Draft, DraftInfo, LabelDocumentJson } from '../../api/types';
import EditorPage from './index';

vi.mock('react-konva', () => {
  const Box = (props: { children?: ReactNode }) => <div>{props.children}</div>;
  const Leaf = () => null;
  return { Stage: Box, Layer: Box, Group: Box, Rect: Leaf, Line: Leaf, Image: Leaf, Text: Leaf };
});

const DOC: LabelDocumentJson = { version: 1, objects: [{ kind: 'text', id: 'text1', x: 8, y: 8, w: 80, h: 40, text: 'Hallo' }] };

function draft(id: string, title: string, extra?: Partial<DraftInfo>): Draft {
  return {
    id,
    title,
    doc_name: null,
    dirty: true,
    updated: new Date(Date.now() - 5 * 60_000).toISOString(),
    objects: 1,
    order: 0,
    session: 'alte-sitzung',
    document: DOC,
    ...extra,
  };
}

const info = (d: Draft): DraftInfo => {
  const { document: _document, ...rest } = d;
  return rest;
};

function setup(opts: { own?: Draft[]; orphaned?: Draft[]; route?: string }): { api: MockApi; user: ReturnType<typeof renderWithProviders>['user'] } {
  const own = opts.own ?? [];
  const orphaned = opts.orphaned ?? [];
  const all = [...own, ...orphaned];
  const api = mockApi({
    'GET /api/v1/drafts': () => ({ drafts: [...own, ...orphaned].map(info), own: own.map(info), orphaned: orphaned.map(info) }),
    'GET /api/v1/drafts/:id': ({ params }) => all.find((d) => d.id === params.id),
    'POST /api/v1/drafts/:id/adopt': ({ params }) => info(all.find((d) => d.id === params.id)!),
    'PUT /api/v1/drafts/:id': ({ params }) => ({ id: params.id }),
    'DELETE /api/v1/drafts/:id': () => ({}),
    'GET /api/v1/labels/fonts': () => ({ fonts: [] }),
    'GET /api/v1/targets': () => ({ targets: [] }),
    'POST /api/v1/labels/render': () => fixtures.renderJson(),
  });
  const { user } = renderWithProviders(<EditorPage />, { route: opts.route ?? '/editor' });
  return { api, user };
}

// hidden: true, weil ein eben geschlossener Dialog unter voller Parallellast (Tabster-Rest) die
// Seite kurzzeitig noch als aria-hidden markieren kann, obwohl sie sichtbar ist.
function tabNames(): string[] {
  return within(screen.getByRole('tablist', { name: 'Geöffnete Etiketten', hidden: true }))
    .getAllByRole('tab', { hidden: true })
    .map((t) => t.getAttribute('aria-label') ?? '');
}

const TWO = [draft('draft-0000-0001', 'Server-Etikett'), draft('draft-0000-0002', 'Kabel', { dirty: false, doc_name: 'Kabel', objects: 3 })];

/** Lässt einen Editor-Tab mit Stand `text` beim Verlassen nicht mehr beim Dienst ankommen (Dienst weg). */
async function leaveEditorOffline(id: string, title: string, text: string): Promise<void> {
  setTokenForTests('test-token');
  const off = mockApi(
    {
      'PUT /api/v1/drafts/:id': () =>
        new MockResponse(503, { error: { kind: 'Offline', code: 'internal', message: 'weg', hint: '', exit_code: 5, details: null } }),
    },
    { quiet: true },
  );
  const base = { ...initialTabs(() => title).tabs[0]!, id, title, untitledNo: null };
  const { rerender, unmount } = renderHook(({ tabs }) => useDraftSync(tabs, { enabled: true, retryMs: 60_000 }), {
    initialProps: { tabs: [base] },
  });
  const doc: LabelDocumentJson = { version: 1, objects: [{ kind: 'text', id: 'text1', x: 8, y: 8, w: 80, h: 40, text }] };
  rerender({ tabs: [{ ...base, undo: push(base.undo, doc, 'Text geändert') }] });
  unmount();
  await waitFor(() => expect(off.calls.some((c) => c.method === 'PUT')).toBe(true));
  await act(async () => {
    await new Promise((r) => setTimeout(r, 10));
  });
  off.restore();
}

describe('Editor: Wiederherstellung', () => {
  it('zwei verwaiste Entwürfe: Dialog mit beiden, „Wiederherstellen“ übernimmt sie als Tabs', async () => {
    const { api, user } = setup({ orphaned: TWO });
    const dialog = await findDialog('Entwürfe wiederherstellen?');
    expect(within(dialog).getByText('Server-Etikett')).toBeInTheDocument();
    expect(within(dialog).getByText('Kabel')).toBeInTheDocument();
    expect(within(dialog).getByText('ungespeichert')).toBeInTheDocument();
    expect(within(dialog).getByText(/3 Objekte/)).toBeInTheDocument();
    expect(within(dialog).getAllByRole('checkbox', { hidden: true }).every((c) => (c as HTMLInputElement).checked)).toBe(true);
    await user.click(within(dialog).getByRole('button', { name: 'Wiederherstellen', hidden: true }));
    await waitFor(() => expect(api.calls.filter((c) => c.method === 'POST' && c.path.endsWith('/adopt'))).toHaveLength(2));
    await waitFor(() => expect(tabNames()).toEqual(['Server-Etikett, ungespeichert', 'Kabel']));
  });

  it('„Verwerfen“ löscht nach Rückfrage die ausgewählten Entwürfe', async () => {
    const { api, user } = setup({ orphaned: TWO });
    const dialog = await findDialog('Entwürfe wiederherstellen?');
    await user.click(within(dialog).getByRole('button', { name: 'Verwerfen', hidden: true }));
    const askTitle = await screen.findByText('Ausgewählte Entwürfe verwerfen?', {}, { timeout: SLOW_UI_MS });
    const ask = askTitle.closest<HTMLElement>('[role="alertdialog"]')!;
    await user.click(within(ask).getByRole('button', { name: 'Verwerfen', hidden: true }));
    await waitFor(() =>
      expect(api.calls.filter((c) => c.method === 'DELETE').map((c) => c.path)).toEqual([
        '/api/v1/drafts/draft-0000-0001',
        '/api/v1/drafts/draft-0000-0002',
      ]),
    );
    expect(api.calls.some((c) => c.path.endsWith('/adopt'))).toBe(false);
    expect(tabNames()).toEqual(['Unbenannt']);
  });

  it('„Später“ schließt den Dialog und ändert nichts', async () => {
    const { api, user } = setup({ orphaned: TWO });
    const dialog = await findDialog('Entwürfe wiederherstellen?');
    await user.click(within(dialog).getByRole('button', { name: 'Später', hidden: true }));
    await waitFor(() => expect(screen.queryByText('Entwürfe wiederherstellen?')).not.toBeInTheDocument(), { timeout: SLOW_UI_MS });
    expect(api.calls.some((c) => c.method === 'DELETE' || c.path.endsWith('/adopt'))).toBe(false);
    expect(tabNames()).toEqual(['Unbenannt']);
  });

  it('eigene Entwürfe kommen ohne Dialog als Tabs zurück', async () => {
    const own = [draft('draft-0000-0011', 'Mein Etikett', { session: 'diese' }), draft('draft-0000-0012', 'Zweites', { session: 'diese', dirty: false, doc_name: 'Zweites', order: 1 })];
    const { api } = setup({ own });
    await waitFor(() => expect(tabNames()).toEqual(['Mein Etikett, ungespeichert', 'Zweites']));
    expect(screen.queryByText('Entwürfe wiederherstellen?')).not.toBeInTheDocument();
    expect(api.calls.some((c) => c.path.endsWith('/adopt'))).toBe(false);
  });

  it('Editor offline verlassen und wieder geöffnet: der neuere Stand ersetzt den Entwurf des Servers', async () => {
    await leaveEditorOffline('draft-0000-0031', 'Neuer Stand', 'Neu');
    const own = [draft('draft-0000-0031', 'Alter Stand', { session: 'diese' })];
    const { api } = setup({ own });
    await waitFor(() => expect(tabNames()).toEqual(['Neuer Stand, ungespeichert']));
    expect(api.calls.some((c) => c.method === 'GET' && c.path === '/api/v1/drafts/draft-0000-0031')).toBe(false);
    // Der Tab sichert seinen Stand erneut.
    await waitFor(
      () => {
        const put = api.calls.find((c) => c.method === 'PUT' && c.path === '/api/v1/drafts/draft-0000-0031');
        expect((put?.body as { document?: LabelDocumentJson } | undefined)?.document?.objects[0]).toMatchObject({ text: 'Neu' });
      },
      { timeout: 5000 },
    );
    expect(takeLeftoverDrafts().size).toBe(0);
  });

  it('nie beim Dienst angekommener Tab kommt beim erneuten Öffnen trotzdem zurück', async () => {
    await leaveEditorOffline('draft-0000-0032', 'Nur lokal', 'Lokal');
    setup({});
    await waitFor(() => expect(tabNames()).toEqual(['Nur lokal, ungespeichert']));
  });

  it('erstes Öffnen ohne verwaiste Entwürfe verbraucht das Angebot nicht (später verwaiste kommen noch)', async () => {
    sessionStorage.removeItem('p12.editor.recoveryOffered');
    const first = setup({ orphaned: [] });
    await screen.findByRole('application', {}, { timeout: SLOW_UI_MS });
    await waitFor(() => expect(first.api.calls.some((c) => c.path.startsWith('/api/v1/drafts?'))).toBe(true));
    first.api.restore();
    document.body.innerHTML = '';
    setup({ orphaned: TWO });
    await findDialog('Entwürfe wiederherstellen?');
  });

  it('ohne ?wiederherstellen=1 nur beim ersten Öffnen je Fenster, mit der Query auch danach', async () => {
    sessionStorage.setItem('p12.editor.recoveryOffered', '1');
    const first = setup({ orphaned: TWO });
    await screen.findByRole('application', {}, { timeout: SLOW_UI_MS });
    await waitFor(() => expect(first.api.calls.some((c) => c.path.startsWith('/api/v1/drafts?'))).toBe(true));
    expect(screen.queryByText('Entwürfe wiederherstellen?')).not.toBeInTheDocument();
    first.api.restore();
    document.body.innerHTML = '';
    setup({ orphaned: TWO, route: '/editor?wiederherstellen=1' });
    await findDialog('Entwürfe wiederherstellen?');
  });
});
