/** Aufrufe des Editors (Editor-, Vorlagen- und Aktions-Routen des Servers). Kernlogik bleibt in Python. */
import { apiDelete, apiGet, apiPost, apiPut } from '../../api/client';
import type {
  DocumentInfo,
  EditOp,
  EditResult,
  EditorPreset,
  IconInfoJson,
  LabelDocumentJson,
  PendingJson,
  SaveTemplateRequest,
  SnapRequest,
  SnapResult,
  TargetJson,
  TemplateDetail,
} from '../../api/types';

export const DRAFT_NAME = '_entwurf';
export const EMPTY_DOC: LabelDocumentJson = { version: 1, objects: [] };

const enc = encodeURIComponent;

export function newObject(
  document: LabelDocumentJson,
  preset: EditorPreset,
  extra?: { at?: [number, number]; png?: string },
): Promise<EditResult> {
  const body: Record<string, unknown> = { document, preset };
  if (extra?.at) body.at = [Math.round(extra.at[0]), Math.round(extra.at[1])];
  if (extra?.png) body.png = extra.png;
  return apiPost<EditResult>('/api/v1/editor/new-object', body);
}

export function applyOp(document: LabelDocumentJson, op: EditOp, ids: string[], params: Record<string, unknown> = {}): Promise<EditResult> {
  return apiPost<EditResult>('/api/v1/editor/op', { document, op, ids, params });
}

export function snap(req: SnapRequest, signal?: AbortSignal): Promise<SnapResult> {
  return apiPost<SnapResult>('/api/v1/editor/snap', req, signal);
}

export function uploadImage(dataB64: string, name?: string): Promise<{ png: string; width: number; height: number }> {
  return apiPost('/api/v1/editor/image', name ? { data_b64: dataB64, name } : { data_b64: dataB64 });
}

export function listDocuments(signal?: AbortSignal): Promise<{ documents: DocumentInfo[] }> {
  return apiGet('/api/v1/documents', signal);
}

export function loadDocument(name: string): Promise<{ name: string; document: LabelDocumentJson }> {
  return apiGet(`/api/v1/documents/${enc(name)}`);
}

export function saveDocument(name: string, document: LabelDocumentJson): Promise<DocumentInfo> {
  return apiPut(`/api/v1/documents/${enc(name)}`, { document });
}

export function deleteDocument(name: string): Promise<Record<string, never>> {
  return apiDelete(`/api/v1/documents/${enc(name)}`);
}

export function fromHistory(id: string | number): Promise<{ document: LabelDocumentJson }> {
  return apiPost(`/api/v1/documents/from-history/${enc(String(id))}`, {});
}

export function fromTemplate(template: string, values?: Record<string, string>): Promise<{ document: LabelDocumentJson }> {
  return apiPost('/api/v1/documents/from-template', values ? { template, values } : { template });
}

export function fetchPending(id: string): Promise<PendingJson> {
  return apiGet(`/api/v1/integration/pending/${enc(id)}`);
}

export function listIcons(query: string, category: string, limit = 120, signal?: AbortSignal): Promise<{ icons: IconInfoJson[] }> {
  const qs = new URLSearchParams({ query, category, limit: String(limit) });
  return apiGet(`/api/v1/icons?${qs.toString()}`, signal);
}

export function iconCategories(signal?: AbortSignal): Promise<{ categories: string[]; labels?: Record<string, string> }> {
  return apiGet('/api/v1/icons/categories', signal);
}

export function uploadUserIcon(name: string, dataB64: string): Promise<{ ref: string }> {
  return apiPost('/api/v1/icons/user', { name, data_b64: dataB64 });
}

export function listTargets(signal?: AbortSignal): Promise<{ targets: TargetJson[] }> {
  return apiGet('/api/v1/targets', signal);
}

export function saveAsTemplate(req: SaveTemplateRequest): Promise<TemplateDetail> {
  return apiPost('/api/v1/templates', req);
}
