/** Endpunkte /api/v1/modules: Beschreibung mit Zustand, Modul ein- und ausschalten. */
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiGet, apiPut } from '../api/client';
import { qk } from '../api/core';
import type { ModuleDef } from './index';

export interface ModulesJson {
  modules: (ModuleDef & { enabled: boolean })[];
  enabled: string[];
}

export function useModulesList(): UseQueryResult<ModulesJson> {
  return useQuery({ queryKey: qk.modules, queryFn: ({ signal }) => apiGet<ModulesJson>('/api/v1/modules', signal) });
}

export function putModule(id: string, enabled: boolean): Promise<ModulesJson> {
  return apiPut<ModulesJson>(`/api/v1/modules/${encodeURIComponent(id)}`, { enabled });
}
