/** Endpunkte der Seite Kabel: /api/v1/homelab/kabel/*. */
import { apiDelete, apiGet, apiPost } from '../../api/client';
import type { ColumnMapping, IdsRequest, IdsResultJson, KabelRegisterJson, NetboxPreviewJson, NetboxTableJson } from './types';

export function previewNetbox(
  csvB64: string,
  mapping: ColumnMapping | null,
  assignIds: boolean,
  saveMapping: boolean,
): Promise<NetboxPreviewJson> {
  return apiPost<NetboxPreviewJson>('/api/v1/homelab/kabel/netbox', {
    csv_b64: csvB64,
    mapping,
    assign_ids: assignIds,
    save_mapping: saveMapping,
  });
}

export function openNetboxSeries(
  csvB64: string,
  mapping: ColumnMapping | null,
  assignIds: boolean,
  template: string,
  register: boolean,
): Promise<NetboxTableJson> {
  return apiPost<NetboxTableJson>('/api/v1/homelab/kabel/table', {
    csv_b64: csvB64,
    mapping,
    assign_ids: assignIds,
    template,
    register,
  });
}

export function generateIds(req: IdsRequest): Promise<IdsResultJson> {
  return apiPost<IdsResultJson>('/api/v1/homelab/kabel/ids', req);
}

export function fetchKabelRegister(query: string): Promise<KabelRegisterJson> {
  const qs = query ? `?query=${encodeURIComponent(query)}` : '';
  return apiGet<KabelRegisterJson>(`/api/v1/homelab/kabel/register${qs}`);
}

export function deleteKabelEntry(id: string): Promise<{ removed: boolean }> {
  return apiDelete<{ removed: boolean }>(`/api/v1/homelab/kabel/register/${encodeURIComponent(id)}`);
}
