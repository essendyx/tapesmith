import { describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { screen, waitFor, within } from '@testing-library/react';
import { anyDialogInDom, findDialog, fixtures, MockResponse, mockApi, renderWithProviders, SLOW_UI_MS, type MockApi } from '../../test/utils';
import type {
  EditOpRequest,
  EditResult,
  LabelDocumentJson,
  LabelObjectJson,
  ObjectIssueJson,
  RenderJson,
} from '../../api/types';
import EditorPage from './index';

vi.mock('react-konva', () => {
  const Box = (props: { children?: ReactNode }) => <div>{props.children}</div>;
  const Leaf = () => null;
  return { Stage: Box, Layer: Box, Group: Box, Rect: Leaf, Line: Leaf, Image: Leaf, Text: Leaf };
});

const TEXT1: LabelObjectJson = { kind: 'text', id: 'text1', x: 8, y: 8, w: 80, h: 40, text: 'Hallo' };
const TEXT2: LabelObjectJson = { kind: 'text', id: 'text2', x: 100, y: 8, w: 80, h: 40, text: 'Welt' };
const TWO: LabelDocumentJson = { version: 1, objects: [TEXT1, TEXT2] };
const QR1: LabelObjectJson = { kind: 'qr', id: 'qr1', x: 0, y: 0, w: 64, h: 64, data: 'HTTP://L.LAN/D7' };
const QR_DOC: LabelDocumentJson = { version: 1, objects: [QR1] };

function overlay(doc: LabelDocumentJson) {
  const boxes: Record<string, [number, number, number, number]> = {};
  for (const o of doc.objects) boxes[o.id] = [o.x, o.y, o.w, o.h];
  return { png: fixtures.pngB64, width: 400, height: 96, boxes, font_sizes: {}, codes: {} };
}

function fakeOp(req: EditOpRequest): EditResult {
  const doc = req.document;
  switch (req.op) {
    case 'update': {
      const changes = (req.params.changes ?? {}) as Record<string, unknown>;
      return {
        document: { ...doc, objects: doc.objects.map((o) => (req.ids.includes(o.id) ? { ...o, ...changes } : o)) },
        selected: req.ids,
        step_label: 'Text geändert',
        guides: [],
      };
    }
    case 'remove':
      return { document: { ...doc, objects: doc.objects.filter((o) => !req.ids.includes(o.id)) }, selected: [], step_label: 'Text gelöscht', guides: [] };
    case 'duplicate': {
      const copies = doc.objects.filter((o) => req.ids.includes(o.id)).map((o) => ({ ...o, id: `${o.id}k`, x: o.x + 8 }));
      return { document: { ...doc, objects: [...doc.objects, ...copies] }, selected: copies.map((c) => c.id), step_label: 'Text dupliziert', guides: [] };
    }
    default:
      return { document: doc, selected: req.ids, step_label: 'Geändert', guides: [] };
  }
}

function setup(opts?: {
  route?: string;
  render?: (doc: LabelDocumentJson) => Partial<RenderJson>;
  extra?: Parameters<typeof mockApi>[0];
}): { api: MockApi; user: ReturnType<typeof renderWithProviders>['user'] } {
  const api = mockApi({
    'GET /api/v1/documents/:name': ({ params }) =>
      params.name === 'Zwei'
        ? { name: 'Zwei', document: TWO }
        : params.name === 'QR'
          ? { name: 'QR', document: QR_DOC }
          : new MockResponse(404, { error: { kind: 'NotFound', message: 'Nicht gefunden', hint: '', exit_code: 1, details: null } }),
    'PUT /api/v1/documents/:name': ({ params, body }) => ({
      name: params.name,
      modified: '2026-09-28T10:00:00',
      objects: (body as { document: LabelDocumentJson }).document.objects.length,
    }),
    'GET /api/v1/documents': () => ({ documents: [] }),
    'GET /api/v1/labels/fonts': () => ({ fonts: [{ id: 'sans', name: 'Sans' }] }),
    'GET /api/v1/targets': () => ({ targets: [] }),
    'POST /api/v1/labels/render': ({ body }) => {
      const doc = (body as { source: { document: LabelDocumentJson } }).source.document;
      return fixtures.renderJson({ editor: overlay(doc), ...(opts?.render?.(doc) ?? {}) });
    },
    'POST /api/v1/editor/new-object': ({ body }) => {
      const b = body as { document: LabelDocumentJson; preset: string; png?: string };
      const obj: LabelObjectJson =
        b.preset === 'image'
          ? { kind: 'image', id: 'image1', x: 0, y: 0, w: 40, h: 40, png: b.png ?? '' }
          : { ...TEXT1, text: 'Text' };
      return {
        document: { ...b.document, objects: [...b.document.objects, obj] },
        selected: [obj.id],
        step_label: b.preset === 'image' ? 'Bild hinzugefügt' : 'Text hinzugefügt',
        guides: [],
      } satisfies EditResult;
    },
    'POST /api/v1/editor/op': ({ body }) => fakeOp(body as EditOpRequest),
    'GET /api/v1/drafts': () => ({ drafts: [], own: [], orphaned: [] }),
    'PUT /api/v1/drafts/:id': ({ params }) => ({ id: params.id }),
    'DELETE /api/v1/drafts/:id': () => ({}),
    ...(opts?.extra ?? {}),
  });
  const { user } = renderWithProviders(<EditorPage />, { route: opts?.route ?? '/editor' });
  return { api, user };
}

function renders(api: MockApi): LabelDocumentJson[] {
  return api.calls
    .filter((c) => c.path === '/api/v1/labels/render')
    .map((c) => (c.body as { source: { document: LabelDocumentJson } }).source.document);
}

function ops(api: MockApi, op?: string): EditOpRequest[] {
  return api.calls
    .filter((c) => c.path === '/api/v1/editor/op')
    .map((c) => c.body as EditOpRequest)
    .filter((b) => !op || b.op === op);
}

async function addText(api: MockApi, user: ReturnType<typeof renderWithProviders>['user']) {
  await waitFor(() => expect(renders(api).length).toBeGreaterThan(0));
  await user.click(screen.getByRole('button', { name: 'Text' }));
  await waitFor(() => expect(renders(api).some((d) => d.objects.length === 1)).toBe(true));
}

async function openTab(user: ReturnType<typeof renderWithProviders>['user'], name: string) {
  await user.click(screen.getByRole('tab', { name }));
}

describe('Editor', () => {
  it('leerer Editor fragt die Entwürfe ab (nicht mehr _entwurf), Palette „Text“ fügt ein, rendert und schreibt den Verlauf', async () => {
    const { api, user } = setup();
    await waitFor(() => expect(renders(api)[0]).toEqual({ version: 1, objects: [] }));
    expect(api.calls.some((c) => c.method === 'GET' && c.path.startsWith('/api/v1/drafts?session='))).toBe(true);
    expect(api.calls.some((c) => c.path.startsWith('/api/v1/documents/_entwurf'))).toBe(false);
    await addText(api, user);
    const call = api.calls.find((c) => c.path === '/api/v1/editor/new-object');
    expect((call?.body as { preset: string }).preset).toBe('text');
    await openTab(user, 'Verlauf');
    const history = screen.getByRole('list', { name: 'Verlauf' });
    expect(within(history).getByRole('button', { name: /Text hinzugefügt/ })).toHaveAttribute('aria-current', 'step');
  });

  it('Text ändern sendet entprellt update, zwei schnelle Änderungen ergeben einen Schritt', async () => {
    const { api, user } = setup();
    await addText(api, user);
    const box = screen.getByRole('textbox', { name: 'Text' });
    await user.type(box, 'A');
    await waitFor(() => expect(ops(api, 'update')).toHaveLength(1));
    expect((ops(api, 'update')[0]?.params.changes as { text: string }).text).toBe('TextA');
    await user.type(box, 'B');
    await waitFor(() => expect(ops(api, 'update')).toHaveLength(2));
    expect((ops(api, 'update')[1]?.params.changes as { text: string }).text).toBe('TextAB');
    await openTab(user, 'Verlauf');
    const items = within(screen.getByRole('list', { name: 'Verlauf' })).getAllByRole('button');
    expect(items.map((i) => i.textContent)).toEqual(['Neues Label', 'Text hinzugefügt', 'Text geändert']);
  });

  it('Tabwechsel während einer entprellten Eingabe: die Änderung landet im Tab, in dem getippt wurde', async () => {
    const { api, user } = setup();
    await addText(api, user);
    // Zweiter Tab mit eigenem Text (gleiche Objekt-ID wie im ersten Tab)
    await user.keyboard('{Control>}{Alt>}t{/Alt}{/Control}');
    await waitFor(() => expect(screen.getAllByRole('tab', { name: /^Unbenannt 2/, hidden: true })).toHaveLength(1));
    await user.click(screen.getByRole('button', { name: 'Text' }));
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Text' })).toHaveValue('Text'));
    await user.type(screen.getByRole('textbox', { name: 'Text' }), 'Zwei');
    await waitFor(() => expect(ops(api, 'update').at(-1)?.params.changes).toEqual({ text: 'TextZwei' }));
    // Zurück zum ersten Tab, tippen und sofort (vor dem Senden) weiter zum zweiten Tab
    await user.keyboard('{Control>}{PageUp}{/Control}');
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Text' })).toHaveValue('Text'));
    const before = ops(api, 'update').length;
    await user.type(screen.getByRole('textbox', { name: 'Text' }), 'X');
    await user.keyboard('{Control>}{PageDown}{/Control}');
    await waitFor(() => expect(ops(api, 'update').length).toBeGreaterThan(before));
    const req = ops(api, 'update').at(-1)!;
    expect(req.params.changes).toEqual({ text: 'TextX' });
    expect(req.document.objects[0]).toMatchObject({ text: 'Text' });
    // Der zweite Tab bleibt unverändert
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Text' })).toHaveValue('TextZwei'));
    await new Promise((r) => setTimeout(r, 400));
    expect(screen.getByRole('textbox', { name: 'Text' })).toHaveValue('TextZwei');
    expect(ops(api, 'update').length).toBe(before + 1);
  });

  it('Strg+Z stellt das vorige Dokument her, Strg+Y wieder das neue', async () => {
    const { api, user } = setup();
    await addText(api, user);
    const before = renders(api).length;
    await user.keyboard('{Control>}z{/Control}');
    await waitFor(() => expect(renders(api).length).toBeGreaterThan(before));
    expect(renders(api).at(-1)?.objects).toHaveLength(0);
    const mid = renders(api).length;
    await user.keyboard('{Control>}y{/Control}');
    await waitFor(() => expect(renders(api).length).toBeGreaterThan(mid));
    expect(renders(api).at(-1)?.objects).toHaveLength(1);
  });

  it('Entf sendet remove mit der Auswahl, Strg+D duplicate', async () => {
    const { api, user } = setup();
    await addText(api, user);
    await user.keyboard('{Control>}d{/Control}');
    await waitFor(() => expect(ops(api, 'duplicate')).toHaveLength(1));
    expect(ops(api, 'duplicate')[0]?.ids).toEqual(['text1']);
    await user.keyboard('{Delete}');
    await waitFor(() => expect(ops(api, 'remove')).toHaveLength(1));
    expect(ops(api, 'remove')[0]?.ids).toEqual(['text1k']);
  });

  it('Ebenen: „Ganz nach vorn“ sendet reorder top', async () => {
    const { api, user } = setup({ route: '/editor?dokument=Zwei' });
    await waitFor(() => expect(renders(api).some((d) => d.objects.length === 2)).toBe(true));
    await openTab(user, 'Ebenen');
    await user.click(screen.getByRole('option', { name: /text1/ }));
    await user.click(screen.getByRole('button', { name: 'Ganz nach vorn' }));
    await waitFor(() => expect(ops(api, 'reorder')).toHaveLength(1));
    expect(ops(api, 'reorder')[0]).toMatchObject({ ids: ['text1'], params: { op: 'top' } });
  });

  it('Mehrfachauswahl im Ebenen-Panel mit Strg und „Links ausrichten“ sendet align left', async () => {
    const { api, user } = setup({ route: '/editor?dokument=Zwei' });
    await waitFor(() => expect(renders(api).some((d) => d.objects.length === 2)).toBe(true));
    await openTab(user, 'Ebenen');
    await user.click(screen.getByRole('option', { name: /text1/ }));
    await user.keyboard('{Control>}');
    await user.click(screen.getByRole('option', { name: /text2/ }));
    await user.keyboard('{/Control}');
    await openTab(user, 'Eigenschaften');
    await user.click(screen.getByRole('button', { name: 'Links ausrichten' }));
    await waitFor(() => expect(ops(api, 'align')).toHaveLength(1));
    const req = ops(api, 'align')[0]!;
    expect(req.params).toMatchObject({ mode: 'left', reference: 'selection' });
    expect([...req.ids].sort()).toEqual(['text1', 'text2']);
  });

  it('Klick auf einen Hinweis mit object_id wählt das Objekt', async () => {
    const issue: ObjectIssueJson = { object_id: 'text2', level: 'warning', message: 'Text ist zu lang' };
    const { user } = setup({ route: '/editor?dokument=Zwei', render: () => ({ issues: [issue] }) });
    await user.click(await screen.findByRole('button', { name: /Text ist zu lang/ }));
    expect(await screen.findByRole('heading', { name: /text2/ })).toBeInTheDocument();
  });

  it('?verlauf=5 lädt aus dem Verlauf, ?vorlage=datentraeger aus der Vorlage', async () => {
    const extra = {
      'POST /api/v1/documents/from-history/:id': () => ({ document: TWO }),
      'POST /api/v1/documents/from-template': () => ({ document: TWO }),
    };
    const first = setup({ route: '/editor?verlauf=5', extra });
    await waitFor(() => expect(first.api.calls.some((c) => c.method === 'POST' && c.path === '/api/v1/documents/from-history/5')).toBe(true));
    await waitFor(() => expect(renders(first.api).some((d) => d.objects.length === 2)).toBe(true));
    first.api.restore();
    const second = setup({ route: '/editor?vorlage=datentraeger', extra });
    await waitFor(() => {
      const call = second.api.calls.find((c) => c.path === '/api/v1/documents/from-template');
      expect(call?.body).toEqual({ template: 'datentraeger' });
    });
  });

  /** Wartet auf den Dialog mit diesem Titel samt Namensfeld (Fluent rendert verzögert, siehe findDialog). */
  async function openDialogNameBox(title: string): Promise<{ dialog: HTMLElement; nameBox: HTMLElement }> {
    const dialog = await findDialog(title);
    const nameBox = await within(dialog).findByRole('textbox', { name: 'Name', hidden: true }, { timeout: SLOW_UI_MS });
    return { dialog, nameBox };
  }

  it('Speichern unter „Test“ ruft PUT, Als Vorlage speichern ruft POST /templates mit document', async () => {
    const { api, user } = setup({
      extra: { 'POST /api/v1/templates': () => ({ name: 'Meine' }) },
    });
    await addText(api, user);
    await user.click(screen.getByRole('button', { name: 'Speichern unter' }));
    let { dialog, nameBox } = await openDialogNameBox('Speichern unter');
    await user.type(nameBox, 'Test');
    await user.click(within(dialog).getByRole('button', { name: 'Speichern', hidden: true }));
    await waitFor(() => expect(api.calls.some((c) => c.method === 'PUT' && c.path === '/api/v1/documents/Test')).toBe(true));
    await waitFor(() => expect(anyDialogInDom()).toBe(false), { timeout: SLOW_UI_MS });

    await user.click(await screen.findByRole('button', { name: 'Als Vorlage speichern' }));
    ({ dialog, nameBox } = await openDialogNameBox('Als Vorlage speichern'));
    expect(nameBox).toHaveValue('Test');
    await user.clear(nameBox);
    await user.type(nameBox, 'Meine');
    await user.click(within(dialog).getByRole('button', { name: 'Speichern', hidden: true }));
    await waitFor(() => {
      const call = api.calls.find((c) => c.method === 'POST' && c.path === '/api/v1/templates');
      expect(call?.body).toMatchObject({ name: 'Meine', overwrite: false });
      expect((call?.body as { document: LabelDocumentJson }).document.objects).toHaveLength(1);
    });
  });

  it('Drucken ist bei Fehlern gesperrt und sendet sonst die Dokument-Quelle', async () => {
    let ok = false;
    const { api, user } = setup({
      render: () => ({ ok, errors: ok ? [] : ['Label ist leer'] }),
      extra: { 'POST /api/v1/labels/print': () => fixtures.outcomeJson() },
    });
    await waitFor(() => expect(renders(api).length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Drucken' })).toBeDisabled());
    ok = true;
    await addText(api, user);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Drucken' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Drucken' }));
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/labels/print')).toBe(true));
    const body = api.calls.find((c) => c.path === '/api/v1/labels/print')?.body as { source: { kind: string; document: LabelDocumentJson } };
    expect(body.source.kind).toBe('document');
    expect(body.source.document.objects).toHaveLength(1);
  });

  it('Bild einfügen: Datei auswählen ruft /editor/image und danach new-object image mit png', async () => {
    const { api, user } = setup({
      extra: { 'POST /api/v1/editor/image': () => ({ png: 'UE5H', width: 40, height: 40 }) },
    });
    await waitFor(() => expect(renders(api).length).toBeGreaterThan(0));
    const file = new File([new Uint8Array([137, 80, 78, 71])], 'logo.png', { type: 'image/png' });
    await user.upload(screen.getByLabelText('Bilddatei'), file);
    await waitFor(() => expect(api.calls.some((c) => c.path === '/api/v1/editor/new-object')).toBe(true));
    const upload = api.calls.find((c) => c.path === '/api/v1/editor/image');
    expect(upload?.body).toMatchObject({ name: 'logo.png' });
    expect(typeof (upload?.body as { data_b64: string }).data_b64).toBe('string');
    const created = api.calls.find((c) => c.path === '/api/v1/editor/new-object')?.body;
    expect(created).toMatchObject({ preset: 'image', png: 'UE5H' });
  });

  it('Eigenschaften: QR ohne Decoder zeigt „Nicht rückgelesen“ statt Fehler', async () => {
    const { user } = setup({
      route: '/editor?dokument=QR',
      render: (doc) => ({
        editor: {
          ...overlay(doc),
          codes: { qr1: { kind: 'qr', module_dots: 4, decodes: false, checked: false, inverted: false, version: 3 } },
        },
      }),
    });
    await openTab(user, 'Ebenen');
    await user.click(screen.getByRole('option', { name: /qr1/ }));
    await openTab(user, 'Eigenschaften');
    expect(await screen.findByText('Nicht rückgelesen')).toBeInTheDocument();
    expect(screen.queryByText('Selbsttest: nicht lesbar')).toBeNull();
  });

  it('Eigenschaften: QR mit Decoder und fehlgeschlagenem Selbsttest bleibt Fehler', async () => {
    const { user } = setup({
      route: '/editor?dokument=QR',
      render: (doc) => ({
        editor: {
          ...overlay(doc),
          codes: { qr1: { kind: 'qr', module_dots: 4, decodes: false, checked: true, inverted: false, version: 3 } },
        },
      }),
    });
    await openTab(user, 'Ebenen');
    await user.click(screen.getByRole('option', { name: /qr1/ }));
    await openTab(user, 'Eigenschaften');
    expect(await screen.findByText('Selbsttest: nicht lesbar')).toBeInTheDocument();
    expect(screen.queryByText('Nicht rückgelesen')).toBeNull();
  });
});
