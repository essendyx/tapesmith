/** Endpunkte /api/v1/homelab/settings und /homelab/check (Einstellungskarten der Module, Homelab-Übersicht). */
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiGet, apiPatch } from '../../api/client';
import type { HomelabCheckJson, HomelabSettingsJson } from './types';

export const homelabKeys = {
  settings: ['homelab', 'settings'] as const,
  check: ['homelab', 'check'] as const,
};

export function useHomelabSettings(opts?: { enabled?: boolean }): UseQueryResult<HomelabSettingsJson> {
  return useQuery({
    queryKey: homelabKeys.settings,
    queryFn: ({ signal }) => apiGet<HomelabSettingsJson>('/api/v1/homelab/settings', signal),
    enabled: opts?.enabled ?? true,
  });
}

export function useHomelabCheck(opts?: { enabled?: boolean }): UseQueryResult<HomelabCheckJson> {
  return useQuery({
    queryKey: homelabKeys.check,
    queryFn: ({ signal }) => apiGet<HomelabCheckJson>('/api/v1/homelab/check', signal),
    enabled: opts?.enabled ?? true,
  });
}

export function patchHomelabSettings(changes: Record<string, unknown>): Promise<HomelabSettingsJson> {
  return apiPatch<HomelabSettingsJson>('/api/v1/homelab/settings', { changes });
}
