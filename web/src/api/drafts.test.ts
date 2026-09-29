import { describe, expect, it } from 'vitest';
import { adoptDraft, deleteDraft, getDraft, heartbeat, listDrafts, putDraft } from './drafts';
import { WINDOW_SESSION_KEY, windowSessionId } from './session';
import { mockApi } from '../test/utils';
import type { DraftInfo, LabelDocumentJson } from './types';
import { setTokenForTests } from './client';

const doc: LabelDocumentJson = { version: 1, objects: [] };

function info(o: Partial<DraftInfo> = {}): DraftInfo {
  return {
    id: 'entwurf-1',
    title: 'Entwurf',
    doc_name: null,
    dirty: true,
    updated: '2026-09-28T10:00:00',
    objects: 0,
    order: 0,
    session: windowSessionId(),
    ...o,
  };
}

describe('windowSessionId', () => {
  it('ist innerhalb eines Fensters stabil und liegt in sessionStorage', () => {
    const a = windowSessionId();
    const b = windowSessionId();
    expect(a).toBe(b);
    expect(a).toMatch(/^[A-Za-z0-9-]{8,64}$/);
    expect(sessionStorage.getItem(WINDOW_SESSION_KEY)).toBe(a);
  });

  it('übernimmt eine vorhandene Kennung aus sessionStorage', () => {
    sessionStorage.setItem(WINDOW_SESSION_KEY, 'fenster-1234');
    expect(windowSessionId()).toBe('fenster-1234');
  });
});

describe('drafts', () => {
  it('jede Funktion nutzt Methode, Pfad und Fenster-Sitzung', async () => {
    setTokenForTests('tok');
    const sid = windowSessionId();
    const api = mockApi({
      'GET /api/v1/drafts': () => ({ drafts: [info()], own: [info()], orphaned: [] }),
      'GET /api/v1/drafts/:id': ({ params }) => ({ ...info({ id: params.id }), document: doc }),
      'PUT /api/v1/drafts/:id': ({ params }) => info({ id: params.id }),
      'DELETE /api/v1/drafts/:id': () => ({}),
      'POST /api/v1/drafts/:id/adopt': ({ params }) => info({ id: params.id }),
      'POST /api/v1/drafts/heartbeat': () => ({ alive_s: 90 }),
    });

    const list = await listDrafts();
    expect(list.own).toHaveLength(1);
    expect((await getDraft('entwurf-1')).document).toEqual(doc);
    await putDraft('entwurf-1', { title: 'Entwurf', doc_name: null, document: doc, dirty: true, order: 2 });
    await deleteDraft('entwurf-1');
    await adoptDraft('entwurf-2');
    expect(await heartbeat()).toEqual({ alive_s: 90 });

    expect(api.calls.map((c) => `${c.method} ${c.path}`)).toEqual([
      `GET /api/v1/drafts?session=${sid}`,
      'GET /api/v1/drafts/entwurf-1',
      'PUT /api/v1/drafts/entwurf-1',
      'DELETE /api/v1/drafts/entwurf-1',
      'POST /api/v1/drafts/entwurf-2/adopt',
      'POST /api/v1/drafts/heartbeat',
    ]);
    expect(api.calls[2]?.body).toEqual({ title: 'Entwurf', doc_name: null, document: doc, dirty: true, order: 2, session: sid });
    expect(api.calls[4]?.body).toEqual({ session: sid });
    expect(api.calls[5]?.body).toEqual({ session: sid });
    expect(api.unmatched).toEqual([]);
  });
});
