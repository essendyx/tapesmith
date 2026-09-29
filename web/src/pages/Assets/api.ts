/** Endpunkte der Seite „Assets" (/homelab/assets). */
import { apiDownload, apiGet, apiPost, apiPut } from '../../api/client';
import type {
  AssetCreateBody,
  AssetCreateResponse,
  AssetImportBody,
  AssetJson,
  AssetLabelResponse,
  AssetsListResponse,
  AssetTableResponse,
  AssetUpdateBody,
  AssetUpdateResponse,
  AssetVaultNoteResponse,
} from './types';

export function fetchAssets(status: string, query: string, signal?: AbortSignal): Promise<AssetsListResponse> {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  if (query) params.set('query', query);
  const qs = params.toString();
  return apiGet<AssetsListResponse>(`/api/v1/homelab/assets${qs ? `?${qs}` : ''}`, signal);
}

export function createAssets(body: Partial<AssetCreateBody>): Promise<AssetCreateResponse> {
  return apiPost<AssetCreateResponse>('/api/v1/homelab/assets', body);
}

export function importAsset(body: Partial<AssetImportBody>): Promise<AssetJson> {
  return apiPost<AssetJson>('/api/v1/homelab/assets/import', body);
}

export function updateAsset(id: string, body: AssetUpdateBody): Promise<AssetUpdateResponse> {
  return apiPut<AssetUpdateResponse>(`/api/v1/homelab/assets/${encodeURIComponent(id)}`, body);
}

export function voidAsset(id: string, reason: string): Promise<AssetJson> {
  return apiPost<AssetJson>(`/api/v1/homelab/assets/${encodeURIComponent(id)}/void`, { reason });
}

export function fetchAssetLabel(id: string, signal?: AbortSignal): Promise<AssetLabelResponse> {
  return apiGet<AssetLabelResponse>(`/api/v1/homelab/assets/${encodeURIComponent(id)}/label`, signal);
}

export function createAssetsTable(ids: string[]): Promise<AssetTableResponse> {
  return apiPost<AssetTableResponse>('/api/v1/homelab/assets/table', { ids });
}

export function exportAssetsCsv(): Promise<void> {
  return apiDownload('/api/v1/homelab/assets/export.csv', undefined, 'assets.csv', 'GET');
}

/** Legt die Vault-Notiz `Assets/<ID>` an (409, wenn sie schon existiert). */
export function createAssetVaultNote(id: string): Promise<AssetVaultNoteResponse> {
  return apiPost<AssetVaultNoteResponse>(`/api/v1/homelab/assets/${encodeURIComponent(id)}/vault-note`);
}
