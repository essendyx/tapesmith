/** Endpunkte der Seite Zugriff. */
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiDelete, apiGet, apiPatch, apiPost } from '../../api/client';
import type { AccessJson, CreateTokenResponse, Role } from './types';

/** Query-Schlüssel der Zugriffsseite (auch von der SSE-Invalidierung in `api/events.tsx` verwendet). */
export const ACCESS_KEY = ['access'] as const;

export function useAccess(): UseQueryResult<AccessJson> {
  return useQuery({
    queryKey: ACCESS_KEY,
    queryFn: ({ signal }) => apiGet<AccessJson>('/api/v1/access', signal),
  });
}

/** Sendet nur die geänderten Schlüssel (z. B. `"lan.enabled"`); die Antwort ersetzt die Query-Daten. */
export function patchAccessSettings(changes: Record<string, unknown>): Promise<AccessJson> {
  return apiPatch<AccessJson>('/api/v1/access/settings', { changes });
}

export function createAccessToken(name: string, role: Role): Promise<CreateTokenResponse> {
  return apiPost<CreateTokenResponse>('/api/v1/access/tokens', { name, role });
}

export function revokeAccessToken(id: string): Promise<Record<string, never>> {
  return apiDelete<Record<string, never>>(`/api/v1/access/tokens/${encodeURIComponent(id)}`);
}

export function telegramTest(): Promise<{ ok: boolean; error: string | null }> {
  return apiPost<{ ok: boolean; error: string | null }>('/api/v1/access/telegram/test', {});
}
