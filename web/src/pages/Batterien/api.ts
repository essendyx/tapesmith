/** Endpunkte der Seite Batterien. */
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiGet, apiPost, apiPut } from '../../api/client';
import type { BatteriesJson, TableRequest, TableResponse, TodoRequest, TodoResponse } from './types';

export const batterienKeys = {
  list: (below?: number) => ['homelab', 'ha', 'batteries', below ?? null] as const,
};

export function useBatteries(below?: number): UseQueryResult<BatteriesJson> {
  return useQuery({
    queryKey: batterienKeys.list(below),
    queryFn: ({ signal }) =>
      apiGet<BatteriesJson>(
        below !== undefined ? `/api/v1/homelab/ha/batteries?below=${below}` : '/api/v1/homelab/ha/batteries',
        signal,
      ),
  });
}

export function setBatteryType(entityId: string, batteryType: string | null): Promise<{ ok: boolean }> {
  return apiPut<{ ok: boolean }>('/api/v1/homelab/ha/battery-type', { entity_id: entityId, battery_type: batteryType });
}

export function postBatteryTable(body: TableRequest): Promise<TableResponse> {
  return apiPost<TableResponse>('/api/v1/homelab/ha/table', body);
}

export function postTodo(body: TodoRequest): Promise<TodoResponse> {
  return apiPost<TodoResponse>('/api/v1/homelab/ha/todo', body);
}
