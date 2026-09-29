/** Client für Entwürfe; alle Aufrufe tragen die Fenster-Sitzung. */
import { apiDelete, apiGet, apiPost, apiPut } from './client';
import { windowSessionId } from './session';
import type { Draft, DraftInfo, DraftListJson, DraftPutBody } from './types';

const BASE = '/api/v1/drafts';

function draftPath(id: string): string {
  return `${BASE}/${encodeURIComponent(id)}`;
}

export function listDrafts(signal?: AbortSignal): Promise<DraftListJson> {
  return apiGet<DraftListJson>(`${BASE}?session=${encodeURIComponent(windowSessionId())}`, signal);
}

export function getDraft(id: string): Promise<Draft> {
  return apiGet<Draft>(draftPath(id));
}

export function putDraft(id: string, body: DraftPutBody): Promise<DraftInfo> {
  return apiPut<DraftInfo>(draftPath(id), { ...body, session: windowSessionId() });
}

export function deleteDraft(id: string): Promise<Record<string, never>> {
  return apiDelete<Record<string, never>>(draftPath(id));
}

export function adoptDraft(id: string): Promise<DraftInfo> {
  return apiPost<DraftInfo>(`${draftPath(id)}/adopt`, { session: windowSessionId() });
}

export function heartbeat(): Promise<{ alive_s: number }> {
  return apiPost<{ alive_s: number }>(`${BASE}/heartbeat`, { session: windowSessionId() });
}
